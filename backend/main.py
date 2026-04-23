import sys
from pathlib import Path

# Allow `from config import …` when cwd is not `backend/` (e.g. uvicorn from project root).
_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

import os
import json
from datetime import datetime, date
from decimal import Decimal
from typing import Optional

import hashlib
import logging
import uuid

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from config import (
    ENDPOINT_NAME,
    MAX_IMAGE_UPLOAD_BYTES,
    PGDATABASE,
    PGHOST,
    PGPORT,
    PGSSLMODE,
    PGUSER,
)
from databricks_auth import w
from document_ai import (
    SQL_UPDATE_DOCUMENT_AI_FIELDS,
    SQL_UPDATE_DOCUMENT_AI_FIELDS_RETURNING,
    classify_fema_category_from_claim_fields,
    document_update_values_from_ai,
    extract_with_ai,
    form_description_from_ai_result,
    normalize_fema_category_code,
    raise_if_ai_processing_failed,
    read_upload_or_url_to_bytes,
    refine_description,
)
from volume_storage import (
    delete_volume_file,
    download_from_volume,
    is_valid_preview_staging_path,
    try_stage_new_claim_image,
    upload_claim_document_with_retry,
    upload_to_volume,
)

_logger = logging.getLogger("backend")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("INFO:     %(message)s"))
    _logger.addHandler(_handler)

CLAIM_VALID_STATUSES: frozenset[str] = frozenset(
    ("submitted", "under_review", "ai_processed", "approved", "rejected", "needs_info", "packaged")
)

# Volume / Files API: treat as "already gone" so we still remove the DB row.
_VOLUME_FILE_ABSENT_ERROR_MARKERS: frozenset[str] = frozenset(
    ("404", "not found", "does not exist", "resource_not_found")
)


def _volume_delete_error_is_absent(err: Exception) -> bool:
    err_l = str(err).lower()
    return any(m in err_l for m in _VOLUME_FILE_ABSENT_ERROR_MARKERS)


app = FastAPI(title="Disaster Recovery Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OAuthConnection(psycopg.Connection):
    """Connection subclass that fetches a fresh Lakebase OAuth credential on each connect."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        cred = w.postgres.generate_database_credential(endpoint=ENDPOINT_NAME)
        kwargs["password"] = cred.token
        return super().connect(conninfo, **kwargs)


def _build_conninfo() -> str:
    """Build the PostgreSQL connection string.

    On Databricks Apps the PGHOST/PGUSER env vars are auto-injected.
    Locally, derive them from the SDK endpoint metadata if not set.
    """
    host = PGHOST
    user = PGUSER
    if not host or not user:
        _logger.info("PGHOST/PGUSER not set — deriving from SDK endpoint metadata")
        ep = w.postgres.list_endpoints(parent=ENDPOINT_NAME.rsplit("/endpoints/", 1)[0])
        first = next(iter(ep))
        host = host or first.status.hosts.host
        if not user:
            me = w.current_user.me()
            user = me.user_name
    _logger.info("Connecting to Lakebase as user=%s host=%s db=%s", user, host, PGDATABASE)
    return f"dbname={PGDATABASE} user={user} host={host} port={PGPORT} sslmode={PGSSLMODE}"


_pool: ConnectionPool | None = None


def get_db_connection():
    """Get a context-managed connection from the pool (created on first call).

    Usage:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
            conn.commit()
    """
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=_build_conninfo(),
            connection_class=OAuthConnection,
            kwargs={"row_factory": dict_row, "autocommit": False},
            min_size=1,
            max_size=10,
            open=True,
        )
    return _pool.connection()


def _json_default(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


def _serialize(data):
    """Round-trip DB rows through JSON to handle dates/decimals."""
    return json.loads(json.dumps(data, default=_json_default))


# --- Health ---
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


def _identity_from_request_headers(request: Request) -> Optional[str]:
    """Return the caller's email/userName when Databricks Apps forwards identity; else None.

    Same resolution as ``/api/current-user`` for the Databricks paths, without the
    generated placeholder (used only for status history and similar auditing).
    """
    email = request.headers.get("x-forwarded-email")
    if email and email.strip():
        return email.strip()

    user_token = request.headers.get("x-forwarded-access-token")
    if user_token:
        try:
            resp = httpx.get(
                f"{w.config.host}/api/2.0/preview/scim/v2/Me",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            name = resp.json().get("userName")
            if name and str(name).strip():
                return str(name).strip()
        except Exception:
            pass
    return None


def _status_history_actor(request: Request, form_fallback: str = "") -> str:
    """Prefer authenticated platform user; otherwise use non-empty client-provided name."""
    ident = _identity_from_request_headers(request)
    if ident:
        return ident
    return (form_fallback or "").strip()


def _insert_claim_status_history(
    cur,
    claim_id: int,
    old_status: Optional[str],
    new_status: str,
    changed_by: str,
    notes: str,
) -> None:
    cur.execute(
        """
        INSERT INTO claim_status_history (claim_id, old_status, new_status, changed_by, notes)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (claim_id, old_status, new_status, changed_by, notes),
    )


