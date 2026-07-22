"""
Canonical LLM package and per-analysis evidence for rey_analyzer
(SGC_Rey_Lib_Canonical_LLM_Package_And_Contract_Evidence).

rey_analyzer is the natural adoption path for the canonical LLM package: an
analysis request already carries every canonical field — the source file, its
hash, the resolved contract path and hash, and the analysis identity — so the
package is assembled from already-resolved evidence rather than reconstructed.

This module builds that canonical package for an analysis invocation and emits
two durable run-log records at execution time:

  LLM_CONTRACT  the exact resolved contract used (path + hash + identity).
  LLM_CONTEXT   the effective invocation context: the resolved contract content,
                the payload actually supplied to the provider, and execution
                context, carried as the canonical package.

Both records carry the correlation identifiers (run_id via the standard record
writer, plus analysis_name, request_id, contract_hash, input_hash) so a later
projector can associate them with the existing ExecutionRecord result and its
artifacts under one analysis. Neither record is the provider wire payload, and
emitting them does not change provider behavior.
"""

from __future__ import annotations

from typing import Any

from rey_lib.files import read_text_file
from rey_lib.llm.package import LlmPackageContract, LlmPackageInput, build_package
from rey_lib.logs import get_logger, log_run_record

_logger = get_logger(__name__)

# The default logical input a rey_analyzer analysis supplies. Named for lineage.
_ANALYSIS_INPUT_NAME = "analysis_input"


def build_analysis_package(
    ctx: Any,
    request: Any,
    result: Any,
    *,
    inputs: list[LlmPackageInput] | None = None,
) -> dict[str, Any]:
    """Build the canonical LLM package for an analysis invocation.

    The contract stays structurally separate from ``inputs``. Callers may supply
    the exact logical inputs sent to the provider; otherwise the existing single
    prepared analysis input is projected. Content and the contract hash come from
    already-resolved request evidence and the shared file utilities.

    Parameters
    ----------
    ctx : Any
        The analysis run context (carries run identity).
    request : Any
        The AnalysisRequest for this invocation.
    result : Any
        The AnalysisResult returned by the analyzer; ``result.prepared`` carries
        the payload actually supplied to the provider.

    Returns
    -------
    dict[str, Any]
        The canonical package (analysis / contract / inputs / execution_context).
    """
    analysis_name = str(getattr(request, "analysis_name", "") or "")
    # The contract content is read through the shared file boundary (also recording
    # the read as file evidence). The authoritative identity is the already-resolved
    # request.contract_hash; content is best-effort and never re-resolved.
    contract_content = ""
    contract_path = str(getattr(request, "contract_path", "") or "")
    if contract_path:
        try:
            contract_content = read_text_file(contract_path)
        except OSError as exc:  # pragma: no cover - evidence never masks execution
            _logger.warning("LLM contract content unavailable for evidence: %s", exc)

    contract = LlmPackageContract(
        path=contract_path,
        hash=str(getattr(request, "contract_hash", "") or ""),
        content=contract_content,
    )

    if inputs is None:
        prepared = getattr(result, "prepared", None)
        payload_text = str(getattr(prepared, "rendered_text", "") or "")
        inputs = [
            LlmPackageInput(
                source_path=str(getattr(request, "file_path", "") or ""),
                content=payload_text,
                input_hash=str(getattr(request, "input_hash", "") or ""),
                name=_ANALYSIS_INPUT_NAME,
            )
        ]

    execution_context = {
        "run_id": str(getattr(ctx, "run_id", "") or ""),
        "app": "rey_analyzer",
        "analysis_name": analysis_name,
        "source_name": str(getattr(request, "source_name", "") or ""),
        "request_id": str(getattr(request, "request_id", "") or ""),
        "pipeline": str(getattr(ctx, "pipeline_name", "") or ""),
    }

    # The contract may declare reference documents; resolve and attach their full
    # contents as a sibling of the contract section, reusing the shared rey_lib
    # reference loader (existing path-token resolver + approved text loader).
    from rey_lib.logs.llm_package import load_contract_references

    declared_references = None
    if contract_path:
        try:
            from rey_lib.llm.contract import load as _load_contract
            declared_references = _load_contract(contract_path).raw_frontmatter.get("references")
        except Exception as exc:  # pragma: no cover - evidence never masks execution
            _logger.warning("Contract references unavailable for evidence: %s", exc)

    return build_package(
        analysis={"name": analysis_name, "run_id": execution_context["run_id"]},
        contract=contract,
        inputs=inputs,
        execution_context=execution_context,
        references=load_contract_references(ctx, declared_references),
    )


def _correlation_fields(request: Any) -> dict[str, Any]:
    """Return the identifiers that correlate evidence to the existing result.

    request_id matches ExecutionRecord.idempotency_key; contract_hash and
    input_hash match the ExecutionRecord fields of the same name. run_id is added
    by the standard record writer from ctx.
    """
    return {
        "analysis_name": str(getattr(request, "analysis_name", "") or ""),
        "request_id": str(getattr(request, "request_id", "") or ""),
        "contract_hash": str(getattr(request, "contract_hash", "") or ""),
        "input_hash": str(getattr(request, "input_hash", "") or ""),
    }


def emit_llm_evidence(
    ctx: Any,
    request: Any,
    result: Any,
    *,
    inputs: list[LlmPackageInput] | None = None,
) -> dict[str, Any]:
    """Emit LLM_CONTRACT and LLM_CONTEXT for one analysis invocation.

    Called after the analyzer returns, so the evidence is captured at execution
    time from already-computed values, not reconstructed later. Evidence emission
    never masks execution: a failure here is logged and swallowed.

    Returns
    -------
    dict[str, Any]
        The canonical package that was emitted as LLM_CONTEXT.
    """
    try:
        package = build_analysis_package(ctx, request, result, inputs=inputs)
        correlation = _correlation_fields(request)

        # LLM_CONTRACT: the exact resolved contract used for this analysis.
        log_run_record(
            ctx,
            "LLM_CONTRACT",
            record_group="results",
            contract_path=package["contract"]["path"],
            **correlation,
        )

        # LLM_CONTEXT: the effective invocation context, as the canonical package.
        log_run_record(
            ctx,
            "LLM_CONTEXT",
            record_group="results",
            package=package,
            **correlation,
        )
        return package
    except Exception as exc:  # noqa: BLE001 — evidence must never break an analysis
        _logger.warning("Failed to emit LLM evidence: %s", exc)
        return {}
