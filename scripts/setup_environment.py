"""Process-local setup settings; Windows installers connect directly to package hosts."""

import os
import sys


def installation_environment(environment=None, platform_name=None):
    result = dict(os.environ if environment is None else environment)
    if (sys.platform if platform_name is None else platform_name) == "win32":
        result = {key: value for key, value in result.items() if not key.lower().endswith("_proxy")}
        result.update(NO_PROXY="*", no_proxy="*", PIP_CONFIG_FILE="nul")
    return result


def application_environment(root, environment=None):
    from pathlib import Path

    result = dict(os.environ if environment is None else environment)
    dotnet = Path(root).resolve() / ".runtime/dotnet"
    if (dotnet / "dotnet.exe").is_file():
        result.update(
            DOTNET_ROOT=str(dotnet), DOTNET_ROOT_X64=str(dotnet), DOTNET_MULTILEVEL_LOOKUP="0"
        )
        result["PATH"] = str(dotnet) + os.pathsep + result.get("PATH", "")
    return result