@app.get("/api/current-user")
def current_user(request: Request):
    """Return the logged-in user's email.

    When running as a Databricks App the platform injects x-forwarded-access-token
    and x-forwarded-email headers. We prefer those over the CLI.
    """
    ident = _identity_from_request_headers(request)
    if ident:
        return {"email": ident, "source": "databricks"}

    tag = hashlib.md5(uuid.uuid4().bytes).hexdigest()[:8]
    return {"email": f"user_{tag}@county.local", "source": "generated"}


# --- FEMA Categories ---
@app.get("/api/categories")
def list_categories():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fema_categories ORDER BY code")
            rows = cur.fetchall()
        return _serialize(list(rows))


# --- Claims ---
@app.get("/api/claims")
def list_claims(status: Optional[str] = None, county: Optional[str] = None):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT c.*, fc.code as fema_code, fc.name as fema_category_name,
                       (SELECT COUNT(*) FROM documents d WHERE d.claim_id = c.id) as document_count
                FROM claims c
                LEFT JOIN fema_categories fc ON c.fema_category_id = fc.id
                WHERE 1=1
            """
            params = []
            if status:
                query += " AND c.status = %s"
                params.append(status)
            if county:
                query += " AND c.county ILIKE %s"
                params.append(f"%{county}%")
            query += " ORDER BY c.submitted_at DESC"
            cur.execute(query, params)
            rows = cur.fetchall()
        return _serialize(list(rows))


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.*, fc.code as fema_code, fc.name as fema_category_name
                FROM claims c
                LEFT JOIN fema_categories fc ON c.fema_category_id = fc.id
                WHERE c.id = %s
            """, (claim_id,))
            claim = cur.fetchone()
            if not claim:
                raise HTTPException(status_code=404, detail="Claim not found")

            cur.execute("SELECT * FROM documents WHERE claim_id = %s ORDER BY uploaded_at DESC", (claim_id,))
            documents = cur.fetchall()

            cur.execute("SELECT * FROM claim_status_history WHERE claim_id = %s ORDER BY changed_at DESC", (claim_id,))
            history = cur.fetchall()

        result = dict(claim)
        result["documents"] = list(documents)
        result["status_history"] = list(history)
        return _serialize(result)


