"""Tests for rey_analyzer.file_handler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rey_analyzer.error_utils import FileMovementError
from rey_analyzer.file_handler import (
    discover_inbox_files,
    move_to_failed,
    move_to_processing,
    move_to_success,
)


def _make_source(tmp_path: Path) -> SimpleNamespace:
    """Build a source config with all paths under tmp_path."""
    paths = SimpleNamespace(
        inbox_path      = str(tmp_path / "inbox"),
        processing_path = str(tmp_path / "processing"),
        success_path    = str(tmp_path / "success"),
        failed_path     = str(tmp_path / "failed"),
    )
    return SimpleNamespace(name="test", file_pattern="*.jsonl", paths=paths)


def test_discover_inbox_files_returns_sorted(tmp_path: Path) -> None:
    """discover_inbox_files returns files sorted by name."""
    src = _make_source(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "b.jsonl").write_text("b")
    (inbox / "a.jsonl").write_text("a")
    files = discover_inbox_files(src)
    assert [f.name for f in files] == ["a.jsonl", "b.jsonl"]


def test_discover_inbox_files_creates_inbox(tmp_path: Path) -> None:
    """discover_inbox_files creates the inbox directory if absent."""
    src = _make_source(tmp_path)
    files = discover_inbox_files(src)
    assert (tmp_path / "inbox").exists()
    assert files == []


def test_discover_inbox_files_filters_by_pattern(tmp_path: Path) -> None:
    """Only files matching file_pattern are returned."""
    src = _make_source(tmp_path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "a.jsonl").write_text("x")
    (inbox / "b.txt").write_text("x")
    files = discover_inbox_files(src)
    assert all(f.suffix == ".jsonl" for f in files)


def test_move_to_processing_moves_file(tmp_path: Path) -> None:
    """move_to_processing moves the file and returns the new path."""
    src  = _make_source(tmp_path)
    f    = tmp_path / "inbox" / "run.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text("data")
    dest = move_to_processing(f, src)
    assert dest.exists()
    assert dest.parent.name == "processing"
    assert not f.exists()


def test_move_to_success_moves_file(tmp_path: Path) -> None:
    """move_to_success moves the file to success_path."""
    src  = _make_source(tmp_path)
    proc = tmp_path / "processing" / "run.jsonl"
    proc.parent.mkdir(parents=True)
    proc.write_text("data")
    dest = move_to_success(proc, src)
    assert dest.parent.name == "success"
    assert not proc.exists()


def test_move_to_failed_moves_file(tmp_path: Path) -> None:
    """move_to_failed moves the file to failed_path."""
    src  = _make_source(tmp_path)
    proc = tmp_path / "processing" / "run.jsonl"
    proc.parent.mkdir(parents=True)
    proc.write_text("data")
    dest = move_to_failed(proc, src)
    assert dest.parent.name == "failed"
    assert not proc.exists()


def test_move_raises_file_movement_error_on_os_error(tmp_path: Path) -> None:
    """FileMovementError is raised when the underlying move fails."""
    src = _make_source(tmp_path)
    f   = tmp_path / "inbox" / "run.jsonl"
    f.parent.mkdir(parents=True)
    f.write_text("data")
    with patch("rey_analyzer.file_handler.move_file", side_effect=OSError("disk full")):
        with pytest.raises(FileMovementError):
            move_to_processing(f, src)
