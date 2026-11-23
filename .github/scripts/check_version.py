"""Refuse a release version that is not newer than the existing tags.

Usage: check_version.py NEW_VERSION [TAG ...]
Exits 1, with a message, when NEW_VERSION is not higher than every tag.
With no tags on the command line the tags are read from ``git tag``.
"""

from __future__ import annotations

import re
import subprocess
import sys

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")


def parse(version: str) -> tuple[int, int, int, int, str] | None:
    """Sort key: a final release is newer than its own pre-releases."""
    match = _VERSION.match(version.strip())
    if match is None:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def newest(tags: list[str]) -> str | None:
    """The highest version among ``tags`` (others are ignored)."""
    valid = [tag for tag in tags if parse(tag) is not None]
    return max(valid, key=lambda tag: parse(tag)) if valid else None  # type: ignore[arg-type,return-value]


def check(new: str, tags: list[str]) -> str | None:
    """Return an error message, or None when ``new`` is newer than all tags."""
    new_key = parse(new)
    if new_key is None:
        return f"'{new}' is not a version like 1.2.3 or 1.2.3-beta1"
    latest = newest(tags)
    if latest is not None and new_key <= parse(latest):  # type: ignore[operator]
        return f"Version {new} must be higher than the latest release {latest}"
    return None


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    tags = argv[2:]
    if not tags:
        tags = subprocess.run(
            ["git", "tag", "--list", "v*"], capture_output=True, text=True, check=True
        ).stdout.split()
    error = check(argv[1], tags)
    if error:
        print(f"::error::{error}")
        return 1
    print(f"Version {argv[1]} is newer than {newest(tags) or 'any existing tag'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
