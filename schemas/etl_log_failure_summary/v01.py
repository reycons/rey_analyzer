"""
Schema: etl_log_failure_summary v01

JSON Schema for validating LLM output from the etl_log_failure contract.
Immutable once versioned — create v02.py for any changes.
"""

SCHEMA: dict = {
    "type": "object",
    "properties": {
        "failure_count": {"type": "integer", "minimum": 0},
        "warning_count": {"type": "integer", "minimum": 0},
        "severity": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "patterns": {
            "type": "array",
            "items": {"type": "string"},
        },
        "summary": {"type": "string"},
        "recommended_actions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "failure_count",
        "warning_count",
        "severity",
        "patterns",
        "summary",
        "recommended_actions",
    ],
    "additionalProperties": False,
}
