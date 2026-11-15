"""Check native application imports without connecting acquisition or output hardware."""

import json
import platform
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform == "win32" and (
        struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64")
    ):
        raise RuntimeError("Use Windows x64 Python with install.cmd.")
    try:
        import mujoco  # noqa: F401
        import numpy  # noqa: F401
        import onnxruntime  # noqa: F401
        import scipy.signal  # noqa: F401
        import torch  # noqa: F401
        from PySide6 import QtWidgets  # noqa: F401
    except (ImportError, OSError) as error:
        raise RuntimeError(
            "Native application components could not load. On Windows, check the Microsoft Visual C++ 2015-2022 x64 runtime; then rerun install.cmd. Details: "
            + str(error)
        ) from error
    if sys.platform == "win32":
        dotnet = ROOT / ".runtime/dotnet/dotnet.exe"
        result = subprocess.run(
            [str(dotnet), "--list-runtimes"], capture_output=True, text=True, check=True
        )
        if "Microsoft.NETCore.App 8.0." not in result.stdout:
            raise RuntimeError("The local .NET 8 runtime is missing; rerun install.cmd.")
    print(
        "Hardware drivers, Cometa .NET Framework and device licenses are separate prerequisites; see drivers/README.md."
    )
    print(json.dumps(dict(native_imports="passed", hardware="not_connected")))


if __name__ == "__main__":
    main()
