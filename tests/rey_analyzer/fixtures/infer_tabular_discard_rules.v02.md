---
name: infer_tabular_discard_rules
version: "02"
effective_date: "2026-10-12"
source_type: text
output:
  format: json
max_rows: 10000
sampling:
  method: head
output_schema: {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "rey://rey_analyzer/infer_tabular_discard_rules/v01",
    "title": "File Operator structural discard-rule candidate",
    "type": "object",
    "additionalProperties": false,
    "required": [
      "schema_version",
      "file_type",
      "tables",
      "unresolved_ambiguities"
    ],
    "properties": {
      "schema_version": {
        "const": 1
      },
      "file_type": {
        "type": "string",
        "pattern": "^file_type_[0-9a-f]{16}$"
      },
      "tables": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "items": {
          "$ref": "#/definitions/table"
        }
      },
      "unresolved_ambiguities": {
        "type": "array",
        "maxItems": 0
      }
    },
    "definitions": {
      "non_empty_string": {
        "type": "string",
        "minLength": 1,
        "maxLength": 512
      },
      "confidence": {
        "type": "number",
        "minimum": 0,
        "maximum": 1
      },
      "evidence": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "uniqueItems": true,
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": [
            "source_file",
            "physical_line_number"
          ],
          "properties": {
            "source_file": {
              "$ref": "#/definitions/non_empty_string"
            },
            "physical_line_number": {
              "type": "integer",
              "minimum": 1
            }
          }
        }
      },
      "field_match": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "values",
          "case_sensitive",
          "trim_fields"
        ],
        "properties": {
          "type": {
            "enum": [
              "exact_fields",
              "contains_fields"
            ]
          },
          "values": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "items": {
              "$ref": "#/definitions/non_empty_string"
            }
          },
          "case_sensitive": {
            "type": "boolean"
          },
          "trim_fields": {
            "type": "boolean"
          }
        }
      },
      "repeated_header": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "comparison",
          "action",
          "evidence",
          "confidence"
        ],
        "properties": {
          "comparison": {
            "const": "normalized_exact"
          },
          "action": {
            "const": "drop"
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "header": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "match",
          "keep_first",
          "repeated",
          "evidence",
          "confidence"
        ],
        "properties": {
          "match": {
            "$ref": "#/definitions/field_match"
          },
          "keep_first": {
            "const": true
          },
          "repeated": {
            "$ref": "#/definitions/repeated_header"
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "start": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "type",
          "evidence",
          "confidence"
        ],
        "properties": {
          "type": {
            "const": "header"
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "end": {
        "oneOf": [
          {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "type",
              "evidence",
              "confidence"
            ],
            "properties": {
              "type": {
                "const": "eof"
              },
              "evidence": {
                "$ref": "#/definitions/evidence"
              },
              "confidence": {
                "$ref": "#/definitions/confidence"
              }
            }
          },
          {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "type",
              "match",
              "evidence",
              "confidence"
            ],
            "properties": {
              "type": {
                "const": "before_match"
              },
              "match": {
                "$ref": "#/definitions/field_match"
              },
              "evidence": {
                "$ref": "#/definitions/evidence"
              },
              "confidence": {
                "$ref": "#/definitions/confidence"
              }
            }
          }
        ]
      },
      "standard_row_rule": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "name",
          "order",
          "action",
          "standard",
          "evidence",
          "confidence"
        ],
        "properties": {
          "name": {
            "$ref": "#/definitions/non_empty_string"
          },
          "order": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000
          },
          "action": {
            "const": "drop"
          },
          "standard": {
            "enum": [
              "blank",
              "repeated_header"
            ]
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "contains_row_rule": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "name",
          "order",
          "action",
          "match",
          "evidence",
          "confidence"
        ],
        "properties": {
          "name": {
            "$ref": "#/definitions/non_empty_string"
          },
          "order": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000
          },
          "action": {
            "const": "drop"
          },
          "match": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "type",
              "value",
              "case_sensitive"
            ],
            "properties": {
              "type": {
                "const": "contains"
              },
              "value": {
                "$ref": "#/definitions/non_empty_string"
              },
              "case_sensitive": {
                "type": "boolean"
              }
            }
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "regex_row_rule": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "name",
          "order",
          "action",
          "match",
          "evidence",
          "confidence"
        ],
        "properties": {
          "name": {
            "$ref": "#/definitions/non_empty_string"
          },
          "order": {
            "type": "integer",
            "minimum": 1,
            "maximum": 1000
          },
          "action": {
            "const": "drop"
          },
          "match": {
            "type": "object",
            "additionalProperties": false,
            "required": [
              "type",
              "pattern",
              "flags"
            ],
            "properties": {
              "type": {
                "const": "regex"
              },
              "pattern": {
                "type": "string",
                "minLength": 1,
                "maxLength": 512,
                "pattern": "^(?!.*\\.\\*)(?!.*\\.\\+)(?!.*\\[[^]]+\\][*+])(?!.*\\([^)]*\\)[*+]).+$"
              },
              "flags": {
                "type": "array",
                "maxItems": 2,
                "uniqueItems": true,
                "items": {
                  "enum": [
                    "IGNORECASE",
                    "MULTILINE"
                  ]
                }
              }
            }
          },
          "evidence": {
            "$ref": "#/definitions/evidence"
          },
          "confidence": {
            "$ref": "#/definitions/confidence"
          }
        }
      },
      "row_rule": {
        "oneOf": [
          {
            "$ref": "#/definitions/standard_row_rule"
          },
          {
            "$ref": "#/definitions/contains_row_rule"
          },
          {
            "$ref": "#/definitions/regex_row_rule"
          }
        ]
      },
      "table": {
        "type": "object",
        "additionalProperties": false,
        "required": [
          "name",
          "expected_columns",
          "header",
          "start",
          "end",
          "row_rules"
        ],
        "properties": {
          "name": {
            "$ref": "#/definitions/non_empty_string"
          },
          "expected_columns": {
            "type": "array",
            "minItems": 1,
            "maxItems": 1000,
            "uniqueItems": true,
            "items": {
              "$ref": "#/definitions/non_empty_string"
            }
          },
          "header": {
            "$ref": "#/definitions/header"
          },
          "start": {
            "$ref": "#/definitions/start"
          },
          "end": {
            "$ref": "#/definitions/end"
          },
          "row_rules": {
            "type": "array",
            "maxItems": 1000,
            "items": {
              "$ref": "#/definitions/row_rule"
            }
          }
        }
      }
    }
  }
