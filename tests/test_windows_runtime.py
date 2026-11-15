"""Verified runtimes and setup orchestration; tiny archives never become release payloads."""

import json
import zipfile

import pytest

from scripts import bootstrap
from scripts import windows_runtime as runtime
from scripts.offline_bootstrap import setup_lock
from scripts.release_common import file_hash


def archive(tmp_path, key="uv"):
    path = tmp_path / "payload.zip"
    with zipfile.ZipFile(path, "w") as output:
        output.writestr(runtime.EXECUTABLES[key], b"verified fixture only")
        output.writestr("LICENSE.txt", "fixture notice")
    return path


def test_runtime_pins_are_shared_and_complete():
    specs = runtime.runtime_specs()
    assert specs["python"]["version"] == "3.13.5"
    assert len(specs["python"]["urls"]) == 2
    assert specs["dotnet"]["version"].startswith("8.0.")
    assert specs["uv"]["checksum_url"].startswith(specs["uv"]["urls"][0])


def test_runtime_cache_checks_content_and_recovers_tampering(tmp_path, monkeypatch):
    payload = archive(tmp_path)
    spec = dict(
        version="1.2.3",
        urls=["https://example.test/runtime"],
        expected=file_hash(payload),
        algorithm="sha256",
        filename=payload.name,
    )
    monkeypatch.setattr(runtime, "runtime_specs", lambda root: {"uv": spec})
    calls = []

    def fetch(spec, cache):
        calls.append(cache)
        return payload, dict(sha256=file_hash(payload))

    monkeypatch.setattr(runtime, "fetch_payload", fetch)
    executable = runtime.ensure_runtime("uv", tmp_path)
    assert executable.read_bytes() == b"verified fixture only"
    assert (executable.parent / "LICENSE.txt").is_file()
    runtime.ensure_runtime("uv", tmp_path)
    assert len(calls) == 1
    executable.write_bytes(b"tampered")
    runtime.ensure_runtime("uv", tmp_path)
    assert len(calls) == 2 and executable.read_bytes() == b"verified fixture only"


def test_transport_retries_and_falls_back_but_digest_failure_is_fatal(tmp_path, monkeypatch):
    spec = dict(
        version="1.0.0",
        urls=["https://primary", "https://mirror"],
        expected="1" * 64,
        algorithm="sha256",
        filename="payload.zip",
    )
    payload = archive(tmp_path)
    calls = []

    def download(url, *args):
        calls.append(url)
        if url.endswith("primary"):
            raise OSError("offline")
        return payload

    monkeypatch.setattr(runtime, "download", download)
    assert runtime.fetch_payload(spec, tmp_path)[0] == payload
    assert calls == ["https://primary"] * 3 + ["https://mirror"]

    def corrupt(*args):
        raise ValueError("Checksum mismatch")

    monkeypatch.setattr(runtime, "download", corrupt)
    with pytest.raises(ValueError, match="Checksum"):
        runtime.fetch_payload(spec, tmp_path)


def test_setup_lock_rejects_a_second_installer(tmp_path):
    with setup_lock(tmp_path):
        with pytest.raises(RuntimeError, match="already running"):
            with setup_lock(tmp_path):
                pytest.fail("Acquired twice")


def test_source_bootstrap_owns_all_missing_components_and_stamps_only_success(
    tmp_path, monkeypatch
):
    (tmp_path / "uv.lock").write_text("lock fixture")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    runtimes, commands = [], []

    def ensure(key, root):
        runtimes.append(key)
        return root / ".runtime" / key / (key + ".exe")

    monkeypatch.setattr(bootstrap, "ensure_runtime", ensure)
    monkeypatch.setattr(bootstrap, "run", commands.append)
    bootstrap.prepare_source()
    assert runtimes == ["dotnet", "uv"]
    assert commands[0][1:3] == ["sync", "--locked"]
    assert commands[-1][-1] == "scripts/check_installation.py"
    stamp = tmp_path / "local/source-setup.json"
    assert json.loads(stamp.read_text())["location"] == str(tmp_path)

    def fail(command):
        raise RuntimeError("transport failed")

    monkeypatch.setattr(bootstrap, "run", fail)
    with pytest.raises(RuntimeError):
        bootstrap.prepare_source()
    assert not stamp.exists()


def test_wrong_architecture_rejected_before_setup(monkeypatch):
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(bootstrap.struct, "calcsize", lambda value: 4)
    with pytest.raises(RuntimeError, match="x64"):
        bootstrap.gate()
