"""
ETL JSONL log preprocessor.

Converts a raw JSONL log into a compact incident packet before LLM analysis.
Implements the ETL Log Preprocessing Contract.

Processing stages (in order):
1. Level filtering     — discard INFO/DEBUG noise
2. Field selection     — keep only operationally relevant fields
3. Width limiting      — truncate large message/stack/sql/ctx fields
4. Grouping            — cluster records by (level, operation, message pattern)
5. Sampling            — keep up to N representative examples per group
6. Aggregation         — compute counts, file lists, and summary statistics

Output is a JSON string (incident packet) suitable for LLM analysis.

Public API
----------
build_incident_packet    Convert a JSONL file to a compact incident packet string.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rey_lib.logs.log_utils import get_logger

from rey_analyzer.error_utils import SourceError

__all__ = ["build_incident_packet"]

_logger = get_logger(__name__)

# Fields treated as stack traces for width limiting.
_STACK_FIELDS: frozenset[str] = frozenset({"exception", "stack_trace", "traceback"})

# Fields treated as SQL for width limiting.
_SQL_FIELDS: frozenset[str] = frozenset({"sql", "query", "proc"})

# Default limits — all overridable via analysis config.
_DEFAULT_MAX_MESSAGE_CHARS:   int = 1000
_DEFAULT_MAX_STACK_CHARS:     int = 3000
_DEFAULT_MAX_SQL_CHARS:       int = 3000
_DEFAULT_MAX_CTX_FIELD_CHARS: int = 500
_DEFAULT_MAX_EXAMPLES:        int = 3


def build_incident_packet(file_path: Path, input_cfg: Any) -> str:
    """Convert a raw JSONL log file into a compact incident packet JSON string.

    Applies level filtering, field selection, width limiting, deduplication,
    representative sampling, and statistical aggregation before returning
    a structured JSON string ready for LLM consumption.

    Parameters
    ----------
    file_path : Path
        Absolute path to the JSONL log file.
    input_cfg : Any
        Namespace with optional preprocessing config attributes.

    Returns
    -------
    str
        JSON-serialised incident packet.

    Raises
    ------
    SourceError
        If the file cannot be read.
    """
    include_levels    = _resolve_levels(input_cfg)
    include_fields    = _resolve_fields(input_cfg)
    max_msg           = int(getattr(input_cfg, "max_message_chars",   _DEFAULT_MAX_MESSAGE_CHARS))
    max_stack         = int(getattr(input_cfg, "max_stack_chars",     _DEFAULT_MAX_STACK_CHARS))
    max_sql           = int(getattr(input_cfg, "max_sql_chars",       _DEFAULT_MAX_SQL_CHARS))
    max_ctx           = int(getattr(input_cfg, "max_ctx_field_chars", _DEFAULT_MAX_CTX_FIELD_CHARS))
    max_examples      = int(getattr(input_cfg, "max_examples_per_group", _DEFAULT_MAX_EXAMPLES))

    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SourceError(f"Cannot read {file_path}: {exc}") from exc

    all_lines  = [l for l in raw_text.splitlines() if l.strip()]
    total_rows = len(all_lines)

    records: list[dict[str, Any]] = []
    for line in all_lines:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if include_levels and rec.get("level", "").upper() not in include_levels:
            continue
        rec = _select_fields(rec, include_fields)
        rec = _apply_width_limits(rec, max_msg, max_stack, max_sql, max_ctx)
        records.append(rec)

    groups      = _group_records(records, max_examples)
    group_count = len(groups)

    packet: dict[str, Any] = {
        "source_file":   file_path.name,
        "total_rows":    total_rows,
        "included_rows": len(records),
        "group_count":   group_count,
        "groups":        groups,
    }

    _logger.info(
        "preprocessor: total=%d included=%d groups=%d file=%s",
        total_rows,
        len(records),
        group_count,
        file_path.name,
    )
    return json.dumps(packet, default=str, indent=2)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resolve_levels(input_cfg: Any) -> frozenset[str]:
    """Return the set of log levels to include, or empty set meaning all."""
    raw = getattr(input_cfg, "include_levels", None)
    if not raw:
        return frozenset()
    return frozenset(str(l).upper() for l in raw)


def _resolve_fields(input_cfg: Any) -> frozenset[str]:
    """Return the set of fields to retain, or empty set meaning all."""
    raw = getattr(input_cfg, "include_fields", None)
    if not raw:
        return frozenset()
    return frozenset(str(f) for f in raw)


def _select_fields(rec: dict[str, Any], include_fields: frozenset[str]) -> dict[str, Any]:
    """Keep only include_fields keys. No-op when include_fields is empty."""
    if not include_fields:
        return rec
    return {k: v for k, v in rec.items() if k in include_fields}


def _apply_width_limits(
    rec:       dict[str, Any],
    max_msg:   int,
    max_stack: int,
    max_sql:   int,
    max_ctx:   int,
) -> dict[str, Any]:
    """Truncate oversized string fields in place."""
    out: dict[str, Any] = {}
    for key, val in rec.items():
        if key == "message" and isinstance(val, str) and len(val) > max_msg:
            val = val[:max_msg]
        elif key in _STACK_FIELDS and isinstance(val, str) and len(val) > max_stack:
            val = val[:max_stack]
        elif key in _SQL_FIELDS and isinstance(val, str) and len(val) > max_sql:
            val = val[:max_sql]
        elif key == "ctx_dump" and isinstance(val, dict):
            val = {
                k: (v[:max_ctx] if isinstance(v, str) and len(v) > max_ctx else v)
                for k, v in val.items()
            }
        out[key] = val
    return out


def _group_key(rec: dict[str, Any]) -> tuple[str, str, str]:
    """Return a stable grouping key for a record."""
    level     = str(rec.get("level", "")).upper()
    operation = str(rec.get("operation", ""))
    message   = str(rec.get("message", ""))[:120]
    return (level, operation, message)


def _extract_file_name(rec: dict[str, Any]) -> str | None:
    """Extract file name from a record, checking common field locations."""
    for field in ("file_name", "current_file_name", "source_path"):
        val = rec.get(field)
        if val:
            return str(val)
    ctx = rec.get("ctx_dump")
    if isinstance(ctx, dict):
        for field in ("current_file_name", "file_name"):
            val = ctx.get(field)
            if val:
                return str(val)
    return None


def _group_records(
    records:      list[dict[str, Any]],
    max_examples: int,
) -> list[dict[str, Any]]:
    """Group records by (level, operation, message) and sample examples."""
    seen:   dict[tuple, dict[str, Any]] = {}
    order:  list[tuple]                 = []

    for rec in records:
        key = _group_key(rec)
        if key not in seen:
            order.append(key)
            seen[key] = {
                "level":          key[0],
                "operation":      key[1],
                "message_sample": key[2],
                "count":          0,
                "files":          [],
                "_examples":      [],
            }

        group = seen[key]
        group["count"] += 1

        file_name = _extract_file_name(rec)
        if file_name and file_name not in group["files"]:
            group["files"].append(file_name)

        # Keep first, last, and up to max_examples total.
        examples: list[dict] = group["_examples"]
        if len(examples) == 0:
            examples.append(rec)
        elif len(examples) < max_examples:
            examples.append(rec)
        else:
            examples[-1] = rec  # Replace last with most recent.

    groups: list[dict[str, Any]] = []
    for key in order:
        g = seen[key]
        examples = g.pop("_examples")
        g["examples"] = examples
        groups.append(g)

    return groups
