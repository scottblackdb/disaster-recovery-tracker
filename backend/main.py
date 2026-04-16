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

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import psycopg
from psycopg.rows import dict_row

import logging

from config import (
    BRANCH_ID,
    DATABASE_NAME,
    ENDPOINT_ID,
    LAKEBASE_HOST,
    LAKEBASE_PASSWORD,
    LAKEBASE_USER,
    MAX_IMAGE_UPLOAD_BYTES,
    PROJECT_ID,
)
from databricks_auth import cli_json

_logger = logging.getLogger(__name__)
from document_ai import (
    document_update_values_from_ai,
    extract_with_ai,
    fetch_url_bytes,
    form_description_from_ai_result,
    raise_if_ai_processing_failed,
    read_upload_or_url_to_bytes,
    refine_description,
)
from volume_storage import (
    download_from_volume,
    is_valid_preview_staging_path,
    try_stage_new_claim_image,
    upload_to_volume,
)

app = FastAPI(title="Disaster Recovery Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_connection():
    """Get a psycopg connection to Lakebase.

    Prefers the Databricks CLI for dynamic OAuth credentials.
    Falls back to LAKEBASE_HOST / LAKEBASE_USER / LAKEBASE_PASSWORD env vars.
    """
    host = user = password = None

    try:
        endpoints = cli_json([
            "postgres", "list-endpoints",
            f"projects/{PROJECT_ID}/branches/{BRANCH_ID}"
        ])
        host = endpoints[0]["status"]["hosts"]["host"]

        cred = cli_json([
            "postgres", "generate-database-credential",
            f"projects/{PROJECT_ID}/branches/{BRANCH_ID}/endpoints/{ENDPOINT_ID}"
        ])
        password = cred["token"]

        user_info = cli_json(["current-user", "me"])
        user = user_info["userName"]
    except RuntimeError:
        _logger.warning("CLI unavailable for DB connection, falling back to env vars")

    host = host or LAKEBASE_HOST
    user = user or LAKEBASE_USER
    password = password or LAKEBASE_PASSWORD

    if not all([host, user, password]):
        raise RuntimeError(
            "No database credentials available. Either install/authenticate the Databricks CLI "
            "or set LAKEBASE_HOST, LAKEBASE_USER, and LAKEBASE_PASSWORD environment variables."
        )

    return psycopg.connect(
        host=host, port=5432, dbname=DATABASE_NAME,
        user=user, password=password, sslmode="require",
        row_factory=dict_row, autocommit=False
    )


def json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")


# --- Health ---
@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/api/current-user")
def current_user(request: Request):
    """Return the logged-in user's email.

    When running as a Databricks App the platform injects x-forwarded-access-token
    and x-forwarded-email headers. We prefer those over the CLI.
    """
    # 1. Databricks Apps: check forwarded headers
    email = request.headers.get("x-forwarded-email")
    if email:
        return {"email": email, "source": "databricks"}

    # 2. Databricks Apps: use the forwarded access token to look up the user
    user_token = request.headers.get("x-forwarded-access-token")
    if user_token:
        import httpx
        from config import DATABRICKS_HOST
        try:
            resp = httpx.get(
                f"{DATABRICKS_HOST}/api/2.0/preview/scim/v2/Me",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=10,
            )
            resp.raise_for_status()
            return {"email": resp.json().get("userName", "unknown"), "source": "databricks"}
        except Exception:
            pass

    # 3. Fallback: generate a random placeholder
    import hashlib, uuid
    tag = hashlib.md5(uuid.uuid4().bytes).hexdigest()[:8]
    return {"email": f"user_{tag}@county.local", "source": "generated"}


# --- FEMA Categories ---
@app.get("/api/categories")
def list_categories():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM fema_categories ORDER BY code")
            rows = cur.fetchall()
        return json.loads(json.dumps(list(rows), default=json_serial))
    finally:
        conn.close()


# --- Claims ---
@app.get("/api/claims")
def list_claims(status: Optional[str] = None, county: Optional[str] = None):
    conn = get_db_connection()
    try:
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
        return json.loads(json.dumps(list(rows), default=json_serial))
    finally:
        conn.close()


@app.get("/api/claims/{claim_id}")
def get_claim(claim_id: int):
    conn = get_db_connection()
    try:
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
        return json.loads(json.dumps(result, default=json_serial))
    finally:
        conn.close()


@app.post("/api/claims")
def create_claim(
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

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO claims (incident_name, county, applicant_name, description,
                                    estimated_cost, submitted_by, fema_category_id, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'submitted')
                RETURNING *
            """, (incident_name, county, applicant_name, description,
                  estimated_cost, submitted_by, fema_category_id))
            claim = cur.fetchone()
            claim_id = claim["id"]

            cur.execute("""
                INSERT INTO claim_status_history (claim_id, old_status, new_status, changed_by, notes)
                VALUES (%s, NULL, 'submitted', %s, 'Claim created')
            """, (claim_id, submitted_by))

            if staged_content is not None and staged_base_name is not None:
                file_size = len(staged_content)
                try:
                    final_storage = upload_to_volume(staged_content, claim_id, staged_base_name)
                except Exception as e:
                    conn.rollback()
                    raise HTTPException(status_code=500, detail=f"Failed to save image to claim folder: {e}") from e
                cur.execute("""
                    INSERT INTO documents (claim_id, file_name, file_type, file_size, storage_path, processing_status)
                    VALUES (%s, %s, %s, %s, %s, 'completed')
                """, (
                    claim_id,
                    staged_base_name,
                    staged_type or "application/octet-stream",
                    file_size,
                    final_storage,
                ))

            conn.commit()
        return json.loads(json.dumps(dict(claim), default=json_serial))
    finally:
        conn.close()


@app.patch("/api/claims/{claim_id}/status")
def update_claim_status(
    claim_id: int,
    status: str = Form(...),
    changed_by: str = Form(""),
    notes: str = Form(""),
    approved_amount: Optional[str] = Form(None),
):
    valid_statuses = ["submitted", "under_review", "ai_processed", "approved", "rejected", "needs_info", "packaged"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")

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

    conn = get_db_connection()
    try:
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

            cur.execute("""
                INSERT INTO claim_status_history (claim_id, old_status, new_status, changed_by, notes)
                VALUES (%s, %s, %s, %s, %s)
            """, (claim_id, old_status, status, changed_by, notes))
            conn.commit()
        return json.loads(json.dumps(dict(claim), default=json_serial))
    finally:
        conn.close()


# --- Document Upload & AI Processing ---

def _insert_and_process_document(claim_id: int, content: bytes, file_name: str, content_type: str) -> dict:
    """Insert a document record, upload to Volume, run AI extraction, update claim."""
    file_size = len(content)

    # Upload file to UC Volume
    try:
        storage_path = upload_to_volume(content, claim_id, file_name)
    except Exception as e:
        import logging
        logging.warning(f"Volume upload failed for claim {claim_id}/{file_name}: {e}")
        storage_path = None  # non-fatal; continue with AI processing

    conn = get_db_connection()
    try:
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

        # AI extraction
        ai_result = extract_with_ai(content, file_name, content_type)

        conn2 = get_db_connection()
        try:
            with conn2.cursor() as cur:
                cur.execute("""
                    UPDATE documents SET
                        ai_extracted_vendor = %s,
                        ai_extracted_cost = %s,
                        ai_extracted_date = %s,
                        ai_extracted_category = %s,
                        ai_summary = %s,
                        ai_damage_description = %s,
                        processing_status = 'completed'
                    WHERE id = %s RETURNING *
                """, (*document_update_values_from_ai(ai_result), doc_id))
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

                conn2.commit()
            return json.loads(json.dumps(dict(updated_doc), default=json_serial))
        finally:
            conn2.close()
    finally:
        conn.close()


@app.post("/api/claims/{claim_id}/documents")
async def upload_document(claim_id: int, file: UploadFile = File(...)):
    content = await file.read()
    return _insert_and_process_document(claim_id, content, file.filename, file.content_type)


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
async def upload_document_from_url(claim_id: int, url: str = Form(...)):
    """Fetch an image or document from a URL and process it with AI."""
    content, file_name, content_type = await fetch_url_bytes(url)
    return _insert_and_process_document(claim_id, content, file_name, content_type)


@app.get("/api/claims/{claim_id}/documents")
def list_documents(claim_id: int):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM documents WHERE claim_id = %s ORDER BY uploaded_at DESC", (claim_id,))
            rows = cur.fetchall()
        return json.loads(json.dumps(list(rows), default=json_serial))
    finally:
        conn.close()


@app.get("/api/documents/{doc_id}/file")
def view_document_file(doc_id: int):
    """Download/view the original uploaded file from the UC Volume."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_path, file_name, file_type FROM documents WHERE id = %s", (doc_id,))
            doc = cur.fetchone()
            if not doc:
                raise HTTPException(status_code=404, detail="Document not found")
            if not doc["storage_path"]:
                raise HTTPException(status_code=404, detail="File not stored in volume")
    finally:
        conn.close()

    content, content_type = download_from_volume(doc["storage_path"])
    # Use stored content_type if volume didn't return a useful one
    if content_type == "application/octet-stream" and doc["file_type"]:
        content_type = doc["file_type"]

    from fastapi.responses import Response
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{doc["file_name"]}"'},
    )


