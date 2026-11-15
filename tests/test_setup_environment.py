"""Windows setup ignores inherited and OS-configured proxies without changing user settings."""

import os

from scripts import bootstrap, release_common
from scripts.setup_environment import installation_environment


def test_windows_setup_sanitizes_proxy_variants_without_mutating_source():
    inherited = dict(
        HTTP_PROXY="http://unreachable",
        https_proxy="http://unreachable",
        All_Proxy="socks5://unreachable",
        PIP_PROXY="http://unreachable",
        NO_PROXY="internal",
        PIP_CONFIG_FILE="custom.ini",
        PATH="tools",
    )
    snapshot = inherited.copy()
    environment = installation_environment(inherited, "win32")
    assert {key.lower() for key in environment if key.lower().endswith("_proxy")} == {"no_proxy"}
    assert environment["NO_PROXY"] == environment["no_proxy"] == "*"
    assert environment["PIP_CONFIG_FILE"] == "nul" and environment["PATH"] == "tools"
    assert inherited == snapshot
    assert installation_environment(inherited, "linux") == inherited


def test_bootstrap_passes_direct_environment_to_installer(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://unreachable")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "outside-the-repo")
    monkeypatch.setattr(bootstrap.sys, "platform", "win32")
    calls = []

    class Process:
        stdout = iter(["installed\n"])

        def wait(self):
            return 0

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(bootstrap.subprocess, "Popen", popen)
    bootstrap.run(["uv", "sync", "--locked"])
    assert calls[0][0] == ["uv", "sync", "--locked"]
    assert "HTTPS_PROXY" not in calls[0][1]["env"]
    assert calls[0][1]["env"]["NO_PROXY"] == "*"
    assert os.environ["HTTPS_PROXY"] == "http://unreachable"
    assert calls[0][1]["env"]["UV_PROJECT_ENVIRONMENT"] == str(bootstrap.ROOT / ".venv")
    assert calls[0][1]["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert os.environ["UV_PROJECT_ENVIRONMENT"] == "outside-the-repo"


def test_windows_runtime_downloads_bypass_registry_proxy(monkeypatch):
    monkeypatch.setattr(release_common.sys, "platform", "win32")
    calls = []

    class Opener:
        def open(self, request, **kwargs):
            calls.append((request, kwargs))
            return "direct response"

    def build(handler):
        assert handler.proxies == {}
        return Opener()

    monkeypatch.setattr(release_common.urllib.request, "build_opener", build)
    assert release_common.open_url("https://example.test/runtime") == "direct response"
    assert calls == [("https://example.test/runtime", {"timeout": 90})]
