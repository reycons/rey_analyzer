"""
File movement and discovery for the rey_analyzer pipeline.

All file operations use configured paths only. No hardcoded folders. Files
move through stages in one direction: inbox → processing → success/failed.
Files pending approval remain in processing_path until resolved.

All functions delegate to rey_lib.files.file_utils for the actual move
operations. FileMovementError is raised on any OS-level failure.

Public API
----------
discover_inbox_files    Glob inbox_path for files matching the source pattern.
move_to_processing      Move a file from inbox to processing (claim ownership).
move_to_success         Move a processed file to success_path.
move_to_failed          Move a failed file to failed_path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rey_lib.files.file_utils import input_files, move_file
from rey_lib.logs.log_utils import get_logger

from rey_analyzer.error_utils import FileMovementError

__all__ = [
    "discover_inbox_files",
    "move_to_processing",
    "move_to_success",
    "move_to_failed",
]

_logger = get_logger(__name__)


def discover_inbox_files(source_cfg: Any) -> list[Path]:
    """
    Return all files in inbox_path matching the source file_pattern.

    Files are returned sorted for deterministic processing order. The
    inbox_path is created if it does not exist so the app starts cleanly
    on first run.

    Parameters
    ----------
    source_cfg : Any
        Data source config Namespace. Must have .paths.inbox_path and
        .file_pattern.

    Returns
    -------
    list[Path]
        Matching files sorted by name. Empty list when inbox is empty.
    """
    inbox = Path(source_cfg.paths.inbox_path).expanduser().resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    pattern = getattr(source_cfg, "file_pattern", "*")
    return sorted(input_files(inbox, pattern))


def move_to_processing(file_path: Path, source_cfg: Any) -> Path:
    """
    Move a file from inbox_path to processing_path.

    Files become owned by rey_analyzer only after this move. Files must
    never be analyzed directly from inbox_path.

    Parameters
    ----------
    file_path : Path
        Absolute path of the file in inbox_path.
    source_cfg : Any
        Data source config Namespace. Must have .paths.processing_path.

    Returns
    -------
    Path
        New absolute path of the file in processing_path.

    Raises
    ------
    FileMovementError
        If the move fails for any OS-level reason.
    """
    dest_dir = Path(source_cfg.paths.processing_path).expanduser().resolve()
    return _move(file_path, dest_dir, "processing")


def move_to_success(file_path: Path, source_cfg: Any) -> Path:
    """
    Move a processed file from processing_path to success_path.

    Parameters
    ----------
    file_path : Path
        Absolute path of the file in processing_path.
    source_cfg : Any
        Data source config Namespace. Must have .paths.success_path.

    Returns
    -------
    Path
        New absolute path of the file in success_path.

    Raises
    ------
    FileMovementError
        If the move fails for any OS-level reason.
    """
    dest_dir = Path(source_cfg.paths.success_path).expanduser().resolve()
    return _move(file_path, dest_dir, "success")


def move_to_failed(file_path: Path, source_cfg: Any) -> Path:
    """
    Move a file from processing_path to failed_path.

    Parameters
    ----------
    file_path : Path
        Absolute path of the file in processing_path.
    source_cfg : Any
        Data source config Namespace. Must have .paths.failed_path.

    Returns
    -------
    Path
        New absolute path of the file in failed_path.

    Raises
    ------
    FileMovementError
        If the move fails for any OS-level reason.
    """
    dest_dir = Path(source_cfg.paths.failed_path).expanduser().resolve()
    return _move(file_path, dest_dir, "failed")


# ---------------------------------------------------------------------------
# Private
# ---------------------------------------------------------------------------

def _move(file_path: Path, dest_dir: Path, stage: str) -> Path:
    """Move file_path into dest_dir, creating dest_dir if needed."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_path.name
    try:
        move_file(file_path, dest_dir)
        _logger.debug("moved %s → %s", file_path.name, stage)
        return dest
    except Exception as exc:
        raise FileMovementError(
            f"Failed to move {file_path.name} to {stage}: {exc}"
        ) from exc
