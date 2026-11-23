"""The version guard used by the Create Release workflow."""

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).parent.parent / ".github" / "scripts" / "check_version.py"
_spec = importlib.util.spec_from_file_location("check_version", _PATH)
check_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_version)

TAGS = ["v0.1.0", "v0.1.3", "v0.3.0", "v0.3.1"]


def test_a_higher_version_is_accepted():
    assert check_version.check("0.4.0", TAGS) is None
    assert check_version.check("v0.3.2", TAGS) is None
    assert check_version.check("1.0.0", TAGS) is None


@pytest.mark.parametrize("version", ["0.3.1", "0.3.0", "0.2.9", "v0.1.3"])
def test_the_same_or_a_lower_version_is_refused(version):
    assert "must be higher" in check_version.check(version, TAGS)


def test_versions_compare_as_numbers_not_text():
    # 0.10.0 is newer than 0.9.0, although "0.10" sorts before "0.9" as text.
    assert check_version.check("0.10.0", ["v0.9.0"]) is None
    assert check_version.check("0.9.0", ["v0.10.0"]) is not None


def test_a_final_release_follows_its_prerelease():
    assert check_version.check("0.5.0", ["v0.5.0-beta1"]) is None
    assert check_version.check("0.5.0-beta2", ["v0.5.0-beta1"]) is None
    assert check_version.check("0.5.0-beta1", ["v0.5.0"]) is not None


def test_the_first_release_is_accepted_without_tags():
    assert check_version.check("0.1.0", []) is None


def test_other_tags_are_ignored_and_nonsense_is_refused():
    assert check_version.check("0.4.0", ["latest", "v0.3.1"]) is None
    assert "not a version" in check_version.check("banana", TAGS)
