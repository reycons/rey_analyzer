"""Tests for per-analysis LLM evidence emission
(SGC_Rey_Lib_Canonical_LLM_Package_And_Contract_Evidence).

rey_analyzer adopts the canonical package and emits LLM_CONTRACT and LLM_CONTEXT
for each analysis, carrying the identifiers that correlate the evidence to the
existing ExecutionRecord result and its artifacts. Provider behavior is unchanged.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import rey_analyzer.evidence as evidence
from rey_analyzer.evidence import build_analysis_package, emit_llm_evidence


def _request(tmp_path: Path) -> SimpleNamespace:
    contract = tmp_path / "contract.md"
    contract.write_text("---\nname: c\nversion: 1\n---\nRULES\n", encoding="utf-8")
    source = tmp_path / "profile.json"
    source.write_text('{"columns": ["a"]}', encoding="utf-8")
    return SimpleNamespace(
        analysis_name="file_profile_to_loader_config",
        source_name="profile_source",
        request_id="req-123",
        file_path=source,
        input_hash="inhash",
        contract_path=contract,
        contract_hash="conhash",
    )


def _result() -> SimpleNamespace:
    # The AnalysisResult carries the payload actually supplied to the provider.
    prepared = SimpleNamespace(rendered_text="| a |\n| - |\n| 1 |")
    record = SimpleNamespace(
        run_id="exec-uuid", idempotency_key="req-123",
        contract_hash="conhash", input_hash="inhash", artifact_uris=["file:///a.json"],
    )
    return SimpleNamespace(status="success", prepared=prepared, record=record)


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(run_id="run-1", pipeline_name="p1")


# TEST-003 / AC-006
def test_analyzer_builds_canonical_package_with_exactly_one_input(tmp_path: Path) -> None:
    """The rey_analyzer package is canonical and single-input."""
    package = build_analysis_package(_ctx(), _request(tmp_path), _result())

    assert set(package) == {"analysis", "contract", "inputs", "execution_context"}
    assert len(package["inputs"]) == 1
    assert package["analysis"]["name"] == "file_profile_to_loader_config"


# TEST-004 / AC-007
def test_package_contract_uses_already_resolved_evidence(tmp_path: Path) -> None:
    """Contract path and hash equal the resolved request evidence; separate from inputs."""
    request = _request(tmp_path)
    package = build_analysis_package(_ctx(), request, _result())

    assert package["contract"]["path"] == str(request.contract_path)
    assert package["contract"]["hash"] == "conhash"      # the request's hash, not re-derived
    assert "RULES" in package["contract"]["content"]
    # Contract is never an input.
    assert all(entry.get("name") != "contract" for entry in package["inputs"])


# TEST-006 / AC-009 / AC-009A
def test_context_input_is_the_payload_actually_supplied(tmp_path: Path) -> None:
    """The single input carries the prepared payload the provider received."""
    package = build_analysis_package(_ctx(), _request(tmp_path), _result())
    entry = package["inputs"][0]
    assert entry["content"] == "| a |\n| - |\n| 1 |"       # result.prepared.rendered_text
    assert entry["input_hash"] == "inhash"


# TEST-005 / TEST-006A / AC-008 / AC-009C
def test_emits_contract_and_context_with_correlation_identifiers(tmp_path, monkeypatch) -> None:
    """Both records are emitted, carrying identifiers that reach the ExecutionRecord."""
    emitted: list[tuple] = []
    monkeypatch.setattr(
        evidence, "log_run_record",
        lambda ctx, record_type, **fields: emitted.append((record_type, fields)),
    )
    request, result = _request(tmp_path), _result()
    emit_llm_evidence(_ctx(), request, result)

    by_type = {record_type: fields for record_type, fields in emitted}
    assert set(by_type) == {"LLM_CONTRACT", "LLM_CONTEXT"}

    # LLM_CONTRACT: exact resolved contract identity.
    contract = by_type["LLM_CONTRACT"]
    assert contract["contract_path"] == str(request.contract_path)
    assert contract["contract_hash"] == "conhash"

    # Both carry the correlation spine that appears on the ExecutionRecord:
    # request_id == idempotency_key, plus contract_hash / input_hash, plus analysis_name.
    for fields in by_type.values():
        assert fields["analysis_name"] == "file_profile_to_loader_config"
        assert fields["request_id"] == result.record.idempotency_key == "req-123"
        assert fields["contract_hash"] == result.record.contract_hash
        assert fields["input_hash"] == result.record.input_hash

    # LLM_CONTEXT carries the canonical package as the effective invocation context.
    assert set(by_type["LLM_CONTEXT"]["package"]) == {
        "analysis", "contract", "inputs", "execution_context",
    }


def test_evidence_emission_never_masks_the_analysis(tmp_path, monkeypatch) -> None:
    """A failure while emitting evidence is swallowed, not raised."""
    def boom(*_a, **_k):
        raise RuntimeError("record writer down")

    monkeypatch.setattr(evidence, "log_run_record", boom)
    # Must not raise.
    assert emit_llm_evidence(_ctx(), _request(tmp_path), _result()) == {}


# TEST-006B / AC-009B
def test_evidence_module_does_not_touch_the_provider_wire() -> None:
    """Building/emitting evidence imports no provider or runner invocation path."""
    import ast

    tree = ast.parse(Path(evidence.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "rey_lib.llm.package" in imported          # the canonical builder
    for forbidden in ("rey_lib.llm.runner", "rey_lib.llm.llm_utils",
                      "rey_lib.llm.adapters", "rey_lib.llm.providers"):
        assert forbidden not in imported, forbidden
