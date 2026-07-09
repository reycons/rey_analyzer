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

import re
from pathlib import Path
from typing import Any

from rey_lib.files.file_utils import run_artifact_path, write_file
from rey_lib.llm.artifacts import LocalArtifactStore
from rey_lib.llm.analysis import AnalysisResult
from rey_lib.logs import get_logger, log_artifact_reference

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
    # Pass the run context so each written LLM stage-result JSON is recorded as a
    # files/artifacts run-log artifact (SGC_Rey_Log_Writer_Run_View_Groups).
    return LocalArtifactStore(base_dir=artifacts_path, run_ctx=ctx)


def write_result(
    request:        AnalysisRequest,
    result:         AnalysisResult,
    source_cfg:     Any,
    analysis_cfg:   Any = None,
    ctx:            Any = None,
) -> Path:
    """
    Write result artifacts directly under results_path.

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
    results_root.mkdir(parents=True, exist_ok=True)

    run_timestamp = str(getattr(ctx, "run_timestamp", "") or "").strip() or "unknown_time"
    step_name = _artifact_step_name(request)

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
        "raw_text":        getattr(result, "raw_text", None),
        "errors":          result.errors,
    }

    result_file = run_artifact_path(results_root, step_name, run_timestamp, "result.json")
    _state = {"state_ctx": ctx, "app": "rey_analyzer", "pipeline": getattr(ctx, "pipeline_name", None) if ctx else None, "reason": "analyzed"}
    write_file(result_file, record, file_type="JSON", **_state)

    context_file = run_artifact_path(results_root, step_name, run_timestamp, "context.json")
    write_file(context_file, {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "source_name": request.source_name,
        "analysis_name": request.analysis_name,
        "input_file": str(request.file_path),
        "input_hash": request.input_hash,
        "contract_path": str(request.contract_path),
        "contract_hash": request.contract_hash,
        "schema_hash": request.schema_hash,
        "idempotency_mode": request.idempotency_mode,
        "status": result.status,
        "errors": result.errors,
    }, file_type="JSON", **_state)

    # The analysis result JSON is a run-created output; record it as an artifact on
    # the append-only run log (SGC_Rey_Log_Writer_Run_View_Groups) when a run context
    # is present. Emission is fail-safe and never blocks result writing.
    if ctx is not None:
        log_artifact_reference(
            ctx, str(result_file), role="analysis_result", event="written",
            producer="analyzer", artifact_type="analysis_result",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )
        log_artifact_reference(
            ctx, str(context_file), role="analysis_context", event="written",
            producer="analyzer", artifact_type="analysis_context",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )

    _logger.info(
        "result written: run_id=%s status=%s result=%s context=%s",
        request.run_id, result.status, result_file, context_file,
    )

    if result.status == "success" and analysis_cfg is not None:
        output_cfg = getattr(analysis_cfg, "output", None)
        if output_cfg is not None and getattr(output_cfg, "write_raw", False):
            _write_raw_output(request, result, source_cfg, ctx=ctx)

    return results_root


def _artifact_step_name(request: AnalysisRequest) -> str:
    """Return a filesystem-safe step name for artifact filenames."""
    raw = str(getattr(request, "analysis_name", "") or getattr(request, "source_name", "") or "").strip()
    if not raw:
        return "unknown_step"

    # Replace separators and other filesystem-hostile characters, then compact runs.
    safe = raw.replace("/", "_").replace("\\", "_")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", safe)
    safe = safe.strip(" ._")
    return safe or "unknown_step"


def _write_raw_output(
    request:    AnalysisRequest,
    result:     AnalysisResult,
    source_cfg: Any,
    ctx:        Any = None,
) -> None:
    """Write raw LLM output text to raw_output_path for pipeline chaining."""
    raw_dir_str = getattr(getattr(source_cfg, "paths", None), "raw_output_path", None)
    if not raw_dir_str:
        _logger.warning("write_raw is true but raw_output_path is not configured.")
        return

    raw_dir = Path(raw_dir_str).expanduser().resolve()
    raw_dir.mkdir(parents=True, exist_ok=True)

    stem = _raw_output_stem(request.file_path)
    ext  = getattr(source_cfg, "raw_output_extension", ".yaml")
    raw_file = raw_dir / f"{stem}{ext}"

    raw_text = result.raw_text or ""
    write_file(raw_file, raw_text, file_type="TEXT", state_ctx=ctx, app="rey_analyzer", pipeline=getattr(ctx, "pipeline_name", None) if ctx else None, reason="raw_output")

    # Raw LLM output is a run-created artifact used for pipeline chaining.
    if ctx is not None:
        log_artifact_reference(
            ctx, str(raw_file), role="raw_output", event="written",
            producer="llm", artifact_type="llm_result",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )

    _logger.info("raw output written: %s", raw_file)


def _raw_output_stem(file_path: Path) -> str:
    """Return output stem, removing only the compound .profile.json suffix."""
    name = file_path.name
    if name.endswith(".profile.json"):
        return name.removesuffix(".profile.json")
    return file_path.stem
