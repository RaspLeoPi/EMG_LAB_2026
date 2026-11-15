"""First-launch offline environment setup using bundled Python, uv and locked wheels."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    from .release_common import file_hash, verify_manifest, write_json
except ImportError:
    from release_common import file_hash, verify_manifest, write_json

try:
    from .setup_environment import application_environment, installation_environment
except ImportError:
    from setup_environment import application_environment, installation_environment


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def setup_lock(root):
    lock = root / "local/setup.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError(
                    "Another setup is already running. Wait for it to finish."
                ) from error
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError(
                    "Another setup is already running. Wait for it to finish."
                ) from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def environment_signature(root):
    return hashlib.sha256(
        (
            str(root.resolve())
            + file_hash(root / "requirements-offline.txt")
            + file_hash(root / "OFFLINE_RELEASE.json")
        ).encode()
    ).hexdigest()


def ensure_environment(root=ROOT, *, repair=False, runner=subprocess.run):
    root = Path(root).resolve()
    manifest = json.loads((root / "OFFLINE_RELEASE.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "emg-lab-offline-release" or manifest.get("format_version") != 1:
        raise ValueError("Unsupported offline release manifest.")
    signature = environment_signature(root)
    target = root / ".venv"
    python = target / "Scripts/python.exe"
    state = target / "emg-lab-environment.json"
    owner = root / "local/offline-install-owner.json"
    with setup_lock(root):
        if target.is_symlink():
            raise ValueError("Virtual environment may not be a symlink.")
        if not repair and state.is_file() and python.is_file():
            try:
                if json.loads(state.read_text(encoding="utf-8")).get("signature") == signature:
                    return python
            except (ValueError, OSError):
                pass
        print("Verifying offline release files...", flush=True)
        verify_manifest(root, manifest)
        bundled_python = root / ".runtime/python313/tools/python.exe"
        uv = root / ".runtime/uv/uv.exe"
        if not bundled_python.is_file() or not uv.is_file():
            raise FileNotFoundError("Bundled Python/uv is missing.")
        owned = False
        if owner.is_file():
            try:
                owned = json.loads(owner.read_text(encoding="utf-8")).get("target") == str(target)
            except (ValueError, OSError):
                pass
        if target.exists():
            if not owned and not (target / "pyvenv.cfg").is_file():
                raise ValueError(
                    "Existing .venv is not a recognized virtual environment. Rename it before repair."
                )
            shutil.rmtree(target)
        write_json(owner, dict(target=str(target)))
        environment = dict(
            application_environment(root, installation_environment()),
            UV_OFFLINE="1",
            UV_PYTHON_DOWNLOADS="never",
            UV_CACHE_DIR=str(root / ".cache/uv"),
            PYTHONIOENCODING="utf-8",
        )
        print("Creating this copy's environment; no network access is used...", flush=True)
        runner(
            [
                str(uv),
                "venv",
                "--python",
                str(bundled_python),
                "--no-python-downloads",
                str(target),
            ],
            cwd=root,
            env=environment,
            check=True,
        )
        runner(
            [
                str(uv),
                "pip",
                "sync",
                "--python",
                str(python),
                "--offline",
                "--no-index",
                "--require-hashes",
                "--find-links",
                str(root / "wheelhouse"),
                str(root / "requirements-offline.txt"),
            ],
            cwd=root,
            env=environment,
            check=True,
        )
        runner(
            [str(uv), "pip", "check", "--python", str(python)],
            cwd=root,
            env=environment,
            check=True,
        )
        runner(
            [str(python), str(root / "scripts/check_installation.py")],
            cwd=root,
            env=environment,
            check=True,
        )
        # Write the marker only after all dependencies and their requirements pass.
        write_json(state, dict(signature=signature, location=str(root)))
        owner.unlink(missing_ok=True)
        return python


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("The student offline package requires Windows x64. Development uses uv.")
    ensure_environment(repair=args.repair)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("Offline setup failed: " + str(error), file=sys.stderr)
        raise SystemExit(1)
