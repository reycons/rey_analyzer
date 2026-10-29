"""infer_tabular_discard_rules v02: the contract carries its own output schema.

The fixture is the text stored in control.analysis_contract for local and
wolff_popper (backlog 903) -- its md5 is the stored row's, so the fixture cannot
drift from the database. The schema is the contract's embedded output_schema;
there is no sidecar.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

from rey_lib.analysis import parse_analysis_contract
from rey_lib.encryption import sha256_text

from rey_analyzer.requests import _compute_request_id, build_request

FIXTURE = Path(__file__).with_name("fixtures") / "infer_tabular_discard_rules.v02.md"
#: md5 of the v02 text stored in control.analysis_contract (both installations).
STORED_V02_MD5 = "21c4664c85059bd36ad25143832dca66"
#: The v01 era: sha256 of the v01 contract file and of its v01.schema.json sidecar.
V01_CONTRACT_SHA256 = "57a59542a99890a51e6f9255fdff067d9d1675d4133198d5a3591e3eb56211c2"
V01_SIDECAR_SHA256 = "bc3dcd5c051dfa29700e636a0740a92272fb035d0d951cb2b3c60a6b1c7a5d05"


def _v02_text() -> str:
    text = FIXTURE.read_text(encoding="utf-8")
    assert hashlib.md5(text.encode("utf-8")).hexdigest() == STORED_V02_MD5
    return text


def _evidence(line: int = 1) -> list[dict[str, object]]:
    return [{"source_file": "sample.csv", "physical_line_number": line}]


def _candidate() -> dict[str, object]:
    return {
        "schema_version": 1,
        "file_type": "file_type_0123456789abcdef",
        "tables": [
            {
                "name": "positions",
                "expected_columns": ["Account", "Amount"],
                "header": {
                    "match": {
                        "type": "exact_fields",
                        "values": ["Account", "Amount"],
                        "case_sensitive": True,
                        "trim_fields": True,
                    },
                    "keep_first": True,
                    "repeated": {
                        "comparison": "normalized_exact",
                        "action": "drop",
                        "evidence": _evidence(20),
                        "confidence": 1.0,
                    },
                    "evidence": _evidence(2),
                    "confidence": 1.0,
                },
                "start": {
                    "type": "header",
                    "evidence": _evidence(2),
                    "confidence": 1.0,
                },
                "end": {
                    "type": "eof",
                    "evidence": _evidence(30),
                    "confidence": 1.0,
                },
                "row_rules": [
                    {
                        "name": "drop_blank",
                        "order": 1,
                        "action": "drop",
                        "standard": "blank",
                        "evidence": _evidence(9),
                        "confidence": 1.0,
                    },
                    {
                        "name": "drop_footer",
                        "order": 2,
                        "action": "drop",
                        "match": {
                            "type": "contains",
                            "value": "End of report",
                            "case_sensitive": False,
                        },
                        "evidence": _evidence(29),
                        "confidence": 0.99,
                    },
                ],
            }
        ],
        "unresolved_ambiguities": [],
    }


@pytest.fixture(scope="module")
def contract():
    parsed = parse_analysis_contract(_v02_text(), "markdown")
    assert parsed.name == "infer_tabular_discard_rules"
    assert parsed.version == "02"
    assert parsed.spec.output_format == "json"
    return parsed


@pytest.fixture(scope="module")
def schema(contract) -> dict[str, object]:
    loaded = contract.spec.output_schema
    assert loaded is not None
    jsonschema.Draft7Validator.check_schema(loaded)
    return loaded


def test_accepts_strict_candidate_json(schema: dict[str, object]) -> None:
    jsonschema.validate(_candidate(), schema)


def test_rejects_prose_only_response(schema: dict[str, object]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("The file contains one table.", schema)


def test_rejects_unresolved_ambiguity(schema: dict[str, object]) -> None:
    candidate = _candidate()
    candidate["unresolved_ambiguities"] = ["Two boundary rows are plausible."]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("tables", 0, "row_rules", 0, "standard"), "fuzzy_header"),
        (("tables", 0, "header", "match", "type"), "fuzzy_fields"),
        (("tables", 0, "end", "type"), "after_match"),
    ],
)
def test_rejects_unsupported_rules(
    schema: dict[str, object],
    path: tuple[object, ...],
    value: object,
) -> None:
    candidate = copy.deepcopy(_candidate())
    target: object = candidate
    for key in path[:-1]:
        target = target[key]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)


def test_rejects_rule_without_line_evidence(schema: dict[str, object]) -> None:
    candidate = _candidate()
    candidate["tables"][0]["row_rules"][0]["evidence"] = []  # type: ignore[index]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)


def test_rejects_unbounded_regex(schema: dict[str, object]) -> None:
    candidate = _candidate()
    candidate["tables"][0]["row_rules"][1] = {  # type: ignore[index]
        "name": "catch_all",
        "order": 2,
        "action": "drop",
        "match": {"type": "regex", "pattern": "^.*$", "flags": []},
        "evidence": _evidence(29),
        "confidence": 0.9,
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(candidate, schema)


def test_schema_excludes_durable_rule_set_fields(
    schema: dict[str, object],
) -> None:
    for forbidden in (
        "file_references",
        "validations",
        "lineage",
        "approval",
        "canonicalization",
        "status",
    ):
        candidate = _candidate()
        candidate[forbidden] = {}
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(candidate, schema)


def test_the_embedded_schema_is_the_former_sidecar(schema: dict[str, object]) -> None:
    assert schema["$id"].endswith("/v01")
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"


# ---------------------------------------------------------------------------
# The intended behaviour changes of v02 (backlog 903) that do not execute the
# contract. Executing it ran on the legacy AI, removed by #1025 (#1283).
# ---------------------------------------------------------------------------

def test_change_2_contract_hash_is_the_v02_text(contract) -> None:
    assert contract.hash == sha256_text(_v02_text())
    assert contract.hash != V01_CONTRACT_SHA256


def test_change_3_request_id_differs_from_the_v01_era(contract, tmp_path: Path) -> None:
    """build_request reads the contract by name; its schema hash is the embedded one."""
    analysed = tmp_path / "file_type_0123456789abcdef.analysis.json"
    analysed.write_text("{}", encoding="utf-8")
    control = SimpleNamespace(
        installation_id=1,
        analysis_contract=lambda name: {
            "name": name, "format": "markdown", "contract_text": _v02_text(),
        },
    )
    analysis_cfg = SimpleNamespace(
        name="infer_tabular_discard_rules", contract="infer_tabular_discard_rules",
        llm_execution_profile="primary", idempotency_mode="reuse_success",
        requires_approval=False,
    )

    request = build_request(
        SimpleNamespace(name="data_engine"), analysis_cfg, analysed,
        ctx=SimpleNamespace(shared_control=control),
    )

    embedded = sha256_text(json.dumps(contract.spec.output_schema, sort_keys=True))
    assert request.schema_hash == embedded
    assert request.contract_hash == contract.hash
    assert request.request_id == _compute_request_id(request.input_hash, contract.hash, embedded)
    assert request.request_id != _compute_request_id(
        request.input_hash, V01_CONTRACT_SHA256, V01_SIDECAR_SHA256,
    )
