"""Create this copy's environment; prefer the bundled wheels, never copy a venv."""

import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path

try:
    from .offline_bootstrap import setup_lock
    from .release_common import file_hash, write_json
    from .setup_environment import application_environment, installation_environment
    from .windows_runtime import ensure_runtime
except ImportError:
    from offline_bootstrap import setup_lock
    from release_common import file_hash, write_json
    from setup_environment import application_environment, installation_environment
    from windows_runtime import ensure_runtime


ROOT = Path(__file__).resolve().parents[1]
WIN, DARWIN = "win32", "darwin"


def run(args):
    command = [str(value) for value in args]
    logs = ROOT / "local"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "setup.log").open("a", encoding="utf-8") as log:
        log.write("Running: " + " ".join(command) + "\n")
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=dict(
                application_environment(ROOT, installation_environment()),
                PIP_DISABLE_PIP_VERSION_CHECK="1",
                PYTHONIOENCODING="utf-8",
                UV_PROJECT_ENVIRONMENT=str(ROOT / ".venv"),
                UV_CACHE_DIR=str(ROOT / ".cache/uv"),
                UV_PYTHON_DOWNLOADS="never",
            ),
        )
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
            log.flush()
        code = process.wait()
        if code:
            raise subprocess.CalledProcessError(code, command)


def gate():
    """放行 win32（学生全功能档）与 darwin/arm64（教师模拟开发档，ADR 0002），均需 Python 3.13。"""
    platform_name, machine, version = sys.platform, platform.machine(), sys.version_info[:2]
    if platform_name == WIN:
        if version != (3, 13):
            raise RuntimeError("本发行包适用于 Windows x64 / Python 3.13。请使用随包 install.cmd。")
        if struct.calcsize("P") != 8 or machine.lower() not in ("amd64", "x86_64"):
            raise RuntimeError("Windows x64 Python is required; use install.cmd.")
        return
    if platform_name == DARWIN:
        if version != (3, 13):
            raise RuntimeError(
                "macOS 开发档需要自装 Python 3.13（如 brew install python@3.13 或从 python.org 下载），再运行 python3 scripts/bootstrap.py。"
            )
        if machine != "arm64":
            raise RuntimeError(
                "macOS 仅支持 arm64（Apple Silicon）开发档；Intel 与 Rosetta 解释器不支持。"
            )
        return
    raise RuntimeError(
        "本包面向 Windows x64（学生全功能档）与 macOS arm64（教师模拟开发档），不支持当前平台："
        + platform_name
    )


def offline_install(platform_name, wheelhouse_present):
    """离线 wheelhouse 只随 Windows 学生包分发；darwin 一律在线安装。"""
    return platform_name == WIN and wheelhouse_present


def venv_python(target, platform_name):
    return target / ("Scripts/python.exe" if platform_name == WIN else "bin/python")


def find_uv():
    if sys.platform == WIN:
        return ensure_runtime("uv", ROOT)
    installed = shutil.which("uv")
    if installed:
        return Path(installed)
    raise RuntimeError("Install uv, then run uv sync --locked from this repository.")


def prepare_source():
    if not (ROOT / "uv.lock").is_file():
        raise RuntimeError("Missing uv.lock. Restore the complete source repository.")
    with setup_lock(ROOT):
        state = ROOT / "local/source-setup.json"
        state.unlink(missing_ok=True)
        if sys.platform == WIN:
            ensure_runtime("dotnet", ROOT)
        uv = find_uv()
        print("Synchronizing locked packages using direct connections...", flush=True)
        run([uv, "sync", "--locked", "--python", sys.executable])
        python = venv_python(ROOT / ".venv", sys.platform)
        run([uv, "pip", "check", "--python", python])
        run([python, "scripts/download_robot_assets.py", "--check"])
        run([python, "scripts/check_hand_assets.py"])
        run([python, "scripts/check_installation.py"])
        write_json(
            state,
            dict(location=str(ROOT.resolve()), dependency_lock_sha256=file_hash(ROOT / "uv.lock")),
        )
        return python


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    gate()
    if (ROOT / "OFFLINE_RELEASE.json").is_file():
        try:
            from .offline_bootstrap import ensure_environment
        except ImportError:
            from offline_bootstrap import ensure_environment
        python = ensure_environment(ROOT, repair=True)
        run([python, "scripts/check_installation.py"])
    else:
        prepare_source()
    print(
        "安装完成。双击 start.cmd 开始使用；无需连接设备。"
        if sys.platform == WIN
        else "安装完成。运行 uv run --locked python main.py 开始使用。",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("安装未完成：" + str(error), flush=True)
        try:
            (ROOT / "local").mkdir(parents=True, exist_ok=True)
            with (ROOT / "local/setup.log").open("a", encoding="utf-8") as log:
                log.write("Setup failed: " + str(error) + "\n")
        except OSError:
            pass
        raise SystemExit(1)
