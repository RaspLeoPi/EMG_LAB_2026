"""Verified app-local runtime preparation shared by clone setup and release builds."""

import json
import re
import shutil
import tempfile
from pathlib import Path

try:
    from .release_common import download, extract_zip, file_hash, open_url, write_json
except ImportError:
    from release_common import download, extract_zip, file_hash, open_url, write_json

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLES = {"python": "tools/python.exe", "uv": "uv.exe", "dotnet": "dotnet.exe"}
FOLDERS = {"python": "python313", "uv": "uv", "dotnet": "dotnet"}


def runtime_specs(root=ROOT):
    fields = {}
    for line in (Path(root) / "scripts/runtime.lock").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            fields.setdefault(key.strip(), []).append(value.strip())
    specs = {
        "python": dict(
            version=fields["version"][0],
            urls=fields["url"],
            expected=fields["sha256"][0],
            algorithm="sha256",
        )
    }
    for key in ("uv", "dotnet"):
        specs[key] = dict(
            version=fields[key + "_version"][0],
            urls=fields[key + "_url"],
            algorithm="sha512" if key == "dotnet" else "sha256",
        )
        digest = fields.get(key + "_" + specs[key]["algorithm"])
        if digest:
            specs[key]["expected"] = digest[0]
        else:
            specs[key]["checksum_url"] = fields[key + "_sha256_url"][0]
    for key, spec in specs.items():
        if not re.fullmatch(r"\d+\.\d+\.\d+", spec["version"]):
            raise ValueError(f"Invalid {key} runtime version.")
        if any(not url.startswith("https://") for url in spec["urls"]):
            raise ValueError("Runtime sources must use HTTPS.")
        expected = spec.get("expected")
        if expected and not re.fullmatch(
            "[0-9a-f]{" + ("128" if spec["algorithm"] == "sha512" else "64") + "}", expected
        ):
            raise ValueError(f"Invalid {key} runtime digest.")
        spec["filename"] = f"{key}-{spec['version']}-windows." + (
            "nupkg" if key == "python" else "zip"
        )
    return specs


def fetch_payload(spec, cache):
    cache = Path(cache)
    expected = spec.get("expected")
    if expected is None:
        with open_url(spec["checksum_url"], timeout=90) as response:
            expected = response.read().decode("ascii").split()[0].lower()
        if not re.fullmatch("[0-9a-f]{64}", expected):
            raise ValueError("Invalid upstream runtime checksum.")
    errors = []
    for url in spec["urls"]:
        for attempt in range(3):
            try:
                path = download(url, cache / spec["filename"], expected, spec["algorithm"])
                return path, dict(
                    filename=path.name,
                    version=spec["version"],
                    url=url,
                    sha256=file_hash(path),
                    verified_hash=expected,
                    verified_algorithm=spec["algorithm"],
                )
            except OSError as error:
                errors.append(str(error))
    raise RuntimeError("Runtime download failed using direct connections: " + "; ".join(errors))


def ensure_runtime(key, root=ROOT):
    root = Path(root)
    spec = runtime_specs(root)[key]
    target = root / ".runtime" / FOLDERS[key]
    executable = target / EXECUTABLES[key]
    stamp = target / "emg-runtime.json"
    if stamp.is_file() and executable.is_file():
        try:
            state = json.loads(stamp.read_text(encoding="utf-8"))
            if state["spec"] == spec and all(
                file_hash(target / name) == digest for name, digest in state["files"].items()
            ):
                return executable
        except (ValueError, KeyError, OSError):
            pass
    print(f"Preparing local {key} {spec['version']}...", flush=True)
    archive, provenance = fetch_payload(spec, root / ".runtime/downloads")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise ValueError("Runtime directory may not be a symlink.")
    with tempfile.TemporaryDirectory(prefix=key + "-", dir=target.parent) as staging:
        staged = Path(staging) / "payload"
        extract_zip(archive, staged)
        if key == "uv" and not (staged / "uv.exe").is_file():
            candidates = list(staged.rglob("uv.exe"))
            if len(candidates) != 1:
                raise ValueError("Expected one uv.exe in archive.")
            shutil.copy2(candidates[0], staged / "uv.exe")
        if not (staged / EXECUTABLES[key]).is_file():
            raise ValueError(f"Missing {key} executable in verified archive.")
        files = {
            p.relative_to(staged).as_posix(): file_hash(p) for p in staged.rglob("*") if p.is_file()
        }
        write_json(staged / stamp.name, dict(spec=spec, artifact=provenance, files=files))
        if target.exists():
            shutil.rmtree(target)
        staged.replace(target)
    return executable
