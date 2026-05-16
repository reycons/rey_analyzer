"""
Result artifact writing for rey_analyzer.

Wraps LocalArtifactStore from rey_lib to write analysis output artifacts
under results_path/<run_id>/. All artifact writing is delegated to rey_lib
— this module owns only the configuration of the store and the call
coordination after a successful analysis.

Public API
----------
build_artifact_store    Factory: build a LocalArtifactStore from ctx.
write_result            Write result artifacts for a completed analysis.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rey_lib.llm.artifacts import LocalArtifactStore
from rey_lib.llm.analysis import AnalysisResult
from rey_lib.logs.log_utils import get_logger

from rey_analyzer.requests import AnalysisRequest

__all__ = ["build_artifact_store", "write_result"]

_logger = get_logger(__name__)


def build_artifact_store(ctx: Any) -> LocalArtifactStore:
    """
    Build a LocalArtifactStore from the application context.

    Parameters
    ----------
    ctx : Any
        Application context Namespace. Must have .app.artifacts_path.

    Returns
    -------
    LocalArtifactStore
        Configured store rooted at ctx.app.artifacts_path.
    """
    artifacts_path = Path(ctx.app.artifacts_path).expanduser().resolve()
    artifacts_path.mkdir(parents=True, exist_ok=True)
    return LocalArtifactStore(base_dir=artifacts_path)


def write_result(
    request:        AnalysisRequest,
    result:         AnalysisResult,
    source_cfg:     Any,
) -> Path:
    """
    Write result artifacts to results_path/<run_id>/.

    Writes result.json containing the structured LLM output and
    execution metadata. Additional artifacts (raw response, validation
    errors) are written by rey_lib internally via the artifact_store
    passed to Analyzer.

    Parameters
    ----------
    request : AnalysisRequest
        The request that produced this result.
    result : AnalysisResult
        The AnalysisResult returned by Analyzer.analyze().
    source_cfg : Any
        Data source config Namespace. Must have .paths.results_path.

    Returns
    -------
    Path
        Path to the result directory written for this run.
    """
    results_root = Path(source_cfg.paths.results_path).expanduser().resolve()
    run_dir      = results_root / request.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "request_id":      request.request_id,
        "run_id":          request.run_id,
        "source_name":     request.source_name,
        "analysis_name":   request.analysis_name,
        "input_file":      str(request.file_path),
        "input_hash":      request.input_hash,
        "contract_path":   str(request.contract_path),
        "contract_hash":   request.contract_hash,
        "schema_hash":     request.schema_hash,
        "idempotency_mode": request.idempotency_mode,
        "status":          result.status,
        "data":            result.data,
        "errors":          result.errors,
    }

    result_file = run_dir / "result.json"
    result_file.write_text(json.dumps(record, default=str, indent=2), encoding="utf-8")

    _logger.info(
        "result written: run_id=%s status=%s path=%s",
        request.run_id, result.status, run_dir,
    )
    return run_dir
