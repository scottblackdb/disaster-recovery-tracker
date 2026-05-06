"""Load bootstrap.sql when the Lakebase schema has not been created yet."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

REQUIRED_TABLES: frozenset[str] = frozenset(
    ("claims", "fema_categories", "documents", "claim_status_history")
)

_STATEMENT_SPLIT = re.compile(r"^\s*--\s*statement-break\s*$", re.MULTILINE)


def _bootstrap_path() -> Path:
    return Path(__file__).resolve().parent / "bootstrap.sql"


def _schema_ready(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(REQUIRED_TABLES),),
        )
        found = {row["table_name"] for row in cur.fetchall()}
    return REQUIRED_TABLES <= found


def _executable_sql_chunks(sql_text: str) -> list[str]:
    parts = _STATEMENT_SPLIT.split(sql_text)
    out: list[str] = []
    for part in parts:
        stmt = part.strip()
        if not stmt:
            continue
        # Skip segments that are only comments / blank lines
        if not any(
            line.strip() and not line.strip().startswith("--")
            for line in stmt.splitlines()
        ):
            continue
        out.append(stmt)
    return out


def ensure_database_schema(
    *,
    conninfo: str,
    password: str,
    logger: logging.Logger,
) -> None:
    """Create tables and seed FEMA categories when any required table is missing.

    Use the same Lakebase OAuth token as ``password`` that the app uses for
    :class:`OAuthConnection` (pass ``cred.token`` from
    ``w.postgres.generate_database_credential``). A plain connection avoids passing
    ``connection_class`` through libpq, which rejects it as an unknown option in some runtimes.
    """
    bootstrap_file = _bootstrap_path()
    if not bootstrap_file.is_file():
        logger.error("bootstrap.sql not found at %s — cannot initialize schema", bootstrap_file)
        raise FileNotFoundError(bootstrap_file)

    sql_text = bootstrap_file.read_text(encoding="utf-8")
    statements = _executable_sql_chunks(sql_text)
    if not statements:
        logger.error("bootstrap.sql contains no executable statements")
        raise RuntimeError("empty bootstrap.sql")

    with psycopg.connect(
        conninfo,
        password=password,
        row_factory=dict_row,
        autocommit=False,
    ) as conn:
        if _schema_ready(conn):
            return

        logger.info("Database schema incomplete — applying bootstrap.sql")
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        logger.info("bootstrap.sql applied successfully")
