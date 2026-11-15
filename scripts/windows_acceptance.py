"""Offline Windows 10/11 acceptance. Never connects physical acquisition/output devices."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .offline_bootstrap import ensure_environment
    from .release_common import write_json
    from .setup_environment import application_environment, installation_environment
except ImportError:
    from offline_bootstrap import ensure_environment
    from release_common import write_json
    from setup_environment import application_environment, installation_environment

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "local/windows-acceptance.json")
    parser.add_argument(
        "--relocation-test",
        action="store_true",
        help="Also copy the package to a path with spaces/Chinese characters and rebuild its environment offline.",
    )
    parser.add_argument("--workflow", choices=["offline", "source"], default="offline")
    args = parser.parse_args()
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise RuntimeError("Run acceptance on Windows 10/11 x64.")
    result = dict(
        platform=sys.platform,
        windows_version=list(sys.getwindowsversion()),
        checks=[],
        real_hardware="not_run",
        workflow=args.workflow,
    )
    try:
        if args.workflow == "offline":
            python = ensure_environment(ROOT)
            assert ensure_environment(ROOT) == python
            result["checks"].append(dict(name="offline_first_and_repeat_launch", passed=True))
        else:
            if not (ROOT / "local/source-setup.json").is_file():
                raise RuntimeError("Run acceptance.cmd to prepare the source installation first.")
            python = ROOT / ".venv/Scripts/python.exe"
            result["checks"].append(dict(name="source_installation_completed", passed=True))
        environment = dict(
            application_environment(ROOT, installation_environment()),
            UV_OFFLINE="1",
            UV_PYTHON_DOWNLOADS="never",
            DOTNET_ROOT=str(ROOT / ".runtime/dotnet"),
        )
        environment["PATH"] = (
            str(ROOT / ".runtime/dotnet") + os.pathsep + environment.get("PATH", "")
        )
        commands = [
            (
                "synthetic_capture_training_replay",
                ["scripts/smoke_pipeline.py", "--output", "local/acceptance-smoke"],
            ),
            ("software_and_both_renderers", ["scripts/check_classroom.py", "--render"]),
            ("robot_basic_workflow", ["scripts/check_ui.py", "--physics"]),
            ("hand_basic_workflow", ["scripts/check_hand_ui.py"]),
            ("robot_seven_classes", ["scripts/check_lesson1_ui.py", "robot7"]),
            ("hand_five_classes", ["scripts/check_lesson1_ui.py", "hand5"]),
            ("offline_help", ["scripts/check_help.py"]),
            (
                "coin_route_reachability",
                ["scripts/benchmark_coin_routes.py", "--output", "local/acceptance-routes.json"],
            ),
        ]
        # Module invocation keeps the repository root importable without PYTHONPATH.
        commands = [
            (name, ["-m", command[0].removesuffix(".py").replace("/", "."), *command[1:]])
            for name, command in commands
        ]
        for name, command in commands:
            started = time.monotonic()
            process = subprocess.run([str(python), *command], cwd=ROOT, env=environment)
            result["checks"].append(
                dict(name=name, passed=process.returncode == 0, seconds=time.monotonic() - started)
            )
            write_json(args.output, result)
            if process.returncode:
                raise RuntimeError(f"Acceptance check failed: {name}")
            if name == "offline_help":
                help_result = json.loads(
                    (ROOT / "local/help-check.json").read_text(encoding="utf-8")
                )
                if help_result.get("passed") is not True:
                    result["checks"][-1]["passed"] = False
                    raise RuntimeError(
                        "Help renderer fell back or skipped; offline WebEngine acceptance is incomplete."
                    )
        if args.relocation_test:
            with tempfile.TemporaryDirectory(prefix="EMG acceptance ") as temporary:
                moved = Path(temporary) / "EMG Lab 中文路径"

                def ignore_outputs(folder, names):
                    excluded = {"__pycache__", ".pytest_cache", ".ruff_cache"}
                    if Path(folder) == ROOT:
                        excluded.update(
                            {".venv", "local", "data", ".cache", ".git", "dist", "build"}
                        )
                    return set(names) & excluded

                shutil.copytree(
                    ROOT,
                    moved,
                    ignore=ignore_outputs,
                )
                if args.workflow == "offline":
                    moved_python = ensure_environment(moved)
                else:
                    subprocess.run(
                        ["cmd.exe", "/d", "/c", "install.cmd", "--no-pause"],
                        cwd=moved,
                        env=installation_environment(),
                        check=True,
                    )
                    moved_python = moved / ".venv/Scripts/python.exe"
                moved_environment = application_environment(moved, installation_environment())
                moved_environment.update(UV_OFFLINE="1", UV_PYTHON_DOWNLOADS="never")
                subprocess.run(
                    [
                        str(moved_python),
                        "-c",
                        "from emg_lab.backend.application import ApplicationService; from emg_lab.frontend.window import MainWindow",
                    ],
                    cwd=moved,
                    env=moved_environment,
                    check=True,
                )
                result["checks"].append(dict(name="spaces_chinese_and_relocation", passed=True))
        result["passed"] = True
    except Exception as error:
        result["passed"] = False
        result["error"] = str(error)
        raise
    finally:
        write_json(args.output, result)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
