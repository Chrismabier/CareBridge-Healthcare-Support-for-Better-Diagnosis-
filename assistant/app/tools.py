"""Chat orchestration with explicit *tool use*.

The assistant does not just forward text to an LLM. Every message is routed
through a small tool layer first:

    create_reminder · create_task · list_tasks · complete_task
    create_note · search_notes · search_documents · summarize_document
    explain_concept · get_datetime · list_reminders · general_qa

Tools run deterministically against the database / vector store, and their
results (with page citations for documents) are then either phrased by the
LLM (when a key is configured) or composed by the offline brain. Either way
the actions - reminders created, tasks ticked off - really happen.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import db, knowledge, llm
from .textutils import best_sentences_for_query, extractive_summary, humanize_dt, parse_when, snippet
from .vectorstore import Hit, store

SYSTEM_PROMPT = (
    "You are Bridge, a helpful personal assistant inside the CareBridge project. "
    "Answer concisely and helpfully in Markdown. When CONTEXT excerpts are provided, answer "
    "from them and cite them like [Doc title - page N]; never invent page numbers or facts "
    "that are not in the context. If the context does not contain the answer, say so plainly "
    "before giving general knowledge."
)


@dataclass
class ToolResult:
    reply: str
    citations: list[dict] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    refresh: list[str] = field(default_factory=list)  # UI panels to reload: tasks/reminders/notes/documents
    # Browser-direct BYOK flow: when set, ``reply`` is the offline fallback and
    # the client may call its own LLM provider with these grounded messages,
    # then persist the result via POST /api/chat/{id}/complete.
    pending_llm: dict | None = None


# --------------------------------------------------------------------- helpers

def _clean_title(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip(" .,-")
    text = re.sub(r"^to\s+", "", text, flags=re.I)
    return (text[0].upper() + text[1:]) if text else text


def _context_block(hits: list[Hit]) -> str:
    parts = []
    for i, hit in enumerate(hits, 1):
        source = hit.citation()["label"]
        parts.append(f"[{i}] ({source})\n{hit.text}")
    return "\n\n".join(parts)


def _offline_grounded_answer(question: str, hits: list[Hit]) -> str:
    """Extractive answer: the best-matching sentences across all hits."""
    from .textutils import split_sentences, tokenize
    query_terms = set(tokenize(question))
    ranked = []
    for hit in hits[:4]:
        for sentence in split_sentences(hit.text):
            overlap = len(query_terms & set(tokenize(sentence)))
            if overlap:
                ranked.append((overlap, hit.score, sentence))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen, seen = [], set()
    for _, _, sentence in ranked:
        if sentence not in seen:
            seen.add(sentence)
            chosen.append(sentence)
        if len(chosen) >= 4:
            break
    if not chosen:
        chosen = [snippet(h.text, 300) for h in hits[:2]]
    return "Here's what I found in your documents and notes:\n\n" + " ".join(chosen)


def _build_llm_messages(conversation_id: int, question: str, hits: list[Hit]) -> list[dict]:
    """Grounded chat-completions payload (shared by server-LLM and browser-BYOK)."""
    history = db.recent_history(conversation_id, limit=8)
    if history and history[-1]["role"] == "user" and history[-1]["content"] == question:
        history = history[:-1]  # current question is appended below (with context)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    if hits:
        messages.append({
            "role": "user",
            "content": f"CONTEXT (from the user's own documents/notes):\n\n{_context_block(hits)}\n\n"
                       f"QUESTION: {question}",
        })
    else:
        messages.append({"role": "user", "content": question})
    return messages


def _pending_payload(conversation_id: int, question: str, hits: list[Hit]) -> dict:
    return {"messages": _build_llm_messages(conversation_id, question, hits)}


def _llm_answer(user: dict, conversation_id: int, question: str, hits: list[Hit]) -> str | None:
    """Ask the LLM, grounded in retrieved context. Returns None to fall back offline."""
    try:
        return llm.chat(_build_llm_messages(conversation_id, question, hits))
    except llm.LLMError:
        return None


# --------------------------------------------------------------------- tools

def tool_create_reminder(user: dict, message: str) -> ToolResult | None:
    m = re.search(r"remind me\s+(?:to\s+)?(.+)", message, re.I)
    if not m:
        return None
    rest = m.group(1).strip()
    when, matched = parse_when(rest)
    title = rest
    for fragment in matched:
        title = re.sub(re.escape(fragment), "", title, flags=re.I)
    title = _clean_title(re.sub(r"\b(on|at|to)\s*$", "", title.strip(" ,"), flags=re.I))
    if not title:
        return ToolResult("What would you like me to remind you about?", tools_used=["create_reminder"])
    if when is None:
        return ToolResult(
            f"I can set a reminder to **{title.lower()}** - but when? "
            "Try 'remind me to … tomorrow at 9am' or 'in 30 minutes'.",
            tools_used=["create_reminder"],
        )
    reminder = db.create_reminder(user["id"], title, when.isoformat())
    return ToolResult(
        f"⏰ Reminder set: **{title}** for **{humanize_dt(reminder['remind_at'])}**. "
        "I'll pop it up here when it's due (keep this tab open, or enable browser notifications).",
        tools_used=["create_reminder"], refresh=["reminders"],
    )


def tool_list_reminders(user: dict, message: str) -> ToolResult | None:
    if not re.search(r"\b(show|list|what|my|any)\b.*\breminder", message, re.I):
        return None
    reminders = db.list_reminders(user["id"])
    if not reminders:
        return ToolResult("You have no pending reminders. Try: *remind me to call the bank tomorrow at 10am*.",
                          tools_used=["list_reminders"])
    lines = "\n".join(f"- ⏰ **{r['title']}** - {humanize_dt(r['remind_at'])}" for r in reminders[:15])
    return ToolResult(f"Your pending reminders:\n\n{lines}", tools_used=["list_reminders"])


def tool_create_task(user: dict, message: str) -> ToolResult | None:
    m = re.search(r"(?:add|create|new)\s+(?:a\s+)?(?:task|to-?do)[:\s]+(.+)", message, re.I)
    if not m:
        m = re.search(r"^(?:task|todo)[:\s]+(.+)", message, re.I)
    if not m:
        return None
    raw = m.group(1).strip()
    when, matched = parse_when(raw)
    title = raw
    for fragment in matched:
        title = re.sub(re.escape(fragment), "", title, flags=re.I)
    if matched:
        title = re.sub(r"\b(due|by|on|at)\s*$", "", title.strip(" ,"), flags=re.I)
    title = _clean_title(title)
    if not title:
        return None
    priority = "high" if re.search(r"\b(urgent|important|asap)\b", raw, re.I) else "normal"
    task = db.create_task(user["id"], title, priority=priority,
                           due_at=when.isoformat() if when else None)
    due_txt = f" (due {humanize_dt(task['due_at'])})" if task.get("due_at") else ""
    return ToolResult(f"✅ Task added: **{title}**{due_txt}. Find it in the **Tasks** panel.",
                      tools_used=["create_task"], refresh=["tasks"])


def tool_list_tasks(user: dict, message: str) -> ToolResult | None:
    if not re.search(r"\b(show|list|what|my|any|open)\b.*\b(task|to-?do)", message, re.I) \
            and "to do list" not in message.lower() and "todo list" not in message.lower():
        return None
    tasks = db.list_tasks(user["id"], include_done=False)
    if not tasks:
        return ToolResult("Your task list is empty - nice! Add one with *add task: review the PR by tomorrow*.",
                          tools_used=["list_tasks"])
    def line(t):
        due = f" (due {humanize_dt(t['due_at'])})" if t.get("due_at") else ""
        prio = " 🔺" if t["priority"] == "high" else ""
        return f"- [ ] **{t['title']}**{due}{prio}"
    lines = "\n".join(line(t) for t in tasks[:20])
    return ToolResult(f"You have **{len(tasks)}** open task(s):\n\n{lines}", tools_used=["list_tasks"])


def tool_complete_task(user: dict, message: str) -> ToolResult | None:
    m = re.search(r"(?:mark|complete|finish|done with|tick off)\s+(?:task\s+)?(.+?)(?:\s+as\s+done|\s+done)?$", message, re.I)
    if not m:
        return None
    fragment = m.group(1).strip(" .")
    task = db.find_open_task_by_title(user["id"], fragment)
    if not task:
        return ToolResult(f"I couldn't find an open task matching “{fragment}”. Say *show my tasks* to see the list.",
                          tools_used=["complete_task"])
    db.update_task(user["id"], task["id"], done=True)
    return ToolResult(f"🎉 Done: **{task['title']}** marked complete.",
                      tools_used=["complete_task"], refresh=["tasks"])


def tool_create_note(user: dict, message: str) -> ToolResult | None:
    m = re.search(r"(?:save|make|create|add)\s+(?:a\s+)?note[:\s]+(.+)", message, re.I | re.S)
    if not m:
        m = re.search(r"^note[:\s]+(.+)", message, re.I | re.S)
    if not m:
        m = re.search(r"remember that\s+(.+)", message, re.I | re.S)
    if not m:
        return None
    body = m.group(1).strip()
    if not body:
        return None
    title = snippet(body.splitlines()[0], 50)
    note = db.create_note(user["id"], title, body)
    store.index_note(user["id"], note)
    return ToolResult(f"📝 Note saved: **{title}**. You can find it later with *search my notes for …*.",
                      tools_used=["create_note"], refresh=["notes"])


def tool_search_notes(user: dict, message: str) -> ToolResult | None:
    m = re.search(r"(?:search|find|look in|look up)\s+(?:in\s+)?my notes\s+(?:for\s+|about\s+)?(.+)", message, re.I)
    if not m:
        m = re.search(r"what did i (?:write|note) about\s+(.+)", message, re.I)
    if not m:
        return None
    query = m.group(1).strip(" ?.")
    hits = store.search(user["id"], query, top_k=5, source_types=("note",))
    if not hits:
        return ToolResult(f"I couldn't find any notes about “{query}”.", tools_used=["search_notes"])
    lines = "\n".join(f"- **{h.title or 'Note'}**: {snippet(h.text, 180)}" for h in hits)
    return ToolResult(f"Notes matching “{query}”:\n\n{lines}",
                      citations=[h.citation() for h in hits], tools_used=["search_notes"])


def tool_summarize(user: dict, message: str, document_id: int | None) -> ToolResult | None:
    if "summar" not in message.lower():
        return None
    doc = None
    if document_id:
        doc = db.get_document(user["id"], document_id)
    if doc is None:  # match a document by name, else the most recent one
        docs = db.list_documents(user["id"])
        lowered = message.lower()
        for candidate in docs:
            stem = (candidate["title"] or "").lower()
            if stem and any(word in lowered for word in re.findall(r"[a-z0-9]{4,}", stem)):
                doc = candidate
                break
        if doc is None and docs:
            doc = docs[0]
    if doc is None:
        return ToolResult("You haven't uploaded any documents yet. Upload a PDF in the **Documents** panel, then ask me to summarise it.",
                          tools_used=["summarize_document"])
    summary = summarize_document(user, doc)
    return ToolResult(f"**Summary of “{doc['title']}”** ({doc['num_pages']} page(s)):\n\n{summary}",
                      tools_used=["summarize_document"], refresh=["documents"])


def summarize_document(user: dict, doc: dict) -> str:
    chunks = db.chunks_for_document(doc["id"])
    full_text = "\n".join(c["text"] for c in chunks)
    if not full_text.strip():
        return "This document has no extractable text."
    try:
        summary = llm.chat([
            {"role": "system", "content": "Summarise documents faithfully and concisely in Markdown: a 2-3 sentence overview, then bullet key points. Do not add facts that are not in the text."},
            {"role": "user", "content": f"Summarise this document titled “{doc['title']}”:\n\n{full_text[:16000]}"},
        ], temperature=0.3)
    except llm.LLMError:
        summary = extractive_summary(full_text, max_sentences=6)
    db.set_document_summary(doc["id"], summary)
    return summary


def tool_explain(user: dict, message: str, client_llm: bool = False) -> ToolResult | None:
    # Only intercept * explicit* explain-style requests here. Anything else
    # goes to document retrieval first (the offline fallback in handle_chat
    # still checks the KB afterwards).
    m = re.search(r"(?:explain|teach me|what is|what are|how does|how do|define|meaning of)\s+(.+)", message, re.I)
    if m is None:
        return None
    topic = m.group(1).strip(" ?.").lower()
    concept = knowledge.find_concept(topic) or knowledge.find_concept(message)
    if concept is not None:
        llm_reply = None
        try:
            llm_reply = llm.chat([
                {"role": "system", "content": "You are a patient programming tutor. Explain concepts clearly in Markdown with a short example and common pitfalls. Keep it under ~350 words."},
                {"role": "user", "content": f"Explain: {concept['title']}" if concept else message},
            ], temperature=0.4)
        except llm.LLMError:
            llm_reply = None
        if llm_reply:
            return ToolResult(llm_reply, tools_used=["explain_concept", "llm"])
        result = ToolResult(concept["body"], tools_used=["explain_concept"])
        if client_llm:
            result.pending_llm = {"messages": [
                {"role": "system", "content": "You are a patient programming tutor. Explain concepts clearly in Markdown with a short example and common pitfalls. Keep it under ~350 words."},
                {"role": "user", "content": f"Explain: {concept['title']}"},
            ]}
        return result
    return None  # no KB hit -> general QA (LLM or graceful offline reply)


def tool_datetime(message: str) -> ToolResult | None:
    lowered = message.lower()
    if re.search(r"\b(what time|current time|what day|what is today|today's date|what date)\b", lowered):
        now = datetime.now(timezone.utc)
        return ToolResult(f"It's **{now.strftime('%A, %d %B %Y, %H:%M')} UTC** right now.",
                          tools_used=["get_datetime"])
    return None


def tool_help(user: dict, message: str) -> ToolResult | None:
    lowered = message.strip().lower()
    if lowered in {"help", "what can you do?", "what can you do", "features", "commands"} \
            or lowered.startswith(("hi", "hello", "hey")) and len(lowered) < 12:
        s = db.stats(user["id"])
        return ToolResult(
            f"Hi {user['name'].split()[0]}! I'm **Bridge**, your personal assistant. Here's what I can do:\n\n"
            "- 📄 **Ask about your PDFs** - upload one, then ask questions; I'll answer *with page references*.\n"
            "- ✍️ **Summarise** - “summarise my document”\n"
            "- ⏰ **Reminders** - “remind me to submit the form tomorrow at 9am”\n"
            "- ✅ **Tasks** - “add task: revise linked lists by Friday”, “show my tasks”, “mark revise as done”\n"
            "- 📝 **Notes** - “note: …”, “search my notes for …”\n"
            "- 💻 **Explain programming** - “explain recursion”, “what is a priority queue?”\n"
            "- 🎤 **Voice** - tap the mic and talk; tap 🔊 on any reply to hear it read aloud.\n\n"
            f"Right now you have {s['documents']} document(s), {s['notes']} note(s), "
            f"{s['open_tasks']} open task(s) and {s['pending_reminders']} pending reminder(s).",
            tools_used=["help"],
        )
    return None


# ------------------------------------------------------------------- routing

def handle_chat(user: dict, conversation_id: int, message: str,
                document_id: int | None = None, client_llm: bool = False) -> ToolResult:
    """Route one user message through tools, then retrieval, then the LLM."""
    for tool_fn, args in [
        (tool_datetime, (message,)),
        (tool_help, (user, message)),
        (tool_create_reminder, (user, message)),
        (tool_list_reminders, (user, message)),
        (tool_create_task, (user, message)),
        (tool_complete_task, (user, message)),
        (tool_list_tasks, (user, message)),
        (tool_create_note, (user, message)),
        (tool_search_notes, (user, message)),
        (tool_summarize, (user, message, document_id)),
    ]:
        result = tool_fn(*args)
        if result is not None:
            return result

    explained = tool_explain(user, message, client_llm=client_llm)
    if explained is not None:
        return explained

    # Retrieval-augmented QA over the user's documents + notes.
    hits = store.search(
        user["id"], message, top_k=5,
        document_id=document_id,
        source_types=("document",) if document_id else ("document", "note"),
    )
    strong_hits = [h for h in hits if h.score >= 0.08] or hits[:2]

    llm_reply = _llm_answer(user, conversation_id, message, strong_hits)
    if llm_reply:
        tools = ["llm"] + (["search_documents"] if strong_hits else [])
        return ToolResult(llm_reply, citations=[h.citation() for h in strong_hits], tools_used=tools)

    # ---- offline fallbacks (no API key, or provider error) ----
    if strong_hits and strong_hits[0].score >= 0.05:
        result = ToolResult(
            _offline_grounded_answer(message, strong_hits),
            citations=[h.citation() for h in strong_hits],
            tools_used=["search_documents", "offline-extractive"],
        )
    else:
        concept = knowledge.find_concept(message)
        if concept:
            result = ToolResult(concept["body"], tools_used=["explain_concept"])
        else:
            result = ToolResult(_offline_no_answer(user, message), tools_used=["general_qa", "offline-demo"])
    if client_llm:
        # Browser will ask its own provider with the same grounded prompt;
        # ``result.reply`` stays as the instant offline fallback.
        result.pending_llm = _pending_payload(conversation_id, message, strong_hits)
    return result


def _offline_no_answer(user: dict, message: str) -> str:
    stats = db.stats(user["id"])
    lines = ["I don't have a confident answer for that one yet - I'm in **offline mode** "
             "(no AI model connected), so I can only use your files and my built-in knowledge right now.\n"]
    if stats["documents"] == 0 and stats["notes"] == 0:
        lines.append("- 📄 You have no documents/notes yet: upload a PDF (Documents panel) or use "
                     "**Load demo data**, then ask me about it - I'll answer with page references.")
    else:
        lines.append("- 🔎 I searched your documents and notes - nothing matched. Try different keywords.")
    suggestions = knowledge.suggest_topics(message)
    if suggestions:
        joined = ", ".join(f"**{t}**" for t in suggestions)
        lines.append(f"- 💻 Closest topics I can explain offline: {joined} - try *explain {suggestions[0]}*.")
    lines.append(f"- 💻 Or ask about any of my {len(knowledge.CONCEPTS)} built-in topics: *what is a CPU*, "
                 "*explain recursion*, *how does the web work*, *compiler vs interpreter*...")
    lines.append("- ⏰✅📝 I can always set reminders, manage tasks and search your notes.")
    lines.append("\n💡 **Want answers to absolutely anything?** Tap **⚙️ AI settings** (top right) and paste "
                 "your own free Groq/OpenRouter API key - it stays in your browser, is sent only to that "
                 "provider, and unlocks full AI answers on top of everything above.")
    return "\n".join(lines)


def answer_about_document(user: dict, doc: dict, question: str,
                          client_llm: bool = False) -> ToolResult:
    hits = store.search(user["id"], question, top_k=5, source_types=("document",), document_id=doc["id"])
    if not hits:
        return ToolResult(f"I couldn't find anything about that in “{doc['title']}”. Try different keywords.",
                          tools_used=["search_documents"])
    try:
        reply = llm.chat([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content":
                f"CONTEXT from “{doc['title']}”:\n\n{_context_block(hits)}\n\nQUESTION: {question}"},
        ])
        return ToolResult(reply, citations=[h.citation() for h in hits],
                          tools_used=["search_documents", "llm"])
    except llm.LLMError:
        result = ToolResult(_offline_grounded_answer(question, hits),
                            citations=[h.citation() for h in hits],
                            tools_used=["search_documents", "offline-extractive"])
        if client_llm:
            result.pending_llm = {"messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content":
                    f"CONTEXT from the document:\n\n{_context_block(hits)}\n\nQUESTION: {question}"},
            ]}
        return result
