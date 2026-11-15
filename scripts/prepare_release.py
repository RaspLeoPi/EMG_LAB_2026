"""Fetch pinned Windows runtimes and record verified release input provenance."""

import argparse
from pathlib import Path

try:
    from .release_common import write_json
    from .windows_runtime import fetch_payload, runtime_specs
except ImportError:
    from release_common import write_json
    from windows_runtime import fetch_payload, runtime_specs

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {}
    for key, spec in runtime_specs(ROOT).items():
        _, artifacts[key] = fetch_payload(spec, destination)
    path = destination / "release-artifacts.lock.json"
    write_json(path, dict(format_version=1, artifacts=artifacts))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/release-inputs")
    args = parser.parse_args()
    print(prepare(args.output))


if __name__ == "__main__":
    main()