# --- Dashboard Stats ---
@app.get("/api/dashboard/stats")
def dashboard_stats():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as total FROM claims")
            total = cur.fetchone()["total"]

            cur.execute("SELECT status, COUNT(*) as count FROM claims GROUP BY status")
            by_status = {row["status"]: row["count"] for row in cur.fetchall()}

            cur.execute("SELECT COALESCE(SUM(estimated_cost), 0) as total FROM claims")
            total_estimated = cur.fetchone()["total"]

            # approved_amount is often unset when status is moved to approved in the UI; fall back to estimated_cost
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

        return json.loads(json.dumps({
            "total_claims": total,
            "by_status": by_status,
            "total_estimated_cost": total_estimated,
            "total_approved_amount": total_approved,
            "by_category": by_category,
            "by_county": by_county,
        }, default=json_serial))
    finally:
        conn.close()


# --- Serve React Frontend ---
# Check both "frontend/build" (local dev) and "static" (Docker)
_project_root = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = None
for candidate in [os.path.join(_project_root, "frontend", "build"),
                  os.path.join(_project_root, "static")]:
    if os.path.isdir(candidate):
        STATIC_DIR = candidate
        break

if STATIC_DIR:
    app.mount("/static", StaticFiles(directory=os.path.join(STATIC_DIR, "static")), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Serve React app for all non-API routes."""
        file_path = os.path.join(STATIC_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