@app.post("/api/claims")
def create_claim(
    request: Request,
    incident_name: str = Form(...),
    county: str = Form(...),
    applicant_name: str = Form(...),
    description: str = Form(""),
    estimated_cost: float = Form(0),
    submitted_by: str = Form(""),
    fema_category_id: Optional[int] = Form(None),
    preview_storage_path: Optional[str] = Form(None),
):
    ps = (preview_storage_path or "").strip()
    staged_content: Optional[bytes] = None
    staged_type: Optional[str] = None
    staged_base_name: Optional[str] = None
    if ps:
        if not is_valid_preview_staging_path(ps):
            raise HTTPException(status_code=400, detail="Invalid preview_storage_path")
        try:
            staged_content, staged_type = download_from_volume(ps)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not read staged damage image: {e}") from e
        staged_base_name = os.path.basename(ps.rstrip("/")) or "damage_image"

    user_chose_category = fema_category_id is not None
    staged_ai_result: Optional[dict] = None
    text_ai_result: Optional[dict] = None

    if not user_chose_category:
        if staged_content is not None and staged_base_name is not None:
            staged_ai_result = extract_with_ai(
                staged_content,
                staged_base_name,
                staged_type or "application/octet-stream",
            )
        elif (description or "").strip():
            text_ai_result = classify_fema_category_from_claim_fields(
                incident_name, county, applicant_name, description, estimated_cost
            )

    ai_for_claim: Optional[dict] = staged_ai_result or text_ai_result
    ai_code_raw = (ai_for_claim or {}).get("fema_category")
    ai_confidence = (ai_for_claim or {}).get("confidence")
    ai_flags = (ai_for_claim or {}).get("flags")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            resolved_fema_id = fema_category_id
            if resolved_fema_id is None:
                code = normalize_fema_category_code(ai_code_raw)
                if code:
                    cur.execute("SELECT id FROM fema_categories WHERE code = %s", (code,))
                    row = cur.fetchone()
                    if row:
                        resolved_fema_id = row["id"]

            ai_ran = staged_ai_result is not None or text_ai_result is not None
            if resolved_fema_id is not None and not user_chose_category and ai_ran:
                claim_status = "ai_processed"
            else:
                claim_status = "submitted"

            cur.execute("""
                INSERT INTO claims (incident_name, county, applicant_name, description,
                                    estimated_cost, submitted_by, fema_category_id, status,
                                    ai_confidence_score, ai_flags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
            """, (
                incident_name,
                county,
                applicant_name,
                description,
                estimated_cost,
                submitted_by,
                resolved_fema_id,
                claim_status,
                ai_confidence if ai_ran else None,
                ai_flags if ai_ran else None,
            ))
            claim = cur.fetchone()
            claim_id = claim["id"]

            hist_note = "Claim created"
            if resolved_fema_id is not None and not user_chose_category and ai_ran:
                hist_note = "Claim created; FEMA category assigned by AI"
            actor = _status_history_actor(request, submitted_by)
            _insert_claim_status_history(cur, claim_id, None, claim_status, actor, hist_note)

            if staged_content is not None and staged_base_name is not None:
                file_size = len(staged_content)
                try:
                    final_storage = upload_to_volume(staged_content, claim_id, staged_base_name)
                except Exception as e:
                    conn.rollback()
                    raise HTTPException(status_code=500, detail=f"Failed to save image to claim folder: {e}") from e
                cur.execute("""
                    INSERT INTO documents (claim_id, file_name, file_type, file_size, storage_path, processing_status)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    claim_id,
                    staged_base_name,
                    staged_type or "application/octet-stream",
                    file_size,
                    final_storage,
                    "completed",
                ))
                doc_row = cur.fetchone()
                doc_id = doc_row["id"]

                if staged_ai_result:
                    cur.execute(
                        SQL_UPDATE_DOCUMENT_AI_FIELDS,
                        (*document_update_values_from_ai(staged_ai_result), doc_id),
                    )

            conn.commit()
        return _serialize(dict(claim))


@app.patch("/api/claims/{claim_id}/status")
def update_claim_status(
    request: Request,
    claim_id: int,
    status: str = Form(...),
    changed_by: str = Form(""),
    notes: str = Form(""),
    approved_amount: Optional[str] = Form(None),
):
    if status not in CLAIM_VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(CLAIM_VALID_STATUSES)}",
        )

    approved_amt: Optional[float] = None
    if status == "approved":
        if approved_amount is None or str(approved_amount).strip() == "":
            raise HTTPException(status_code=400, detail="approved_amount is required when status is approved")
        try:
            approved_amt = float(approved_amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="approved_amount must be a valid number")
        if approved_amt < 0:
            raise HTTPException(status_code=400, detail="approved_amount must be zero or greater")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT status FROM claims WHERE id = %s", (claim_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Claim not found")
            old_status = row["status"]

            if status == "approved":
                cur.execute("""
                    UPDATE claims SET status = %s, approved_amount = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s RETURNING *
                """, (status, approved_amt, claim_id))
            else:
                cur.execute("""
                    UPDATE claims SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING *
                """, (status, claim_id))
            claim = cur.fetchone()

            actor = _status_history_actor(request, changed_by)
            _insert_claim_status_history(cur, claim_id, old_status, status, actor, notes)
            conn.commit()
        return _serialize(dict(claim))


# --- Document Upload & AI Processing ---

def _insert_and_process_document(
    claim_id: int,
    content: bytes,
    file_name: str,
    content_type: str,
    changed_by: str = "",
) -> dict:
    """Insert a document record, upload to Volume, run AI extraction, update claim."""
    file_size = len(content)

    storage_path, volume_upload_error = upload_claim_document_with_retry(
        content, claim_id, file_name
    )
    if storage_path is None:
        _logger.error(
            "Unity Catalog volume upload failed for claim %s/%s after retries: %s",
            claim_id,
            file_name,
            volume_upload_error,
        )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM claims WHERE id = %s", (claim_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Claim not found")

            cur.execute("""
                INSERT INTO documents (claim_id, file_name, file_type, file_size, storage_path, processing_status)
                VALUES (%s, %s, %s, %s, %s, 'processing')
                RETURNING *
            """, (claim_id, file_name, content_type, file_size, storage_path))
            doc = cur.fetchone()
            doc_id = doc["id"]
            conn.commit()

    # AI extraction (outside connection context — can be slow)
    ai_result = extract_with_ai(
        content,
        file_name,
        content_type,
        volume_path=storage_path,
        volume_upload_error=volume_upload_error,
    )

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                SQL_UPDATE_DOCUMENT_AI_FIELDS_RETURNING,
                (*document_update_values_from_ai(ai_result), doc_id),
            )
            updated_doc = cur.fetchone()

            # Update claim with AI suggestions if available
            code = ai_result.get("fema_category")
            if code:
                cur.execute("SELECT id FROM fema_categories WHERE code = %s", (code,))
                cat = cur.fetchone()
                if cat:
                    cur.execute("""
                        UPDATE claims SET
                            fema_category_id = COALESCE(fema_category_id, %s),
                            ai_confidence_score = %s,
                            ai_flags = %s,
                            status = CASE WHEN status = 'submitted' THEN 'ai_processed' ELSE status END,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """, (cat["id"], ai_result.get("confidence", 0), ai_result.get("flags"), claim_id))

            # Estimate documents: merge extracted total into claim cost when unset
            extracted_cost = ai_result.get("cost")
            if extracted_cost is not None:
                cur.execute("""
                    UPDATE claims SET estimated_cost = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND (estimated_cost IS NULL OR estimated_cost = 0)
                """, (extracted_cost, claim_id))

            cur.execute("SELECT status FROM claims WHERE id = %s", (claim_id,))
            status_after = cur.fetchone()
            claim_status_now = status_after["status"] if status_after else "submitted"
            _insert_claim_status_history(
                cur,
                claim_id,
                None,
                claim_status_now,
                changed_by,
                f"Document uploaded: {file_name}",
            )

            conn.commit()
        return _serialize(dict(updated_doc))


@app.post("/api/claims/{claim_id}/documents")
async def upload_document(claim_id: int, request: Request, file: UploadFile = File(...)):
    content = await file.read()
    actor = _status_history_actor(request)
    return _insert_and_process_document(claim_id, content, file.filename, file.content_type, changed_by=actor)


@app.post("/api/preview/damage-description")
async def preview_damage_description(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    """Run AI on an uploaded image or image URL and return text for the claim description (no claim required)."""
    content, file_name, content_type = await read_upload_or_url_to_bytes(
        file, url, max_bytes=MAX_IMAGE_UPLOAD_BYTES
    )

    result = extract_with_ai(content, file_name, content_type)
    raise_if_ai_processing_failed(result)

    # Stage to volume only after successful AI (avoids orphan files under new_claim_preview/ on 502)
    preview_storage_path = try_stage_new_claim_image(content, file_name)

    out = {"description": form_description_from_ai_result(result)}
    if preview_storage_path:
        out["preview_storage_path"] = preview_storage_path
    return out


@app.post("/api/refine-description")
def refine_claim_description(description: str = Form(...)):
    """Use AI to clean and clarify a user-written damage description."""
    stripped = description.strip()
    if not stripped:
        raise HTTPException(status_code=400, detail="Description is empty")
    try:
        refined = refine_description(stripped)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI refinement failed: {e}")
    return {"original": stripped, "refined": refined}


@app.post("/api/claims/{claim_id}/documents/url")
async def upload_document_from_url(claim_id: int, request: Request, url: str = Form(...)):
    """Fetch an image or document from a URL and process it with AI."""
    content, file_name, content_type = await read_upload_or_url_to_bytes(
        None, url, max_bytes=MAX_IMAGE_UPLOAD_BYTES
    )
    actor = _status_history_actor(request)
    return _insert_and_process_document(claim_id, content, file_name, content_type, changed_by=actor)


@app.get("/api/claims/{claim_id}/documents")
def list_documents(claim_id: int):
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM documents WHERE claim_id = %s ORDER BY uploaded_at DESC", (claim_id,))
            rows = cur.fetchall()
        return _serialize(list(rows))


@app.delete("/api/claims/{claim_id}/documents/{doc_id}")
def delete_claim_document(claim_id: int, doc_id: int, request: Request):
    """Remove document row and delete the file from the UC Volume when ``storage_path`` is set."""
    storage_path: Optional[str] = None
    deleted_file_name: Optional[str] = None
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, storage_path, file_name FROM documents WHERE id = %s AND claim_id = %s",
                (doc_id, claim_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found")
            storage_path = row["storage_path"]
            deleted_file_name = row["file_name"]

    if storage_path:
        try:
            delete_volume_file(storage_path)
        except Exception as e:
            if _volume_delete_error_is_absent(e):
                _logger.warning(
                    "Volume file already absent (continuing to remove DB row): %s — %s",
                    storage_path,
                    e,
                )
            else:
                _logger.error("Could not delete volume object %s: %s", storage_path, e)
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not delete file from Unity Catalog volume: {e}",
                ) from e

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE id = %s AND claim_id = %s RETURNING id",
                (doc_id, claim_id),
            )
            deleted = cur.fetchone()
            if not deleted:
                raise HTTPException(status_code=404, detail="Document not found")

            cur.execute("SELECT status FROM claims WHERE id = %s", (claim_id,))
            status_row = cur.fetchone()
            claim_status_now = status_row["status"] if status_row else "submitted"
            note = (
                f"Document deleted: {deleted_file_name}"
                if deleted_file_name
                else "Document deleted"
            )
            actor = _status_history_actor(request)
            _insert_claim_status_history(cur, claim_id, None, claim_status_now, actor, note)

            conn.commit()

    return Response(status_code=204)


@app.get("/api/documents/{doc_id}/file")
def view_document_file(doc_id: int):
    """Download/view the original uploaded file from the UC Volume."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_path, file_name, file_type FROM documents WHERE id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            if not doc["storage_path"]:
                raise HTTPException(status_code=404, detail="File not stored in volume")

    content, content_type = download_from_volume(doc["storage_path"])
    # Use stored content_type if volume didn't return a useful one
    if content_type == "application/octet-stream" and doc["file_type"]:
        content_type = doc["file_type"]

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{doc["file_name"]}"'},
    )


