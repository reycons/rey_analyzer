from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest

from rey_lib.analysis import load_analysis_contract
from rey_lib.analysis.contract import load_sidecar_schema as _load_sidecar_schema


CONTRACT = (
    Path(__file__).parents[2]
    / "contracts"
    / "infer_tabular_discard_rules"
    / "v01.md"
)


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
def schema() -> dict[str, object]:
    contract = load_analysis_contract(CONTRACT)
    assert contract.name == "infer_tabular_discard_rules"
    assert contract.spec.output_format == "json"
    loaded = _load_sidecar_schema(CONTRACT)
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


def test_sidecar_is_valid_json() -> None:
    parsed = json.loads(CONTRACT.with_name("v01.schema.json").read_text())
    assert parsed["$id"].endswith("/v01")
