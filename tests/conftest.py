"""Shared fixtures for rey_analyzer tests."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

logging.getLogger("rey_lib").setLevel(logging.WARNING)
logging.getLogger("rey_analyzer").setLevel(logging.WARNING)

_PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture()
def sample_jsonl_file(tmp_path: Path) -> Path:
    """A small JSONL file with mixed log levels."""
    content = (
        '{"level": "INFO",  "message": "Stage started"}\n'
        '{"level": "ERROR", "message": "Failed to load file.csv"}\n'
        '{"level": "WARNING", "message": "Row 5 truncated"}\n'
        '{"level": "ERROR", "message": "DB insert failed"}\n'
    )
    f = tmp_path / "test_run.jsonl"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture()
def sample_source_cfg(tmp_path: Path) -> SimpleNamespace:
    """Minimal data source config Namespace."""
    paths = SimpleNamespace(
        inbox_path      = str(tmp_path / "inbox"),
        processing_path = str(tmp_path / "processing"),
        success_path    = str(tmp_path / "success"),
        failed_path     = str(tmp_path / "failed"),
        results_path    = str(tmp_path / "results"),
    )
    return SimpleNamespace(
        name                = "test_source",
        enabled             = True,
        input_type          = "jsonl_file",
        file_pattern        = "*.jsonl",
        analysis_config     = "etl_log_failure",
        max_files_per_run   = 10,
        paths               = paths,
    )


@pytest.fixture()
def sample_analysis_cfg() -> SimpleNamespace:
    """Minimal analysis config Namespace."""
    return SimpleNamespace(
        name              = "etl_log_failure",
        contract          = "contracts/etl_log_failure/v01.md",
        llm_execution_profile = "primary",
        idempotency_mode  = "reuse_success",
        requires_approval = False,
        schema            = None,
    )


@pytest.fixture()
def sample_ctx(tmp_path: Path) -> SimpleNamespace:
    """Minimal application context Namespace."""
    app = SimpleNamespace(
        records_path   = str(tmp_path / "records"),
        artifacts_path = str(tmp_path / "artifacts"),
    )
    runtime = SimpleNamespace(
        max_files_per_run = 25,
        stop_on_error     = False,
    )
    return SimpleNamespace(
        app             = app,
        runtime         = runtime,
        data_sources    = [],
        analysis_configs = [],
        llm_profiles    = [],
        source_name     = "",
        analysis_name   = "",
        current_file    = "",
    )


# ---------------------------------------------------------------------------
# Run logging
# ---------------------------------------------------------------------------

def make_run_log(
    tmp_path,
    *,
    app: str = "rey_analyzer",
    run_id: str = "00000000-0000-4000-8000-000000000001",
    run_timestamp: str = "20260822_000000",
    path: str | None = None,
):
    """Build a RunLog writing into ``tmp_path``.

    Run logging is owned by ``RunLog``; a test that writes records takes one
    rather than handing logging a context to read fields off.
    """
    from rey_lib.logs.run_log import RunLog

    return RunLog(
        app=app,
        run_id=run_id,
        run_timestamp=run_timestamp,
        log_dir=None if path else str(tmp_path),
        path=path,
    )


@pytest.fixture()
def run_log(tmp_path):
    """The run log a test writes records through."""
    return make_run_log(tmp_path)
