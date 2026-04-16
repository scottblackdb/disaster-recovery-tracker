"""LLM extraction for documents/images and shared helpers for uploads + preview."""
import base64
import json
import mimetypes
import os
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile
from openai import OpenAI

from config import DATABRICKS_HOST, LLM_ENDPOINT, REFINE_LLM_ENDPOINT, MAX_IMAGE_UPLOAD_BYTES
from databricks_auth import get_auth_token


def get_llm_client() -> OpenAI:
    token = get_auth_token()
    return OpenAI(api_key=token, base_url=f"{DATABRICKS_HOST}/serving-endpoints")


def _normalize_llm_text_content(raw_content: Any) -> str:
    if raw_content is None:
        return ""
    if isinstance(raw_content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        ).strip()
    if isinstance(raw_content, str):
        return raw_content.strip()
    return str(raw_content).strip()


def _ai_failure_payload(exc: Exception) -> dict:
    return {
        "vendor": None,
        "cost": None,
        "date": None,
        "fema_category": None,
        "summary": f"AI processing failed: {str(exc)}",
        "damage_description": None,
        "confidence": 0,
        "flags": f"AI extraction error: {str(exc)}",
    }


def extract_with_ai(content: bytes, filename: str, content_type: str) -> dict:
    """Run FEMA PA document analyzer on bytes (image or text-like document)."""
    try:
        client = get_llm_client()
        is_image = content_type and content_type.startswith("image/")
        if is_image:
            b64 = base64.b64encode(content).decode("utf-8")
            user_content: Any = [
                {
                    "type": "text",
                    "text": (
                        f"Analyze this uploaded image (filename: {filename}). "
                        "Extract the following information from this contractor estimate, invoice, or damage report:"
                    ),
                },
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}},
            ]
        else:
            try:
                text_content = content.decode("utf-8", errors="replace")[:8000]
            except Exception:
                text_content = f"[Binary file: {filename}, size: {len(content)} bytes]"
            user_content = f"""Analyze this uploaded document (filename: {filename}).
Document content:
---
{text_content}
---

Extract the following information from this contractor estimate, invoice, or damage report:"""

        response = client.chat.completions.create(
            model=LLM_ENDPOINT,
            messages=[
                {
                    "role": "system",
                    "content": """You are a FEMA Public Assistance document analyzer. Extract structured data from contractor estimates, invoices, and damage reports.

Return a JSON object with these fields:
- vendor: the contractor/vendor name (null if not applicable, e.g. for photos)
- cost: the total dollar amount as a number (no $ sign, null if not applicable)
- date: the document date in YYYY-MM-DD format (null if unknown)
- fema_category: the FEMA PA category code (A=Debris Removal, B=Emergency Protective Measures, C=Roads/Bridges, D=Water Control, E=Public Buildings, F=Public Utilities, G=Parks/Recreation, H=Residential, I=Commercial)
- summary: a 1-2 sentence summary of the work described or what the document shows
- damage_description: For images/photos ONLY, describe strictly the visible damage — what is damaged, the type and extent of damage, and any observable hazards (e.g. "Large oak tree fallen through roof of single-story home, collapsing the northwest corner. Roof trusses fractured, interior water intrusion visible through the opening."). Focus only on the damage itself, not the surroundings or undamaged areas. For text documents, set to null — use the summary field instead.
- confidence: confidence score 0-100 for the category assignment
- flags: any missing information or concerns (null if none)

Return ONLY valid JSON, no markdown.""",
                },
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=800,
        )

        raw_content = response.choices[0].message.content
        result_text = _normalize_llm_text_content(raw_content)
        if result_text.startswith("```"):
            result_text = result_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(result_text)
    except Exception as e:
        return _ai_failure_payload(e)


def document_update_values_from_ai(ai_result: dict) -> tuple:
    """Column values for UPDATE documents SET ... from extract_with_ai output."""
    return (
        ai_result.get("vendor"),
        ai_result.get("cost"),
        ai_result.get("date"),
        ai_result.get("fema_category"),
        ai_result.get("summary"),
        ai_result.get("damage_description"),
    )


def form_description_from_ai_result(ai_result: dict) -> str:
    """Prefer damage narrative for photos; otherwise summary (e.g. new-claim description field)."""
    damage = ai_result.get("damage_description")
    if isinstance(damage, str) and damage.strip():
        return damage.strip()
    summ = ai_result.get("summary")
    return (summ or "").strip() if isinstance(summ, str) else ""


def raise_if_ai_processing_failed(ai_result: dict) -> None:
    summary = ai_result.get("summary") or ""
    if isinstance(summary, str) and summary.startswith("AI processing failed"):
        raise HTTPException(status_code=502, detail=summary)


async def fetch_url_bytes(url: str) -> tuple[bytes, str, str]:
    """Download URL → (content, file_name, content_type)."""
    import httpx

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="URL must start with http:// or https://")

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: HTTP {e.response.status_code}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch URL: {e}")

    content = resp.content
    content_type = resp.headers.get("content-type", "").split(";")[0].strip()

    path = parsed.path.rstrip("/")
    file_name = os.path.basename(path) if path else "document"
    if not file_name or file_name == "/":
        file_name = "document"
    if "." not in file_name and content_type:
        ext = mimetypes.guess_extension(content_type) or ""
        file_name += ext

    return content, file_name, content_type


async def read_upload_or_url_to_bytes(
    file: Optional[UploadFile],
    url: Optional[str],
    *,
    max_bytes: int = MAX_IMAGE_UPLOAD_BYTES,
) -> tuple[bytes, str, str]:
    """Exactly one of file or url; returns content, file_name, content_type."""
    has_file = file is not None and file.filename
    url_clean = (url or "").strip()
    has_url = bool(url_clean)

    if has_file == has_url:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of: an image file or an image URL.",
        )

    if has_file:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file upload")
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=400,
                detail=f"File too large (max {max_bytes // (1024 * 1024)}MB)",
            )
        file_name = file.filename or "upload"
        content_type = file.content_type or "application/octet-stream"
        return content, file_name, content_type

    content, file_name, content_type = await fetch_url_bytes(url_clean)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {max_bytes // (1024 * 1024)}MB)",
        )
    return content, file_name, content_type


def refine_description(raw_description: str) -> str:
    """Use databricks-gpt-oss-120b to clean and clarify a damage description."""
    token = get_auth_token()
    client = OpenAI(api_key=token, base_url=f"{DATABRICKS_HOST}/serving-endpoints")

    response = client.chat.completions.create(
        model=REFINE_LLM_ENDPOINT,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a professional technical writer for FEMA Public Assistance grant applications. "
                    "Rewrite the user's description to focus strictly on the damage itself: what is damaged, "
                    "the type and extent of the damage, and the current condition of the affected structures or infrastructure. "
                    "Remove any details about how the damage happened (e.g. wind speed, storm name, sequence of events) "
                    "and any information not directly relevant to describing the damage (e.g. personal anecdotes, opinions, "
                    "background context). Fix grammar, spelling, and punctuation. Use precise, professional language "
                    "suitable for an official government document. Do not add facts that were not in the original. "
                    "Return ONLY the rewritten description, nothing else."
                ),
            },
            {"role": "user", "content": raw_description},
        ],
        temperature=0.2,
        max_tokens=600,
    )

    raw = response.choices[0].message.content
    return _normalize_llm_text_content(raw)
