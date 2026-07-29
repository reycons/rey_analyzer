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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rey_lib.files.file_utils import file_sha256, run_artifact_path, write_file
from rey_lib.llm.artifacts import LocalArtifactStore
from rey_lib.llm.analysis import AnalysisResult
from rey_lib.logs import get_logger, log_artifact_reference

from rey_analyzer.requests import AnalysisRequest

__all__ = ["AnalyzerResultArtifacts", "build_artifact_store", "write_result"]

_logger = get_logger(__name__)


@dataclass(frozen=True)
class AnalyzerResultArtifacts:
    """Explicit artifacts produced by one governed Analyzer execution."""

    result_path: Path
    result_sha256: str
    context_path: Path
    context_sha256: str
    candidate_path: Path | None
    candidate_sha256: str | None


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
    *,
    workflow_name: str = "",
    provider: str = "",
    model: str = "",
) -> AnalyzerResultArtifacts:
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
    AnalyzerResultArtifacts
        Exact result, context, and optional candidate artifacts.
    """
    results_root = Path(source_cfg.paths.results_path).expanduser().resolve()
    results_root.mkdir(parents=True, exist_ok=True)

    run_timestamp = str(getattr(ctx, "run_timestamp", "") or "").strip() or "unknown_time"
    artifact_name = _result_artifact_name(request)

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

    result_file = run_artifact_path(
        results_root,
        artifact_name,
        run_timestamp,
        "result.json",
    )
    _state = {"state_ctx": ctx, "app": "rey_analyzer", "pipeline": getattr(ctx, "pipeline_name", None) if ctx else None, "reason": "analyzed"}
    write_file(result_file, record, file_type="JSON", **_state)

    candidate_file: Path | None = None
    if result.status == "success" and analysis_cfg is not None:
        output_cfg = getattr(analysis_cfg, "output", None)
        if output_cfg is not None and getattr(output_cfg, "write_raw", False):
            candidate_file = _write_raw_output(
                request,
                result,
                source_cfg,
                ctx=ctx,
            )

    context_file = run_artifact_path(
        results_root,
        artifact_name,
        run_timestamp,
        "context.json",
    )
    context = {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "workflow_name": workflow_name,
        "source_name": request.source_name,
        "analysis_name": request.analysis_name,
        "model_profile": request.llm_profile_name,
        "provider": provider,
        "model": model,
        "source_artifact_path": str(request.file_path),
        "source_artifact_sha256": request.input_hash,
        "contract_path": str(request.contract_path),
        "contract_hash": request.contract_hash,
        "schema_hash": request.schema_hash,
        "idempotency_mode": request.idempotency_mode,
        "result_artifact_path": str(result_file),
        "result_artifact_sha256": file_sha256(result_file),
        "candidate_artifact_path": (
            str(candidate_file) if candidate_file is not None else None
        ),
        "candidate_artifact_sha256": (
            file_sha256(candidate_file) if candidate_file is not None else None
        ),
        "status": result.status,
        "errors": result.errors,
    }
    write_file(context_file, context, file_type="JSON", **_state)

    # The analysis result JSON is a run-created output; record it as an artifact on
    # the append-only run log (SGC_Rey_Log_Writer_Run_View_Groups) when a run context
    # is present. Emission is fail-safe and never blocks result writing.
    if ctx is not None:
        log_artifact_reference(
            ctx, str(result_file), role="analysis_result", event="written",
            artifact_group="analysis_results", producing_app="rey_analyzer",
            producing_step=_artifact_step_name(request),
            producer="analyzer", artifact_type="analysis_result",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )
        log_artifact_reference(
            ctx, str(context_file), role="analysis_context", event="written",
            artifact_group="analysis_context", producing_app="rey_analyzer",
            producing_step=_artifact_step_name(request),
            producer="analyzer", artifact_type="analysis_context",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )

    _logger.info(
        "result written: run_id=%s status=%s result=%s context=%s",
        request.run_id, result.status, result_file, context_file,
    )

    return AnalyzerResultArtifacts(
        result_path=result_file,
        result_sha256=file_sha256(result_file),
        context_path=context_file,
        context_sha256=file_sha256(context_file),
        candidate_path=candidate_file,
        candidate_sha256=(
            file_sha256(candidate_file) if candidate_file is not None else None
        ),
    )


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


def _result_artifact_name(request: AnalysisRequest) -> str:
    """Return a stable per-request name for result and context artifacts."""
    request_id = str(getattr(request, "request_id", "") or "").strip()
    safe_request_id = re.sub(r"[^A-Za-z0-9._-]+", "_", request_id)
    safe_request_id = safe_request_id.strip(" ._")
    if not safe_request_id:
        raise ValueError("Analyzer result artifacts require a request_id.")
    return f"{_artifact_step_name(request)}.{safe_request_id}"


def _write_raw_output(
    request:    AnalysisRequest,
    result:     AnalysisResult,
    source_cfg: Any,
    ctx:        Any = None,
) -> Path | None:
    """Write raw LLM output text to raw_output_path for pipeline chaining."""
    raw_dir_str = getattr(getattr(source_cfg, "paths", None), "raw_output_path", None)
    if not raw_dir_str:
        _logger.warning("write_raw is true but raw_output_path is not configured.")
        return None

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
            artifact_group="analysis_results", producing_app="rey_analyzer",
            producing_step=_artifact_step_name(request),
            producer="llm", artifact_type="llm_result",
            source_path=str(getattr(request, "file_path", "") or ""),
            viewer_type="file", safe_to_preview=True,
        )

    _logger.info("raw output written: %s", raw_file)
    return raw_file


def _raw_output_stem(file_path: Path) -> str:
    """Return output stem, removing only the compound .profile.json suffix."""
    name = file_path.name
    if name.endswith(".profile.json"):
        return name.removesuffix(".profile.json")
    return file_path.stem