# --- Dashboard Stats ---
@app.get("/api/dashboard/stats")
def dashboard_stats():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM claims")
            total = cur.fetchone()["total"]

            cur.execute("SELECT status, COUNT(*) as count FROM claims GROUP BY status")
            by_status = {row["status"]: row["count"] for row in cur.fetchall()}

            cur.execute("SELECT COALESCE(SUM(estimated_cost), 0) as total FROM claims")
            total_estimated = cur.fetchone()["total"]

            cur.execute("""
                SELECT COALESCE(SUM(COALESCE(approved_amount, estimated_cost, 0)), 0) as total
                FROM claims WHERE status = 'approved'
            """)
            total_approved = cur.fetchone()["total"]

            cur.execute("""
                SELECT fc.code, fc.name, COUNT(c.id) as count, COALESCE(SUM(c.estimated_cost), 0) as total_cost
                FROM fema_categories fc
                LEFT JOIN claims c ON c.fema_category_id = fc.id
                GROUP BY fc.code, fc.name ORDER BY fc.code
            """)
            by_category = list(cur.fetchall())

            cur.execute("""
                SELECT county, COUNT(*) as count, COALESCE(SUM(estimated_cost), 0) as total_cost
                FROM claims GROUP BY county ORDER BY count DESC LIMIT 10
            """)
            by_county = list(cur.fetchall())

        return _serialize({
            "total_claims": total,
            "by_status": by_status,
            "total_estimated_cost": total_estimated,
            "total_approved_amount": total_approved,
            "by_category": by_category,
            "by_county": by_county,
        })


# --- Serve React Frontend ---
# Search multiple candidate locations for the React build output.
# - "frontend/build" relative to project root (local dev, Databricks Apps deploy)
# - "frontend/build" relative to CWD (if uvicorn is launched from project root)
# - "static" relative to project root (Docker image)
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = None
for candidate in [
    os.path.join(_project_root, "frontend", "build"),
    os.path.join(os.getcwd(), "frontend", "build"),
    os.path.join(_project_root, "static"),
    os.path.join(os.getcwd(), "static"),
]:
    if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, "index.html")):
        STATIC_DIR = candidate
        break

if STATIC_DIR:
    _logger.info(f"Serving React frontend from {STATIC_DIR}")
    _static_assets = os.path.join(STATIC_DIR, "static")
    if os.path.isdir(_static_assets):
        app.mount("/static", StaticFiles(directory=_static_assets), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Serve React app for all non-API routes."""
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
else:
    _logger.warning(
        "No React build found — frontend will not be served. "
        "Run 'npm run build' in frontend/ or ensure frontend/build/ is deployed."
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
