"""Document endpoints: upload + index PDFs, summarise, ask with page citations."""
from __future__ import annotations

import os
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import auth, config, db, tools
from ..ingest import IngestError, extract_pages
from ..vectorstore import store

router = APIRouter(prefix="/api/documents", tags=["documents"])


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _require_document(user: dict, document_id: int) -> dict:
    doc = db.get_document(user["id"], document_id)
    if doc is None:
        raise HTTPException(404, "Document not found.")
    return doc


def _safe_title(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(filename))[0]
    return re.sub(r"[_-]+", " ", stem).strip() or "Untitled document"


@router.post("/upload", status_code=201)
async def upload(file: UploadFile = File(...), user: dict = Depends(auth.get_current_user)):
    filename = os.path.basename(file.filename or "upload")
    ext = os.path.splitext(filename)[1].lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(422, "Only PDF, TXT and Markdown files are supported (.pdf, .txt, .md).")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File is too large (limit is {config.MAX_UPLOAD_MB:.0f} MB).")
    if not data:
        raise HTTPException(422, "That file is empty.")
    try:
        kind, pages = extract_pages(filename, data)
    except IngestError as exc:
        raise HTTPException(422, str(exc))

    char_count = sum(len(text) for _, text in pages)
    doc = db.create_document(user["id"], filename, _safe_title(filename), kind,
                               num_pages=len(pages), char_count=char_count)
    num_chunks = store.index_document(user["id"], doc["id"], pages)
    db.update_document_chunks(doc["id"], num_chunks)

    # Keep a copy of the original file next to the database for reference.
    try:
        config.ensure_dirs()
        (config.UPLOAD_DIR / f"{user['id']}_{doc['id']}_{filename}").write_bytes(data)
    except OSError:
        pass  # indexing already succeeded; storing the original is best-effort

    return db.get_document(user["id"], doc["id"])


@router.get("")
def list_documents(user: dict = Depends(auth.get_current_user)):
    return {"documents": db.list_documents(user["id"])}


@router.get("/{document_id}")
def get_document(document_id: int, user: dict = Depends(auth.get_current_user)):
    doc = _require_document(user, document_id)
    chunks = db.chunks_for_document(document_id)
    pages_seen = sorted({c["page"] for c in chunks if c["page"] is not None})
    return {**doc, "pages_with_text": pages_seen}


@router.delete("/{document_id}")
def delete_document(document_id: int, user: dict = Depends(auth.get_current_user)):
    _require_document(user, document_id)
    store.remove_document(user["id"], document_id)
    db.delete_document(user["id"], document_id)
    return {"deleted": True}


@router.post("/{document_id}/summarize")
def summarize(document_id: int, user: dict = Depends(auth.get_current_user)):
    doc = _require_document(user, document_id)
    summary = tools.summarize_document(user, doc)
    return {"document_id": document_id, "title": doc["title"], "summary": summary}


@router.post("/{document_id}/ask")
def ask(document_id: int, body: AskBody, user: dict = Depends(auth.get_current_user)):
    doc = _require_document(user, document_id)
    result = tools.answer_about_document(user, doc, body.question.strip())
    return {
        "document_id": document_id,
        "title": doc["title"],
        "answer": result.reply,
        "citations": result.citations,
        "tools_used": result.tools_used,
    }
