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

from pathlib import Path
from typing import Any

from rey_lib.files.file_utils import write_file
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
    return LocalArtifactStore(base_dir=artifacts_path)


def write_result(
    request:        AnalysisRequest,
    result:         AnalysisResult,
    source_cfg:     Any,
    analysis_cfg:   Any = None,
    ctx:            Any = None,
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
        "raw_text":        getattr(result, "raw_text", None),
        "errors":          result.errors,
    }

    result_file = run_dir / "result.json"
    _state = {"state_ctx": ctx, "app": "rey_analyzer", "pipeline": getattr(ctx, "pipeline_name", None) if ctx else None, "reason": "analyzed"}
    write_file(result_file, record, file_type="JSON", **_state)

    # The analysis result JSON is a run-created output; record it as an artifact on
    # the append-only run log (SGC_Rey_Log_Writer_Run_View_Groups) when a run context
    # is present. Emission is fail-safe and never blocks result writing.
    if ctx is not None:
        log_artifact_reference(
            ctx, str(result_file), role="analysis_result", event="written",
        )

    _logger.info(
        "result written: run_id=%s status=%s path=%s",
        request.run_id, result.status, run_dir,
    )

    if result.status == "success" and analysis_cfg is not None:
        output_cfg = getattr(analysis_cfg, "output", None)
        if output_cfg is not None and getattr(output_cfg, "write_raw", False):
            _write_raw_output(request, result, source_cfg, ctx=ctx)

    return run_dir


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
        )

    _logger.info("raw output written: %s", raw_file)


def _raw_output_stem(file_path: Path) -> str:
    """Return output stem, removing only the compound .profile.json suffix."""
    name = file_path.name
    if name.endswith(".profile.json"):
        return name.removesuffix(".profile.json")
    return file_path.stem
