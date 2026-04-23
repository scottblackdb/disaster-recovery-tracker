"""Structured extraction via Databricks SQL ai_extract(ai_parse_document(volume_path), schema).

PDF: direct UC file path into ai_parse_document (same shape as interactive SQL).
CSV: ai_parse_document does not support CSV — read_files as text, then ai_extract on the string.
"""
from __future__ import annotations

import json
import logging
import time
from decimal import Decimal
from typing import Any, Optional

from databricks.sdk.service.sql import (
    Disposition,
    ExecuteStatementRequestOnWaitTimeout,
    Format,
    StatementState,
)

from config import WAREHOUSE_ID
from databricks_auth import w

_logger = logging.getLogger(__name__)

# Same field list as: ai_extract(..., '["invoice_id","vendor_name","total_amount","invoice_date"]')
ESTIMATE_EXTRACT_SCHEMA = '["invoice_id","vendor_name","total_amount","invoice_date"]'


def validate_uc_single_file_volume_path(volume_path: str) -> bool:
    if not isinstance(volume_path, str):
        return False
    if not volume_path.startswith("/Volumes/"):
        return False
    if ".." in volume_path:
        return False
    if any(ch in volume_path for ch in (";", "`", "\n", "\r", "\x00")):
        return False
    # Single-file path expected (upload_to_volume writes a concrete file path)
    if volume_path.endswith("/"):
        return False
    return True


def sql_escape_literal(value: str) -> str:
    """Escape single quotes for embedding in SQL string literals."""
    return value.replace("'", "''")


def estimate_file_uses_sql_pipeline(filename: str, content_type: str) -> bool:
    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    if fn.endswith(".pdf"):
        return True
    if fn.endswith(".csv"):
        return True
    if ct == "application/pdf" or "pdf" in ct.split("/"):
        return True
    if "csv" in ct or ct in ("application/csv", "text/csv"):
        return True
    return False


def warehouse_configured() -> bool:
    return bool(WAREHOUSE_ID)


def _coerce_cost(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, Decimal):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.replace(",", "").strip().replace("$", "")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _map_ai_extract_variant_to_payload(variant_json: Optional[str]) -> Optional[dict]:
    if not variant_json or variant_json.strip().lower() in ("null", "none"):
        return None
    try:
        data = json.loads(variant_json)
    except json.JSONDecodeError:
        _logger.warning("Could not parse ai_extract JSON: %s…", variant_json[:200])
        return None
    if not isinstance(data, dict):
        return None

    invoice_id = data.get("invoice_id")
    vendor = data.get("vendor_name")
    cost = _coerce_cost(data.get("total_amount"))
    inv_date = data.get("invoice_date")
    date_str = None
    if inv_date is not None:
        date_str = str(inv_date).strip()[:32] or None

    summary_parts = []
    if invoice_id:
        summary_parts.append(f"Invoice / estimate ID: {invoice_id}")

    summary = ". ".join(summary_parts) if summary_parts else None

    return {
        "vendor": vendor if vendor else None,
        "cost": cost,
        "date": date_str,
        "fema_category": None,
        "summary": summary,
        "damage_description": None,
        "confidence": 80,
        "flags": None,
        "_extraction_source": "sql_ai_extract",
    }


def _build_pdf_extract_sql(volume_path_escaped: str, schema_sql: str) -> str:
    """Pattern: ai_extract(ai_parse_document('/Volumes/.../file.pdf'), '["invoice_id",...]')."""
    return f"""
SELECT to_json(
  ai_extract(
    ai_parse_document('{volume_path_escaped}'),
    '{schema_sql}'
  )
) AS extracted_json
""".strip()


def _build_csv_extract_sql(volume_path_escaped: str, schema_sql: str) -> str:
    """CSV: load as text, same four fields (ai_parse_document does not support CSV binaries)."""
    return f"""
SELECT to_json(
  ai_extract(
    CAST(content AS STRING),
    '{schema_sql}'
  )
) AS extracted_json
FROM read_files('{volume_path_escaped}', format => 'text')
""".strip()


def _poll_statement(statement_id: str, deadline: float):
    """Poll until terminal state or deadline."""
    while time.time() < deadline:
        resp = w.statement_execution.get_statement(statement_id)
        state = resp.status.state if resp.status else None
        if state == StatementState.SUCCEEDED:
            return resp
        if state in (
            StatementState.FAILED,
            StatementState.CANCELED,
            StatementState.CLOSED,
        ):
            return resp
        time.sleep(2)
    return w.statement_execution.get_statement(statement_id)


def _execute_extract_sql(statement: str) -> str:
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=WAREHOUSE_ID,
        wait_timeout="50s",
        format=Format.JSON_ARRAY,
        disposition=Disposition.INLINE,
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )

    deadline = time.time() + 300
    sid = resp.statement_id
    resp = _poll_statement(sid, deadline)

    if resp.status is None:
        raise RuntimeError("SQL statement execution: missing status")

    if resp.status.state != StatementState.SUCCEEDED:
        err = resp.status.error.as_dict() if resp.status.error else {}
        raise RuntimeError(f"SQL warehouse error: state={resp.status.state} detail={err}")

    if resp.result is None or not resp.result.data_array:
        raise RuntimeError("SQL statement returned no rows")

    row = resp.result.data_array[0]
    cell = row[0] if row else None
    return cell


def extract_estimate_via_sql(volume_path: str, filename: str, content_type: str) -> Optional[dict]:
    """Run ai_parse_document + ai_extract via serverless SQL; return None to fall back to LLM."""
    if not warehouse_configured():
        return None
    if not validate_uc_single_file_volume_path(volume_path):
        _logger.warning("Skipping SQL extraction: invalid volume path")
        return None

    escaped_path = sql_escape_literal(volume_path)
    schema_lit = sql_escape_literal(ESTIMATE_EXTRACT_SCHEMA)

    fn = (filename or "").lower()
    ct = (content_type or "").lower()
    try:
        if fn.endswith(".csv") or "csv" in ct:
            stmt = _build_csv_extract_sql(escaped_path, schema_lit)
        else:
            # PDF (and PDF-like content types without .pdf extension)
            stmt = _build_pdf_extract_sql(escaped_path, schema_lit)

        cell = _execute_extract_sql(stmt)
        mapped = _map_ai_extract_variant_to_payload(cell)
        return mapped
    except Exception as e:
        _logger.warning("Databricks SQL extraction failed (%s): %s", filename, e)
        return None
