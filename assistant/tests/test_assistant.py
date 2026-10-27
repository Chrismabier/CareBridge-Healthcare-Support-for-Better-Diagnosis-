"""Test suite for the CareBridge AI Personal Assistant.

Runs with plain python (no pytest needed) or under pytest:

    python tests/test_assistant.py
    pytest tests/            # if pytest is installed

Uses an isolated temporary database and the generated sample PDF, and covers
auth, document Q&A with page citations, summarisation, notes search, chat
tool-use (tasks/reminders/notes/explain), error handling and user isolation.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="bridge-test-")
os.environ["ASSISTANT_DATA_DIR"] = _TMP
os.environ["ASSISTANT_DB_PATH"] = str(Path(_TMP) / "test.db")
os.environ.pop("LLM_API_KEY", None)   # force offline mode for determinism
os.environ.pop("OPENAI_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.textutils import parse_when  # noqa: E402
from make_sample_pdf import build_pdf, PAGES  # noqa: E402

_client: TestClient | None = None
_headers: dict | None = None


def client() -> tuple[TestClient, dict]:
    global _client, _headers
    if _client is None:
        _client = TestClient(app)
        _client.__enter__()
        resp = _client.post("/api/auth/register", json={
            "name": "Test User", "email": "test@example.com", "password": "password123"})
        assert resp.status_code == 201, resp.text
        _headers = {"Authorization": f"Bearer {resp.json()['token']}"}
    return _client, _headers


# --------------------------------------------------------------------- units

def test_parse_when_relative_and_absolute():
    when, parts = parse_when("call mom in 45 minutes")
    assert when is not None and parts == ["in 45 minutes"]
    when, parts = parse_when("submit report tomorrow at 9am")
    assert when is not None and when.hour == 9 and "tomorrow" in parts
    when, _ = parse_when("no time here at all really")
    # "at all" must not be mistaken for a time (no digits follow)
    assert when is None


def test_chunking_keeps_pages():
    from app.textutils import chunk_text
    text = " ".join(f"Sentence number {i} about linked lists and queues." for i in range(60))
    chunks = chunk_text(text)
    assert len(chunks) >= 2 and all(len(c) <= 1000 for c in chunks)


# ---------------------------------------------------------------------- auth

def test_health_and_auth_required():
    c, _ = client()
    assert c.get("/api/health").json()["llm"]["mode"] == "offline-demo"
    # The shared TestClient carries a bridge_token cookie from client()
    # registration; override it to simulate a truly unauthenticated call.
    resp = c.get("/api/notes", cookies={"bridge_token": "invalid"})
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"]["code"] == "unauthorized" and body["error"]["request_id"]


def test_login_wrong_password_and_duplicate_email():
    c, _ = client()
    assert c.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong"}).status_code == 401
    dup = c.post("/api/auth/register", json={
        "name": "Dup", "email": "test@example.com", "password": "password123"})
    assert dup.status_code == 409
    short = c.post("/api/auth/register", json={
        "name": "X", "email": "x@example.com", "password": "short"})
    assert short.status_code == 422  # structured validation error, not a crash


def test_demo_account():
    c, _ = client()
    resp = c.post("/api/auth/demo")
    assert resp.status_code == 200 and resp.json()["user"]["email"].endswith("@carebridge.local")


# ----------------------------------------------------------------- documents

_doc_id: int | None = None


def ensure_doc() -> int:
    """Upload the sample PDF once (tests may run in any order)."""
    global _doc_id
    c, h = client()
    if _doc_id is None:
        resp = c.post("/api/documents/upload", headers=h,
                      files={"file": ("report.pdf", build_pdf(PAGES), "application/pdf")})
        assert resp.status_code == 201, resp.text
        _doc_id = resp.json()["id"]
    return _doc_id


def test_pdf_upload_and_page_cited_qa():
    c, h = client()
    ensure_doc()
    doc = c.get(f"/api/documents/{_doc_id}", headers=h).json()
    assert doc["num_pages"] == 3 and doc["num_chunks"] >= 3

    qa = c.post(f"/api/documents/{_doc_id}/ask", headers=h,
                json={"question": "Which hospitals are in the demo data?"}).json()
    assert "CityCare" in qa["answer"] and any(cite["page"] == 1 for cite in qa["citations"])

    qa = c.post(f"/api/documents/{_doc_id}/ask", headers=h,
                json={"question": "How are appointment requests ordered by urgency?"}).json()
    assert "Emergency" in qa["answer"] and qa["citations"][0]["page"] == 2

    qa = c.post(f"/api/documents/{_doc_id}/ask", headers=h,
                json={"question": "When are telemedicine video calls planned?"}).json()
    assert "2027" in qa["answer"] and qa["citations"][0]["page"] == 3

    qa = c.post(f"/api/documents/{_doc_id}/ask", headers=h,
                json={"question": "What is the capital of France?"}).json()
    assert qa["citations"] == [] and "couldn't find" in qa["answer"]


def test_pdf_error_handling():
    c, h = client()
    bad = c.post("/api/documents/upload", headers=h,
                 files={"file": ("bad.pdf", b"hello", "application/pdf")})
    assert bad.status_code == 422 and "valid PDF" in bad.json()["error"]["message"]
    exe = c.post("/api/documents/upload", headers=h,
                 files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert exe.status_code == 422
    empty = c.post("/api/documents/upload", headers=h,
                   files={"file": ("e.txt", b"", "text/plain")})
    assert empty.status_code == 422


def test_summarize_document():
    c, h = client()
    resp = c.post(f"/api/documents/{ensure_doc()}/summarize", headers=h)
    assert resp.status_code == 200
    summary = resp.json()["summary"]
    assert len(summary) > 80
    assert any(word in summary.lower() for word in ("carebridge", "patient", "hospital", "doctor"))


# ---------------------------------------------------------------------- chat

def test_chat_task_and_reminder_tools():
    c, h = client()
    r = c.post("/api/chat", headers=h, json={"message": "add task: revise binary search by friday"}).json()
    assert "create_task" in r["tools_used"] and "Revise binary search" in r["reply"]
    r = c.post("/api/chat", headers=h, json={"message": "remind me to call the bank tomorrow at 10am"}).json()
    assert "create_reminder" in r["tools_used"] and "Call the bank" in r["reply"]
    r = c.post("/api/chat", headers=h, json={"message": "show my tasks"}).json()
    assert "binary search" in r["reply"].lower()
    r = c.post("/api/chat", headers=h, json={"message": "mark binary search as done"}).json()
    assert "complete_task" in r["tools_used"]
    tasks = c.get("/api/tasks", headers=h).json()["tasks"]
    assert any(t["done"] and "binary" in t["title"].lower() for t in tasks)


def test_chat_notes_and_explain_and_doc_qa():
    c, h = client()
    ensure_doc()
    r = c.post("/api/chat", headers=h, json={"message": "note: the wifi password is hunter2"}).json()
    assert "create_note" in r["tools_used"]
    r = c.post("/api/chat", headers=h, json={"message": "search my notes for wifi"}).json()
    assert "hunter2" in r["reply"]
    r = c.post("/api/chat", headers=h, json={"message": "explain recursion"}).json()
    assert "base case" in r["reply"].lower()
    r = c.post("/api/chat", headers=h, json={"message": "Which queue orders appointment requests?"}).json()
    assert r["citations"] and any(cite["page"] == 2 for cite in r["citations"])
    r = c.post("/api/chat", headers=h, json={"message": "write me a poem about the moon"}).json()
    assert "offline" in r["reply"].lower()  # honest degradation, no fake answer


def test_notes_crud_and_search():
    c, h = client()
    note = c.post("/api/notes", headers=h, json={
        "title": "Grocery list", "body": "milk, eggs, spinach and paneer", "tags": "home"}).json()
    results = c.get("/api/notes/search", headers=h, params={"q": "paneer groceries"}).json()["results"]
    assert any(r["note_id"] == note["id"] for r in results)
    updated = c.put(f"/api/notes/{note['id']}", headers=h, json={
        "title": "Groceries", "body": "milk and bread", "tags": "home"}).json()
    assert updated["title"] == "Groceries"
    assert c.delete(f"/api/notes/{note['id']}", headers=h).status_code == 200
    assert c.get(f"/api/notes/{note['id']}", headers=h).status_code == 404


def test_reminder_due_flow():
    c, h = client()
    past = "2020-01-01T00:00:00+00:00"
    c.post("/api/reminders", headers=h, json={"title": "overdue thing", "remind_at": past})
    due = c.get("/api/reminders/due", headers=h).json()["due"]
    assert any(r["title"] == "overdue thing" for r in due)
    due_again = c.get("/api/reminders/due", headers=h).json()["due"]
    assert not any(r["title"] == "overdue thing" for r in due_again)  # notified once


def test_user_isolation():
    c, h = client()
    ensure_doc()
    other = c.post("/api/auth/register", json={
        "name": "Other", "email": "other@example.com", "password": "password123"}).json()
    h2 = {"Authorization": f"Bearer {other['token']}"}
    assert c.get("/api/documents", headers=h2).json()["documents"] == []
    assert c.post(f"/api/documents/{_doc_id}/ask", headers=h2,
                  json={"question": "hospitals?"}).status_code == 404
    assert c.get("/api/notes", headers=h2).json()["notes"] == []


def test_explain_endpoint_and_speech_status():
    c, h = client()
    r = c.post("/api/explain", headers=h, json={"concept": "big o notation"}).json()
    assert "O(n" in r["explanation"] and r["source"] == "knowledge-base"
    missing = c.post("/api/explain", headers=h, json={"concept": "quantum chromodynamics"})
    assert missing.status_code == 404 and "LLM_API_KEY" in missing.json()["error"]["message"]
    speech = c.get("/api/speech/status", headers=h).json()
    assert speech["server_transcription"] is False


def test_demo_seed_is_idempotent():
    c, h = client()
    first = c.post("/api/demo/seed", headers=h).json()
    second = c.post("/api/demo/seed", headers=h).json()
    assert first["stats"]["notes"] == second["stats"]["notes"]
    assert second["created"]["notes"] == 0



# ------------------------------------------------- auth transport fallbacks
# Regression tests for the "login doesn't stick behind the preview proxy" bug:
# the proxy may strip or overwrite Authorization, so the token must also be
# accepted via X-Bridge-Token / cookie, and a garbage Bearer value must not
# shadow a valid fallback credential.

_fallback_token: str | None = None


def _fresh_token() -> str:
    global _fallback_token
    c, _ = client()
    if _fallback_token is None:
        resp = c.post("/api/auth/register", json={
            "name": "Proxy User", "email": "proxy@example.com", "password": "password123"})
        assert resp.status_code == 201, resp.text
        _fallback_token = resp.json()["token"]
        # login sets the fallback cookie
        assert "bridge_token=" in resp.headers.get("set-cookie", "")
    return _fallback_token


def test_auth_via_custom_header_only():
    c, _ = client()
    token = _fresh_token()
    # Simulate a proxy that strips Authorization entirely:
    resp = c.get("/api/auth/me", headers={"X-Bridge-Token": token}, cookies={})
    assert resp.status_code == 200, resp.text
    chat = c.post("/api/chat", headers={"X-Bridge-Token": token}, cookies={},
                  json={"message": "what time is it?"})
    assert chat.status_code == 200 and "UTC" in chat.json()["reply"]


def test_auth_via_cookie_only():
    c, _ = client()
    token = _fresh_token()
    resp = c.get("/api/auth/me", cookies={"bridge_token": token})
    assert resp.status_code == 200, resp.text


def test_garbage_authorization_does_not_shadow_fallback():
    c, _ = client()
    token = _fresh_token()
    # Simulate a proxy that overwrites Authorization with its own value:
    resp = c.get("/api/auth/me", cookies={},
                 headers={"Authorization": "Bearer not-a-real-token", "X-Bridge-Token": token})
    assert resp.status_code == 200, resp.text
    # ...but with every credential invalid it must still be a clean 401:
    resp = c.get("/api/auth/me", cookies={"bridge_token": "nope"},
                 headers={"Authorization": "Bearer nope", "X-Bridge-Token": "nope"})
    assert resp.status_code == 401


# ------------------------------------------- offline KB + browser BYOK flow

def test_what_is_cpu_answers_offline():
    """Regression: 'what is CPU' used to dead-end in the offline-mode message."""
    c, h = client()
    r = c.post("/api/chat", headers=h, json={"message": "what is CPU"}).json()
    assert "Central Processing Unit" in r["reply"] or "fetch" in r["reply"]
    assert "offline demo mode" not in r["reply"].lower()
    r = c.post("/api/chat", headers=h, json={"message": "how does the internet work"}).json()
    assert "DNS" in r["reply"]
    # genuinely unknown topic: helpful fallback pointing at AI settings
    r = c.post("/api/chat", headers=h, json={"message": "what is quantum chromodynamics"}).json()
    assert "AI settings" in r["reply"] and "offline" in r["reply"].lower()


def test_client_llm_pending_and_complete():
    c, h = client()
    resp = c.post("/api/chat", headers=h, json={
        "message": "write a haiku about autumn rain", "client_llm": True})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pending_llm"]["messages"][-1]["content"].startswith("write a haiku")
    assert data["offline_reply"]  # ready-made fallback
    conv = data["conversation_id"]
    # assistant message NOT persisted yet (browser still owes us the answer)
    msgs = c.get(f"/api/conversations/{conv}/messages", headers=h).json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]
    # ...browser "called its provider" and now completes the turn:
    done = c.post(f"/api/chat/{conv}/complete", headers=h, json={
        "content": "soft rain on rooftops", "citations": data["citations"],
        "tools": data["tools_used"] + ["browser-ai"]})
    assert done.status_code == 200, done.text
    msgs = c.get(f"/api/conversations/{conv}/messages", headers=h).json()["messages"]
    assert msgs[-1]["role"] == "assistant" and "rooftops" in msgs[-1]["content"]
    # another user cannot write into this conversation
    other = c.post("/api/auth/register", json={
        "name": "Mallory", "email": "mallory@example.com", "password": "password123"}).json()
    h2 = {"Authorization": f"Bearer {other['token']}"}
    assert c.post(f"/api/chat/{conv}/complete", headers=h2,
                  json={"content": "hijack"}).status_code == 404


def test_client_llm_pending_includes_document_context():
    c, h = client()
    ensure_doc()
    data = c.post("/api/chat", headers=h, json={
        "message": "Which hospitals are mentioned?", "client_llm": True,
        "document_id": _doc_id}).json()
    assert data["pending_llm"] is not None
    joined = " ".join(m["content"] for m in data["pending_llm"]["messages"])
    assert "CONTEXT" in joined and "CityCare" in joined
    assert any(cite["page"] == 1 for cite in data["citations"])
    assert "CityCare" in data["offline_reply"]

ALL_TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failures = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - test runner
            failures += 1
            import traceback
            print(f"FAIL {test.__name__}: {exc}")
            traceback.print_exc()
    print(f"\n{len(ALL_TESTS) - failures}/{len(ALL_TESTS)} tests passed")
    sys.exit(1 if failures else 0)
