"""Tests for result artifact writing."""

from __future__ import annotations

from pathlib import Path

from rey_analyzer.results import _raw_output_stem


def test_raw_output_stem_preserves_dots_in_yaml_filename() -> None:
    """Only the real suffix is removed for normal loader YAML files."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.yaml")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"


def test_raw_output_stem_removes_profile_json_suffix() -> None:
    """Profile inputs remove the compound suffix but keep dots in the stem."""
    path = Path("ExtracoBanks_N.A.2026-03-31_Position.profile.json")

    assert _raw_output_stem(path) == "ExtracoBanks_N.A.2026-03-31_Position"
