#!/usr/bin/env python3
"""Get the current project version from the VERSION file."""

import sys
from pathlib import Path


def get_version() -> str:
    """Read and return the version from the VERSION file."""
    # Try package-level VERSION first, then project root
    package_version = Path(__file__).parent.parent / "ltx2_dataset_builder" / "VERSION"
    root_version = Path(__file__).parent.parent / "VERSION"

    if package_version.exists():
        return package_version.read_text().strip()
    if root_version.exists():
        return root_version.read_text().strip()
    return "0.1.0"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--json":
        import json
        print(json.dumps({"version": get_version()}))
    else:
        print(get_version())