---

# Infer tabular discard rules

Analyze exactly one File Operator `{file_type}.analysis.json` artifact. The
artifact's `file_type` and its authoritative grouping facts are facts, not
suggestions. Structural pattern summaries are the primary evidence; ordered
context supplies sequence, header, boundary, anomaly, and region-transition
evidence.

Return exactly one JSON object matching this contract's output_schema. Return
no Markdown, code fence, explanation, final File Operator YAML, rewritten
source data, Python, or shell commands.

## Required proposal

- Copy `file_type` exactly from the input.
- Propose one or more non-overlapping tables in source order.
- For every table, propose the exact expected output column order, header
  matcher, header start, end boundary, repeated-header behavior, and ordered
  discard rules.
- Use only `exact_fields` or `contains_fields` for header and boundary field
  matching.
- Use only the standard discard rules `blank` and `repeated_header`, or an
  explicit `contains` or bounded `regex` match.
- Every header, start, end, repeated-header behavior, and discard rule must
  cite at least one observed source file and physical line number and include
  a confidence from 0 through 1.
- Rule `order` values must be unique, strictly increasing in array order, and
  start at 1.
- Table regions must be sequential and non-overlapping. A table ending at EOF
  must be the final table.
- Preserve header spelling and column order from evidence. Never normalize,
  rename, infer, or reorder output columns.

## Fail-closed rules

The candidate schema requires `unresolved_ambiguities` to be empty. Therefore,
do not emit a candidate when any material ambiguity remains. An ambiguous
response must fail schema validation instead of silently selecting an answer.
Material ambiguity includes:

- two plausible headers, table boundaries, or output column orders;
- a rule without source-line evidence;
- incomplete structural-pattern evidence or truncation that hides a pattern
  needed to justify a rule;
- disagreement among matching files that cannot be represented by the same
  table definitions;
- a proposed table region that overlaps another region;
- a regex that is broad or unbounded.

Regex proposals must be anchored or otherwise narrowly tied to observed
evidence. Do not use `.*`, `.+`, unbounded character-class/group repetition,
or a catch-all expression.

Header-only identity is provisional. The input artifact may support a
proposal, but it does not approve a rule set. Later deterministic validation
must apply the candidate to every matching source file before promotion.

## Ownership boundary

This response is an untrusted candidate only. Do not emit rule-set names,
versions, status, activation flags, file references, validations, lineage,
approval, canonicalization, hashes, or promotion records. A later
deterministic File Operator step owns validation and materialization of the
canonical `file_operator_rule_sets` YAML.
