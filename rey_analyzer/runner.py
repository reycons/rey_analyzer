"""
Assembly-line orchestrator for rey_analyzer.

runner.py is the single module that connects all other modules. It owns
the per-file lifecycle: discover → claim → analyze → write → move. It
delegates every specialised concern to the appropriate module or rey_lib.

No LLM logic lives here. No file-format parsing lives here. No path
construction beyond what is required to wire config to rey_lib.

Public API
----------
run_all        Process all enabled data sources.
run_source     Process all inbox files for one named data source.
run_analysis   Process a single file through a single analysis config.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rey_lib.artifacts import artifact_config_from_ctx
from rey_lib.config.ctx import find_in_ctx
from rey_lib.config.env_reference import resolve_env_reference
from rey_lib.files.file_utils import (
    discover_inbox_files,
    move_to_failed,
    move_to_processing,
    move_to_success,
    read_text_file,
)
from rey_lib.llm.analysis import Analyzer
from rey_lib.llm.package import LlmPackageContract, LlmPackageInput, build_package
from rey_lib.errors.error_utils import build_safe_error_payload
from rey_lib.logs import (
    get_logger,
    log_error,
    log_input_discovered,
    log_input_file_reference,
    log_row_count,
    log_validation_result,
    next_nest_level,
    previous_nest_level,
    set_nest_level,
)
from rey_lib.llm.datasource import (
    CSVDataSource,
    DataSource,
    ExcelDataSource,
    TextDataSource,
)

from rey_analyzer.error_utils import (
    ConfigurationError,
    SourceError,
)
from rey_analyzer.preprocessor import build_incident_packet
from rey_analyzer.requests import AnalysisRequest, build_request
from rey_analyzer.evidence import emit_llm_evidence
from rey_analyzer.results import build_artifact_store, write_result

__all__ = [
    "build_payload",
    "run_all",
    "run_analysis",
    "run_source",
]

_logger = get_logger(__name__)

# Maps input_type config values to DataSource construction strategies.
# Text-like formats are all passed as raw text — the LLM reads them as-is.
_TEXT_INPUT_TYPES = frozenset({
    "text_file",
    "jsonl_file",
    "json_file",
    "markdown_file",
})


def run_all(ctx: Any, run_log) -> tuple[int, int, int]:
    """
    Process all enabled data sources defined in ctx.

    Iterates ctx.data_sources in declaration order. Disabled sources are
    skipped with a debug log. Failures on one source do not stop others
    unless ctx.runtime.stop_on_error is true.

    Parameters
    ----------
    ctx : Any
        Application context built by build_ctx().

    Returns
    -------
    tuple[int, int, int]
        Total counts of (success, failed, pending_approval) files.
    """
    sources = getattr(ctx, "data_sources", []) or []
    if not sources:
        _logger.warning("No data_sources configured — nothing to process.")
        return 0, 0, 0

    stop_on_error = bool(getattr(getattr(ctx, "runtime", None), "stop_on_error", False))
    total_success = total_failed = total_pending = 0

    for source_cfg in sources:
        if not getattr(source_cfg, "enabled", True):
            _logger.debug("source '%s' disabled — skipping.", source_cfg.name)
            continue

        try:
            analysis_cfg = _resolve_analysis_cfg(ctx, source_cfg.analysis_config)
            success, failed, pending = run_source(ctx, run_log, source_cfg, analysis_cfg)
            _logger.info(
                "source '%s' complete: success=%d failed=%d pending=%d",
                source_cfg.name, success, failed, pending,
            )
            total_success += success
            total_failed += failed
            total_pending += pending
        except Exception as exc:  # noqa: BLE001
            _logger.error("source '%s' error: %s", source_cfg.name, exc)
            total_failed += 1
            if stop_on_error:
                raise

    return total_success, total_failed, total_pending


def run_source(
    ctx:          Any, run_log,
    source_cfg:   Any,
    analysis_cfg: Any,
    *,
    workflow_name: str = "",
) -> tuple[int, int, int]:
    """
    Process all inbox files for one data source.

    Applies per-source max_files_per_run cap (lowest of source config and
    ctx.runtime.max_files_per_run). Files are processed in sorted order.

    Parameters
    ----------
    ctx : Any
        Application context.
    source_cfg : Any
        Data source config Namespace.
    analysis_cfg : Any
        Analysis config Namespace.

    Returns
    -------
    tuple[int, int, int]
        Counts of (success, failed, pending_approval) files.
    """
    max_files = _max_files(ctx, source_cfg)
    files     = discover_inbox_files(source_cfg)[:max_files]
    pattern = str(getattr(source_cfg, "file_pattern", "*") or "*")
    inbox = str(getattr(getattr(source_cfg, "paths", None), "inbox_path", "") or "")
    log_row_count(run_log,
        count_name="analysis_input_files_discovered",
        count=len(files),
        subject=source_cfg.name,
        input_type=getattr(source_cfg, "input_type", ""),
        pattern=pattern,
        source_path=inbox,
    )
    for discovered in files:
        log_input_discovered(run_log,
            input_name=source_cfg.name,
            path=str(discovered),
            pattern=pattern,
            source_config=source_cfg.name,
            exists=discovered.exists(),
            safe_to_preview=True,
            input_type=getattr(source_cfg, "input_type", ""),
        )

    if not files:
        if bool(getattr(source_cfg, "require_input", False)):
            log_validation_result(run_log,
                validation_name="analysis_input_required",
                status="failed",
                message=f"source '{source_cfg.name}' has no required input files",
                source_name=source_cfg.name,
                pattern=pattern,
                source_path=inbox,
            )
            raise SourceError(
                f"source '{source_cfg.name}': no input files matched "
                f"'{pattern}' in {inbox}. This step requires input produced by "
                "an upstream step. Confirm the upstream step (e.g. file_operator) "
                "ran successfully and that the inbox path and redact.yaml are correct."
            )
        _logger.info("source '%s': inbox is empty.", source_cfg.name)
        log_validation_result(run_log,
            validation_name="analysis_input_required",
            status="success",
            message=f"source '{source_cfg.name}' has no required input files",
            source_name=source_cfg.name,
            pattern=pattern,
            source_path=inbox,
        )
        return 0, 0, 0

    _logger.info("source '%s': %d file(s) to process.", source_cfg.name, len(files))

    success = failed = pending = 0

    set_nest_level(run_log, "next")
    for file_path in files:
        set_nest_level(run_log, "sibling")
        try:
            status = run_analysis(ctx, run_log,
                source_cfg,
                analysis_cfg,
                file_path,
                workflow_name=workflow_name,
            )
        finally:
            previous_nest_level(run_log)
        if status == "success":
            success += 1
        elif status == "pending_approval":
            pending += 1
        else:
            failed += 1

    return success, failed, pending


def run_analysis(
    ctx:          Any, run_log,
    source_cfg:   Any,
    analysis_cfg: Any,
    file_path:    Path,
    *,
    workflow_name: str = "",
) -> str:
    """
    Run the full analysis lifecycle for one file.

    Stages
    ------
    1. Build AnalysisRequest (hashes, identity).
    2. Move file from inbox to processing (claim ownership).
    3. Resolve LLM profile.
    4. Build Analyzer and DataSource.
    5. Call Analyzer.analyze().
    6. Write result artifacts.
    7. Move file to success, failed, or leave in processing (pending approval).

    Parameters
    ----------
    ctx : Any
        Application context.
    source_cfg : Any
        Data source config Namespace.
    analysis_cfg : Any
        Analysis config Namespace.
    file_path : Path
        Absolute path of the file in inbox_path.

    Returns
    -------
    str
        Final status: 'success', 'pending_approval', or 'failed'.
    """
    object.__setattr__(ctx, "source_name", source_cfg.name)
    object.__setattr__(ctx, "analysis_name", analysis_cfg.name)
    object.__setattr__(ctx, "current_file", file_path.name)
    log_input_file_reference(run_log,
        str(file_path),
        file_role="analysis_input",
        display_name=file_path.name,
        source_name=source_cfg.name,
        analysis_name=analysis_cfg.name,
        input_type=getattr(source_cfg, "input_type", ""),
    )
    next_nest_level(run_log)

    move_files = getattr(source_cfg, "move_files", True)

    processing = file_path
    try:
        request    = build_request(source_cfg, analysis_cfg, file_path, ctx=ctx)
        _move_kwargs = {
            "state_ctx": ctx,
            "app": "rey_analyzer",
            "pipeline": getattr(ctx, "pipeline_name", None),
        }
        processing = move_to_processing(file_path, source_cfg, **_move_kwargs) if move_files else file_path

        llm_profile = _resolve_llm_profile(ctx, request.llm_profile_name)
        log_validation_result(run_log,
            validation_name="analyzer_execution_contract",
            status="passed",
            message=(
                f"Resolved governed Analyzer execution for "
                f"'{request.analysis_name}'."
            ),
            source_name=request.source_name,
            analysis_name=request.analysis_name,
            input_file=str(request.file_path),
            input_hash=request.input_hash,
            contract_path=str(request.contract_path),
            contract_hash=request.contract_hash,
            schema_hash=request.schema_hash,
            model_profile=request.llm_profile_name,
            provider=str(getattr(llm_profile, "provider", "") or ""),
            model=str(getattr(llm_profile, "model", "") or ""),
        )
        analyzer    = _build_analyzer(ctx, analysis_cfg, request, llm_profile)
        source      = _build_data_source(source_cfg.input_type, processing, analysis_cfg)
        analysis_inputs = None

        file_set_cfg = analyzer.contract.base.raw_frontmatter.get("file_set") or {}
        required_values = list(file_set_cfg.get("required_values") or [])
        if required_values:
            pipeline_name = str(getattr(ctx, "pipeline_name", "") or "")
            pipeline_cfg = find_in_ctx(ctx, "pipelines", pipeline_name)
            tokens = getattr(pipeline_cfg, "tokens", None) if pipeline_cfg is not None else None
            missing = [name for name in required_values if not hasattr(tokens, name)]
            if missing:
                raise ConfigurationError(
                    "Analysis requires resolved pipeline file-set values: "
                    + ", ".join(missing)
                )

            source_data = source.extract(max_extract=10_000)
            file_set_values = {name: getattr(tokens, name) for name in required_values}
            analysis_inputs = [
                LlmPackageInput(
                    source_path=str(processing),
                    content=source_data.raw_text,
                    input_hash=request.input_hash,
                    name="analysis_input",
                ),
                LlmPackageInput(
                    source_path="",
                    content=file_set_values,
                    name="file_set",
                ),
            ]
            provider_package = build_package(
                analysis={"name": request.analysis_name},
                contract=LlmPackageContract(
                    path=str(request.contract_path),
                    hash=request.contract_hash,
                    content=read_text_file(request.contract_path),
                ),
                inputs=analysis_inputs,
                execution_context={
                    "app": "rey_analyzer",
                    "analysis_name": request.analysis_name,
                    "source_name": request.source_name,
                    "pipeline": pipeline_name,
                },
            )
            source = TextDataSource(
                text=json.dumps(provider_package, ensure_ascii=False),
                ref=processing.name,
            )
        result      = analyzer.analyze(source, analysis_id=request.request_id)

        # Emit per-analysis LLM evidence (LLM_CONTRACT + LLM_CONTEXT) from the
        # values just used, before final run-log completion. Evidence never masks
        # execution (SGC_Rey_Lib_Canonical_LLM_Package_And_Contract_Evidence).
        emit_llm_evidence(ctx, run_log, request, result, inputs=analysis_inputs)

        write_result(
            request,
            result,
            source_cfg,
            analysis_cfg,
            ctx=ctx,
            run_log=run_log,
            workflow_name=workflow_name,
            provider=str(getattr(llm_profile, "provider", "") or ""),
            model=str(getattr(llm_profile, "model", "") or ""),
        )
        log_validation_result(run_log,
            validation_name="analysis_result",
            status=result.status,
            message=f"analysis={analysis_cfg.name} file={file_path.name} status={result.status}",
            source_name=source_cfg.name,
            analysis_name=analysis_cfg.name,
            input_file=str(file_path),
        )

        if result.status == "pending_approval":
            _logger.info(
                "file '%s' pending approval — remaining in processing.",
                file_path.name,
            )
            return "pending_approval"

        if result.status == "success":
            if move_files:
                move_to_success(processing, source_cfg, **_move_kwargs)
            return "success"

        if move_files:
            move_to_failed(processing, source_cfg, **_move_kwargs)
        return "failed"

    except Exception as exc:  # noqa: BLE001
        _logger.error("analysis failed for '%s': %s", file_path.name, exc)
        # Record the actual caught exception as a structured ERROR on the shared run
        # log through the common error path (as every Rey app does), so the real
        # failure survives beyond the Python log line and the failed result.
        log_error(run_log, **build_safe_error_payload(
            exc, message=f"analysis failed for '{file_path.name}'"))
        if move_files:
            try:
                move_to_failed(processing, source_cfg, state_ctx=ctx, app="rey_analyzer", pipeline=getattr(ctx, "pipeline_name", None))
            except Exception:  # noqa: BLE001
                _logger.error("could not move '%s' to failed.", file_path.name)
        log_validation_result(run_log,
            validation_name="analysis_result",
            status="failed",
            message=f"analysis={analysis_cfg.name} file={file_path.name} failed",
            source_name=source_cfg.name,
            analysis_name=analysis_cfg.name,
            input_file=str(file_path),
        )
        return "failed"


def build_payload(
    ctx:          Any,
    analysis_cfg: Any,
    file_path:    Path,
) -> dict[str, Any]:
    """Build the exact LLM payload for one analysis config and file.

    Applies the same extract → prepare pipeline as run_analysis but stops
    before calling the LLM provider. Returns a dict with the formatted
    payload string and preparation metadata.

    Parameters
    ----------
    ctx : Any
        Application context — used to resolve ``contracts_root``.
    analysis_cfg : Any
        Analysis config Namespace (from ctx.analysis_configs).
    file_path : Path
        Absolute path to the file to include in the payload.

    Returns
    -------
    dict[str, Any]
        Keys: analysis_name, data_file, rows_sampled, content.
    """
    from rey_lib.llm.analysis import load_analysis_contract  # noqa: PLC0415
    from rey_lib.llm.preparation import prepare  # noqa: PLC0415

    # Resolve contract path the same way build_request does.
    contracts_root_value = getattr(ctx, "contracts_root", None)
    if not contracts_root_value:
        raise ConfigurationError(
            "Rey Analyzer requires installation-owned 'contracts_root'; "
            "application-relative contract fallback is prohibited."
        )
    contracts_root = Path(str(contracts_root_value)).expanduser().resolve()
    contract_rel = getattr(analysis_cfg, "contract", "")
    if not contract_rel:
        raise ConfigurationError(
            f"analysis_config '{analysis_cfg.name}' has no contract path."
        )
    p = Path(contract_rel)
    contract_path = p.resolve() if p.is_absolute() else (contracts_root / contract_rel).resolve()

    contract = load_analysis_contract(contract_path)

    # Infer input type from file extension — mirrors _build_data_source logic.
    suffix = file_path.suffix.lower()
    input_type_map = {
        ".jsonl": "jsonl_file",
        ".json":  "json_file",
        ".csv":   "csv_file",
        ".xlsx":  "excel_file",
        ".xls":   "excel_file",
    }
    input_type = input_type_map.get(suffix, "text_file")
    source = _build_data_source(input_type, file_path, analysis_cfg)

    spec = contract.spec
    raw = source.extract(max_extract=10_000)
    prepared = prepare(
        raw,
        allowed_columns  = spec.allowed_columns,
        required_filters = spec.required_filters,
        max_rows         = spec.max_rows,
        sampling_method  = spec.sampling_method,
        sampling_seed    = spec.sampling_seed,
        redaction_rules  = spec.redaction,
    )

    _logger.info(
        "build-payload: contract='%s' rows_sampled=%d file='%s'",
        contract.name,
        prepared.profile.rows_sampled,
        file_path.name,
    )

    content = "\n".join([
        f"# {contract.name}",
        "",
        "## System Prompt (Contract)",
        "",
        contract.base.body.strip(),
        "",
        "---",
        "",
        f"## Input Data — {file_path.name} ({prepared.profile.rows_sampled} rows)",
        "",
        prepared.rendered_text,
    ])

    return {
        "analysis_name": analysis_cfg.name,
        "data_file":     file_path.name,
        "rows_sampled":  prepared.profile.rows_sampled,
        "content":       content,
    }


# ---------------------------------------------------------------------------
# Private factories
# ---------------------------------------------------------------------------

# Profile keys forwarded to the provider as options (endpoint, timeout, and
# capability flags). Only keys present on the profile are forwarded.
_PROVIDER_OPTION_KEYS = (
    "endpoint",
    "timeout_seconds",
    "supports_tools",
    "supports_images",
    "supports_json_mode",
    "supports_streaming",
    "supports_system_messages",
    "max_context_tokens",
)


def _profile_provider_options(llm_profile: Any) -> dict[str, Any]:
    """Collect provider option keys present on the LLM profile."""
    options: dict[str, Any] = {}
    for key in _PROVIDER_OPTION_KEYS:
        value = getattr(llm_profile, key, None)
        if value is not None:
            options[key] = value
    return options


def _build_analyzer(
    ctx:          Any,
    analysis_cfg: Any,
    request:      AnalysisRequest,
    llm_profile:  Any,
) -> Analyzer:
    """Construct an Analyzer for the given request."""
    artifact_store = build_artifact_store(ctx)
    _eval = getattr(ctx, "llm_evaluation", None)
    _payload_log = getattr(_eval, "payload_log_path", None) if _eval else None
    _run_log = getattr(_eval, "run_log_path", None) if _eval else None
    return Analyzer(
        contract_path     = request.contract_path,
        provider          = llm_profile.provider,
        model             = llm_profile.model,
        # Built for this one analysis, so the key is read here and lives only
        # as long as the run does.
        api_key           = resolve_env_reference(ctx, getattr(llm_profile, "api_key", "")),
        temperature       = float(getattr(llm_profile, "temperature", 0.0) or 0.0),
        provider_options  = _profile_provider_options(llm_profile),
        artifact_store    = artifact_store,
        requires_approval = request.requires_approval,
        artifact_processing = artifact_config_from_ctx(ctx),
        eval_payload_log_path = Path(_payload_log) if _payload_log else None,
        eval_run_log_path     = Path(_run_log) if _run_log else None,
    )


def _build_data_source(
    input_type:   str,
    file_path:    Path,
    analysis_cfg: Any = None,
) -> DataSource:
    """
    Construct the appropriate DataSource for the given input_type.

    Parameters
    ----------
    input_type : str
        One of: text_file, jsonl_file, json_file, markdown_file,
        csv_file, excel_file.
    file_path : Path
        Absolute path to the file to read.
    analysis_cfg : Any, optional
        Analysis config Namespace. When present and input_type is
        'jsonl_file', applies analysis_cfg.input.include_levels filtering.

    Returns
    -------
    DataSource
        Configured data source instance.

    Raises
    ------
    SourceError
        If input_type is not recognised.
    """
    if input_type == "jsonl_file" and analysis_cfg is not None:
        input_cfg = getattr(analysis_cfg, "input", None)
        if input_cfg is not None:
            text = build_incident_packet(file_path, input_cfg)
            return TextDataSource(text=text, ref=file_path.name)

    if input_type in _TEXT_INPUT_TYPES:
        try:
            text = read_text_file(file_path, encoding="utf-8")
        except OSError as exc:
            raise SourceError(f"Cannot read {file_path}: {exc}") from exc
        return TextDataSource(text=text, ref=file_path.name)

    if input_type == "csv_file":
        return CSVDataSource(path=file_path)

    if input_type == "excel_file":
        return ExcelDataSource(path=file_path)

    raise SourceError(
        f"Unsupported input_type '{input_type}'. "
        f"Supported: text_file, jsonl_file, json_file, markdown_file, "
        f"csv_file, excel_file."
    )


def _resolve_analysis_cfg(ctx: Any, name: str) -> Any:
    """Look up a named analysis config in ctx.analysis_configs."""
    cfg = find_in_ctx(ctx, "analysis_configs", name)
    if cfg is None:
        raise ConfigurationError(
            f"analysis_config '{name}' not found. "
            f"Check config/app/analysis_configs.yaml."
        )
    return cfg


def _resolve_llm_profile(ctx: Any, name: str) -> Any:
    """Look up a named LLM profile in ctx.llm_profiles."""
    profile = find_in_ctx(ctx, "llm_profiles", name)
    if profile is None:
        raise ConfigurationError(
            f"llm_profile '{name}' not found. "
            f"Check config/app/llm_configs.yaml."
        )
    return profile


def _max_files(ctx: Any, source_cfg: Any) -> int:
    """Return the effective per-run file cap for a data source."""
    runtime_max = getattr(getattr(ctx, "runtime", None), "max_files_per_run", 100)
    source_max  = getattr(source_cfg, "max_files_per_run", runtime_max)
    return min(runtime_max, source_max)
