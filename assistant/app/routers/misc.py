"""Health, unified search, explainer, speech capability + demo-data endpoints."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from .. import auth, config, db, knowledge, llm
from ..vectorstore import store

router = APIRouter(prefix="/api", tags=["assistant"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "carebridge-assistant",
        "version": "1.0.0",
        "llm": llm.status(),
        "speech": speech_status_payload(),
    }


def speech_status_payload() -> dict:
    return {
        "browser_stt": "Web Speech API (SpeechRecognition) in the browser - free, no key needed (Chrome/Edge).",
        "browser_tts": "Web Speech API (speechSynthesis) in the browser - reads replies aloud.",
        "server_transcription": bool(config.LLM_API_KEY),
        "server_transcription_hint": None if config.LLM_API_KEY else
        "Set LLM_API_KEY to enable POST /api/speech/transcribe (Whisper-compatible endpoint).",
    }


@router.get("/stats")
def stats(user: dict = Depends(auth.get_current_user)):
    return db.stats(user["id"])


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=25)
    include: list[str] = Field(default=["document", "note"])


@router.post("/search")
def search(body: SearchBody, user: dict = Depends(auth.get_current_user)):
    kinds = tuple(k for k in body.include if k in ("document", "note")) or ("document", "note")
    hits = store.search(user["id"], body.query, top_k=body.top_k, source_types=kinds)
    return {"query": body.query, "results": [h.citation() for h in hits]}


class ExplainBody(BaseModel):
    concept: str = Field(min_length=1, max_length=200)
    level: str = Field(default="beginner", pattern="^(beginner|intermediate|advanced)$")


@router.post("/explain")
def explain(body: ExplainBody, user: dict = Depends(auth.get_current_user)):
    try:
        reply = llm.chat([
            {"role": "system", "content":
                f"You are a patient programming tutor teaching at {body.level} level. Explain in clear "
                "Markdown with a short code example and 2-3 common pitfalls. Under ~400 words."},
            {"role": "user", "content": f"Explain this programming concept: {body.concept}"},
        ], temperature=0.4)
        return {"concept": body.concept, "explanation": reply, "source": "llm"}
    except llm.LLMError:
        concept = knowledge.find_concept(body.concept)
        if concept:
            return {"concept": concept["title"], "explanation": concept["body"], "source": "knowledge-base"}
        topics = ", ".join(knowledge.concept_titles())
        raise HTTPException(
            404,
            f"“{body.concept}” isn't in the built-in knowledge base yet, and no LLM API key is configured. "
            f"Topics I can explain offline: {topics}. Or set LLM_API_KEY for any topic.",
        )


@router.get("/explain/topics")
def explain_topics(user: dict = Depends(auth.get_current_user)):
    return {"topics": knowledge.concept_titles(), "llm_enabled": config.llm_enabled()}


# --------------------------------------------------------------------- speech

@router.get("/speech/status")
def speech_status(user: dict = Depends(auth.get_current_user)):
    return speech_status_payload()


@router.post("/speech/transcribe")
async def transcribe(file: UploadFile = File(...), user: dict = Depends(auth.get_current_user)):
    """Server-side speech-to-text via a Whisper-compatible API (optional).

    The web UI normally uses the browser's free SpeechRecognition API. This
    endpoint exists for browsers without it: it forwards the audio to
    ``{LLM_BASE_URL}/audio/transcriptions`` when a key is configured, and
    otherwise returns a clear 501 the UI can explain.
    """
    if not config.LLM_API_KEY:
        raise HTTPException(
            501,
            "Server-side transcription needs LLM_API_KEY (Whisper-compatible provider). "
            "Your browser's built-in voice input works without one.",
        )
    audio = await file.read(25 * 1024 * 1024 + 1)
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio file too large (limit 25 MB).")
    boundary = "----carebridge-assistant-boundary"
    filename = file.filename or "audio.webm"
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n", audio, b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n',
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"{config.LLM_BASE_URL}/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Authorization": f"Bearer {config.LLM_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.LLM_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"text": payload.get("text", "")}
    except urllib.error.HTTPError as exc:
        raise HTTPException(502, f"Transcription provider error (HTTP {exc.code}).")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(502, f"Could not transcribe the audio: {exc}")


# ------------------------------------------------------------------ demo data

@router.post("/demo/seed")
def seed_demo(user: dict = Depends(auth.get_current_user)):
    """Load sample notes/tasks/a document so every feature can be tried at once."""
    created = {"notes": 0, "tasks": 0, "reminders": 0, "documents": 0}
    existing_note_titles = {n["title"] for n in db.list_notes(user["id"])}
    for sample in knowledge.SAMPLE_NOTES:
        if sample["title"] not in existing_note_titles:
            note = db.create_note(user["id"], sample["title"], sample["body"], sample["tags"])
            store.index_note(user["id"], note)
            created["notes"] += 1

    existing_titles = {t["title"] for t in db.list_tasks(user["id"])}
    now = datetime.now(timezone.utc)
    samples = [
        ("Revise merge sort & binary search", "high", now + timedelta(days=1)),
        ("Record 2-minute demo video", "normal", now + timedelta(days=3)),
        ("Try asking the assistant about a PDF", "normal", None),
    ]
    for title, priority, due in samples:
        if title not in existing_titles:
            db.create_task(user["id"], title, priority=priority,
                           due_at=due.isoformat() if due else None)
            created["tasks"] += 1

    if not db.list_reminders(user["id"]):
        db.create_reminder(user["id"], "Demo reminder: welcome to Bridge!",
                           (now + timedelta(minutes=2)).isoformat())
        created["reminders"] += 1

    existing_docs = {d["title"] for d in db.list_documents(user["id"])}
    if knowledge.SAMPLE_DOCUMENT_TITLE not in existing_docs:
        char_count = sum(len(t) for _, t in knowledge.SAMPLE_DOCUMENT_PAGES)
        doc = db.create_document(user["id"], "carebridge-study-notes.txt",
                                 knowledge.SAMPLE_DOCUMENT_TITLE, "text",
                                 num_pages=len(knowledge.SAMPLE_DOCUMENT_PAGES), char_count=char_count)
        count = store.index_document(user["id"], doc["id"], knowledge.SAMPLE_DOCUMENT_PAGES)
        db.update_document_chunks(doc["id"], count)
        created["documents"] += 1

    return {"created": created, "stats": db.stats(user["id"])}
