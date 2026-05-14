"""Tests for rey_analyzer.runner."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from rey_analyzer.error_utils import SourceError
from rey_analyzer.runner import _build_data_source, _max_files


def test_build_data_source_jsonl_returns_text_source(tmp_path: Path) -> None:
    """jsonl_file input_type returns a TextDataSource."""
    from rey_lib.llm.datasource import TextDataSource

    f = tmp_path / "test.jsonl"
    f.write_text('{"level":"ERROR"}\n', encoding="utf-8")
    src = _build_data_source("jsonl_file", f)
    assert isinstance(src, TextDataSource)


def test_build_data_source_csv_returns_csv_source(tmp_path: Path) -> None:
    """csv_file input_type returns a CSVDataSource."""
    from rey_lib.llm.datasource import CSVDataSource

    f = tmp_path / "test.csv"
    f.write_text("col1,col2\na,b\n", encoding="utf-8")
    src = _build_data_source("csv_file", f)
    assert isinstance(src, CSVDataSource)


def test_build_data_source_unknown_type_raises_source_error(tmp_path: Path) -> None:
    """Unknown input_type raises SourceError."""
    f = tmp_path / "test.xyz"
    f.write_text("data")
    with pytest.raises(SourceError, match="Unsupported input_type"):
        _build_data_source("xyz_file", f)


def test_build_data_source_text_types(tmp_path: Path) -> None:
    """All text-like input types return TextDataSource."""
    from rey_lib.llm.datasource import TextDataSource

    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    for input_type in ("text_file", "jsonl_file", "json_file", "markdown_file"):
        src = _build_data_source(input_type, f)
        assert isinstance(src, TextDataSource), input_type


def test_max_files_uses_minimum(sample_ctx: SimpleNamespace) -> None:
    """_max_files returns the lower of runtime and source caps."""
    sample_ctx.runtime.max_files_per_run = 50
    source_cfg = SimpleNamespace(max_files_per_run=10)
    assert _max_files(sample_ctx, source_cfg) == 10


def test_max_files_defaults_to_runtime(sample_ctx: SimpleNamespace) -> None:
    """_max_files falls back to runtime cap when source has no override."""
    sample_ctx.runtime.max_files_per_run = 25
    source_cfg = SimpleNamespace()
    assert _max_files(sample_ctx, source_cfg) == 25


def test_run_source_empty_inbox(
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
) -> None:
    """run_source returns (0, 0, 0) when the inbox is empty."""
    from rey_analyzer.runner import run_source

    success, failed, pending = run_source(
        sample_ctx, sample_source_cfg, sample_analysis_cfg
    )
    assert (success, failed, pending) == (0, 0, 0)


def test_run_analysis_moves_to_failed_on_exception(
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """run_analysis returns 'failed' and moves file to failed_path on error."""
    from rey_analyzer.runner import run_analysis

    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    file_in_inbox = inbox / sample_jsonl_file.name
    file_in_inbox.write_text(sample_jsonl_file.read_text())

    with patch("rey_analyzer.runner.build_request", side_effect=Exception("boom")):
        status = run_analysis(
            sample_ctx, sample_source_cfg, sample_analysis_cfg, file_in_inbox
        )

    assert status == "failed"
