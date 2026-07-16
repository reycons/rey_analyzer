"""Tests for rey_analyzer.runner."""

from __future__ import annotations

import json
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


def test_run_source_logs_input_discovery_count(
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """run_source records discovered analyzer input files through shared helpers."""
    from rey_analyzer.runner import run_source

    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")
    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    file_in_inbox = inbox / sample_jsonl_file.name
    file_in_inbox.write_text(sample_jsonl_file.read_text(encoding="utf-8"), encoding="utf-8")

    with patch("rey_analyzer.runner.run_analysis", return_value="success"):
        success, failed, pending = run_source(
            sample_ctx, sample_source_cfg, sample_analysis_cfg
        )

    assert (success, failed, pending) == (1, 0, 0)
    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    count = next(r for r in records if r["record_type"] == "ROW_COUNT")
    discovered = next(r for r in records if r["record_type"] == "INPUT_DISCOVERED")
    assert count["count_name"] == "analysis_input_files_discovered"
    assert count["count"] == 1
    assert discovered["path"] == str(file_in_inbox)
    assert discovered["source_config"] == sample_source_cfg.name


def test_consecutive_analyses_are_siblings_under_app(
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
    sample_analysis_cfg: SimpleNamespace,
    sample_jsonl_file: Path,
    tmp_path: Path,
) -> None:
    """Two files analyzed in one source run are siblings: their records share one
    parent (the app anchor), rather than the second file chaining under the first
    file's final record (SGC_Rey_Log_Hierarchy_Shared_Run_State_Correction)."""
    from rey_analyzer.runner import run_source
    from rey_lib.logs import set_nest_level
    from rey_lib.logs.log_utils import log_run_record

    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")

    inbox = Path(sample_source_cfg.paths.inbox_path)
    inbox.mkdir(parents=True, exist_ok=True)
    for name in ("file_a.jsonl", "file_b.jsonl"):
        (inbox / name).write_text(
            sample_jsonl_file.read_text(encoding="utf-8"), encoding="utf-8"
        )

    # The app boundary (run_app_operation) establishes app level before run_source.
    set_nest_level(sample_ctx, "app")

    def fake_run_analysis(ctx, source_cfg, analysis_cfg, file_path):
        # Each analysis writes at the level run_source established once for the loop.
        log_run_record(ctx, "INPUT_FILE_REFERENCE", display_name=file_path.name)
        return "success"

    with patch("rey_analyzer.runner.run_analysis", side_effect=fake_run_analysis):
        run_source(sample_ctx, sample_source_cfg, sample_analysis_cfg)

    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    refs = [r for r in records if r["record_type"] == "INPUT_FILE_REFERENCE"]
    assert len(refs) == 2
    # Siblings: same parent and same analysis level.
    assert refs[0]["parent_record_id"] == refs[1]["parent_record_id"]
    assert refs[0]["nest_level"] == refs[1]["nest_level"]
    # The second file is not parented under the first file's record.
    assert refs[1]["parent_record_id"] != refs[0]["record_id"]


def test_run_all_returns_failed_count_on_source_exception(
    sample_ctx: SimpleNamespace,
    sample_source_cfg: SimpleNamespace,
) -> None:
    """run_all includes source-level failures in the returned counts."""
    from rey_analyzer.runner import run_all

    sample_source_cfg.analysis_config = "missing_config"
    sample_ctx.data_sources = [sample_source_cfg]

    success, failed, pending = run_all(sample_ctx)

    assert (success, failed, pending) == (0, 1, 0)


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
    object.__setattr__(sample_ctx, "run_log_path", str(tmp_path / "run.jsonl"))
    object.__setattr__(sample_ctx, "run_id", "r1")
    object.__setattr__(sample_ctx, "run_timestamp", "20260709_000000")

    with patch("rey_analyzer.runner.build_request", side_effect=Exception("boom")):
        status = run_analysis(
            sample_ctx, sample_source_cfg, sample_analysis_cfg, file_in_inbox
        )

    assert status == "failed"
    records = [
        json.loads(line)
        for line in Path(sample_ctx.run_log_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    input_ref = next(r for r in records if r["record_type"] == "INPUT_FILE_REFERENCE")
    validation = next(r for r in records if r["record_type"] == "VALIDATION_RESULT")
    assert input_ref["file_role"] == "analysis_input"
    assert input_ref["path"] == str(file_in_inbox)
    assert validation["validation_name"] == "analysis_result"
    assert validation["status"] == "failed"
