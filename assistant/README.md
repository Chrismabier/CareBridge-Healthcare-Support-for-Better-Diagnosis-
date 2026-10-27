# Bridge — AI-Powered Personal Assistant

A voice-enabled personal assistant built for the CareBridge project with
**Python + FastAPI**, a **TF-IDF vector database** for retrieval over your own
documents, an **OpenAI-compatible LLM layer**, and a dependency-free
**HTML/CSS/JavaScript** frontend using the browser's speech APIs.

It is designed to be useful in two modes:

* **Offline mode (default, zero API keys)** — PDF Q&A with page citations,
  extractive summaries, notes search, tasks, reminders and a 33-topic
  computing/programming knowledge base (CPU, recursion, Big-O, Git, the web…)
  all run locally and deterministically.
* **Full AI mode (pick either)** —
  **(a) Browser key (BYOK):** tap **⚙️ AI settings**, paste a free
  Groq/OpenRouter key, and your *browser* asks the provider directly with
  the grounded prompt this server prepares (the key never touches the
  server, so it works in any hosted preview); or
  **(b) Server key:** set `LLM_API_KEY` (OpenAI, Groq, OpenRouter, Ollama…)
  so the backend calls the model itself. If the provider is down, the
  assistant falls back to the offline brain instead of erroring.

> This is a portfolio/learning project that lives alongside the CareBridge
> C++17 system in this repository (see the [root README](../README.md)). It
> does not modify the C++ application.

## Features (and where they live)

| Feature | How it works |
|---|---|
| 💬 Answer questions using an AI model | `POST /api/chat` → tool router → LLM (`app/llm.py`, any OpenAI-compatible endpoint) with conversation history — or **browser-direct BYOK**: server returns a grounded `pending_llm` prompt, the browser calls the user's provider, `POST /api/chat/{id}/complete` persists the reply |
| 🎤 Voice commands | Mic button → Web Speech API `SpeechRecognition`; say *"remind me to call the bank tomorrow at 10am"* and it acts |
| 🗣️→📝 Speech-to-text | Browser `SpeechRecognition` (free, Chrome/Edge) + optional server Whisper proxy at `POST /api/speech/transcribe` |
| ✍️ Summarize uploaded documents | `POST /api/documents/{id}/summarize` — LLM abstractive summary, extractive (TF-scored sentences) offline |
| ⏰✅ Reminders & task lists | Chat tools + panels; natural-language times (*"in 30 minutes"*, *"by Friday at 6pm"*), due-reminder polling, browser notifications, snooze |
| 🔎 Search personal notes | Notes are chunked into the same vector store; semantic search in chat and in the Notes panel |
| 💻 Explain programming concepts | `POST /api/explain` — LLM tutor, or a built-in knowledge base (recursion, Big-O, OOP, linked lists, Git, auth, …) |
| 🔊 Read responses aloud | Per-message 🔊 button + auto-read toggle via `speechSynthesis` |
| 📄 **Advanced: PDF retrieval with page references** | pypdf extracts text **per page** → overlapping chunks → TF-IDF vectors in SQLite → cosine search → answers cite `[title — page N]` with clickable source snippets |
| 🔐 Authentication | Register/login, PBKDF2-SHA256 password hashing, HMAC-signed bearer tokens, per-user data scoping everywhere |
| 🛡️ Reliable error handling | Structured `{error: {code, message, request_id}}` responses, request logging, rate limiting, upload validation (type/size/corrupt/encrypted/scanned PDFs), offline fallbacks |

## Quick start

```bash
cd assistant
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/python run.py                     # http://localhost:8000
```

Then open <http://localhost:8000>, click **“Try the one-click demo account”**,
hit **✨ Load demo data**, and try:

* 🎤 *"What data structure does CareBridge use for appointment requests?"* → answer **citing page 2**
* *"Remind me to submit the assignment tomorrow at 9am"*
* *"Add task: revise linked lists by Friday"* → *"Show my tasks"*
* *"Explain merge sort"*
* Upload `scripts/sample.pdf` (generate it with
  `python scripts/make_sample_pdf.py`) → **Summarise** / **Ask**
* Interactive API docs: <http://localhost:8000/docs>

Run the tests (auth, PDF page-cited Q&A, summaries, chat tools, isolation,
error cases, auth transports, BYOK round-trip — no network or API key needed):

```bash
.venv/bin/python tests/test_assistant.py    # also pytest-compatible
```

### Enable full AI answers (optional)

**Easiest — in the browser (no server access needed):** open the app, tap
**⚙️ AI settings** (top right), paste a free API key from
[Groq](https://console.groq.com/keys) or [OpenRouter](https://openrouter.ai/keys),
tick *Use my API key*, Save, and optionally **🔌 Test connection**. The key is
stored only in your browser's local storage and sent only to that provider;
removing it is one click in the same dialog. Document answers stay grounded:
the server still does retrieval and passes the relevant pages to the model.

**Or on the server:** copy `.env.example` values into your environment (any OpenAI-compatible API):

```bash
export LLM_API_KEY=sk-...                                      # OpenAI
# Groq:       LLM_BASE_URL=https://api.groq.com/openai/v1  LLM_MODEL=llama-3.3-70b-versatile
# OpenRouter: LLM_BASE_URL=https://openrouter.ai/api/v1
# Ollama:     LLM_BASE_URL=http://localhost:11434/v1  LLM_MODEL=llama3.1  LLM_API_KEY=ollama
.venv/bin/python run.py
```

The header badge switches from *📴 Offline demo mode* to *🧠 \<model\>*.
`GET /api/health` reports the same, which is handy for deployment checks.

### Docker

```bash
docker compose up --build assistant   # from repo root → http://localhost:8000
# or standalone:
docker build -f Dockerfile.assistant -t bridge-assistant .   # from repo root
docker run --rm -p 8000:8000 -e LLM_API_KEY=sk-... bridge-assistant
```

## Architecture

```
Browser (static/index.html, app.js)                FastAPI (app/)
┌─────────────────────────────────┐                ┌──────────────────────────────┐
│ chat UI · doc/notes/task panels │  REST + Bearer │ routers/  auth · chat · docs │
│ 🎤 SpeechRecognition (STT)      │ ─────────────▶ │           notes · tasks · misc│
│ 🔊 speechSynthesis (TTS)       │ ◀───────────── │ tools.py  chat orchestration │
│ reminder polling + Notifications│   JSON         │   ├─ tools: reminders, tasks,│
└─────────────────────────────────┘                │   │  notes, summarize, explain│
                                                   │   └─ RAG: vectorstore.search │
   SQLite (data/assistant.db)                      │ vectorstore.py  TF-IDF + cosine│
   users·conversations·messages·documents          │ ingest.py  pypdf per-page text│
   chunks (vectors)·notes·tasks·reminders ◀─────── │ llm.py  OpenAI-compatible API │
                                                   │         (urllib, retry, fallback)│
                                                   │ knowledge.py  offline tutor KB │
                                                   └──────────────────────────────┘
```

**Chat is tool-use, not a bare LLM proxy.** Every message is routed through
deterministic tools first (`create_reminder`, `create_task`, `search_notes`,
`summarize_document`, `explain_concept`, … — see `app/tools.py`). Tool actions
really mutate the database; retrieval results (with page numbers) become the
LLM's context when a key is configured, or an extractive grounded answer when
it isn't. The UI shows which tools ran (🛠 chips) and the exact sources used.

**Vector store design** (`app/vectorstore.py`): documents/notes →
sentence-aware overlapping chunks (~850 chars) → sparse TF-IDF vectors
(light stemming, stop-word removal) persisted in SQLite → per-user in-memory
IDF index → cosine similarity. TF-IDF was chosen so the whole pipeline works
offline with no model downloads and produces reproducible citations.

**Upgrading the vector store**: the `VectorStore` interface
(`index_document`, `index_note`, `search -> Hit`) mirrors what
Chroma/FAISS + neural embeddings would expose. To upgrade, add an embedder
(e.g. `sentence-transformers` or an `/embeddings` API call) behind an env
flag, store dense vectors instead of term counts, and keep everything else —
including page citations — unchanged.

**Security notes**: passwords are PBKDF2-SHA256 (240k iterations, per-user
salt); tokens are HMAC-SHA256 signed with an auto-generated secret in
`data/.secret` (override with `ASSISTANT_SECRET`); every query is scoped by
`user_id`; uploads are size/type/magic-checked; auth endpoints are
rate-limited separately. The token is accepted via `Authorization: Bearer`,
`X-Bridge-Token`, or the `bridge_token` cookie (first valid one wins) —
some reverse proxies strip/overwrite `Authorization`, which otherwise makes
the UI appear to "not stay logged in"; the SPA sends both headers and only
logs out after `/api/auth/me` confirms the session is really gone. Serve
behind HTTPS in production (and add `Secure` to the cookie there).

**Timezones**: form-entered dates are converted by the browser to UTC
correctly. Times typed in chat (*"tomorrow at 9am"*) are interpreted as UTC —
fine for demos; passing the browser offset with chat requests is on the
roadmap below.

## API summary

Full interactive docs at `/docs` (OpenAPI). Highlights:

| Endpoint | Description |
|---|---|
| `POST /api/auth/{register,login,demo}` · `GET /api/auth/me` | accounts + token |
| `POST /api/chat` | message → tools → `{reply, citations[], tools_used[], refresh[]}`; with `client_llm: true` returns `{pending_llm, offline_reply, …}` instead |
| `POST /api/chat/{id}/complete` | persist a browser-generated (BYOK) assistant reply |
| `GET/POST/DELETE /api/conversations…` | chat history |
| `POST /api/documents/upload` | PDF/TXT/MD → chunks indexed per page |
| `POST /api/documents/{id}/{ask,summarize}` | page-cited Q&A · summary |
| `CRUD /api/notes` · `GET /api/notes/search?q=` | notes + semantic search |
| `CRUD /api/tasks` · `CRUD /api/reminders` · `GET /api/reminders/due` | lists, alerts, polling feed |
| `POST /api/search` · `POST /api/explain` | unified retrieval · programming tutor |
| `GET /api/speech/status` · `POST /api/speech/transcribe` | speech capabilities / Whisper proxy |
| `POST /api/demo/seed` · `GET /api/health` · `GET /api/stats` | demo data, health, counters |

## Project layout

```
assistant/
├── run.py                  # uvicorn entry point (HOST/PORT from env)
├── requirements.txt        # fastapi, uvicorn, pypdf, python-multipart, httpx(test)
├── .env.example            # every supported environment variable
├── app/
│   ├── main.py             # FastAPI app, middleware, structured errors, rate limits
│   ├── config.py  db.py    # env config · SQLite layer (stdlib only)
│   ├── auth.py             # PBKDF2 + HMAC tokens (stdlib only)
│   ├── ingest.py           # PDF/TXT/MD → per-page text (pypdf)
│   ├── vectorstore.py      # TF-IDF vector database + cosine search
│   ├── textutils.py        # chunking, extractive summary, NL date/time parser
│   ├── llm.py              # OpenAI-compatible client (urllib, retries)
│   ├── knowledge.py        # programming KB + demo seed content
│   ├── tools.py            # chat orchestration & tool implementations
│   └── routers/            # auth · chat · documents · notes · tasks · misc
├── static/                 # index.html · styles.css · app.js (voice, markdown, panels)
├── scripts/make_sample_pdf.py + sample.pdf
├── tests/test_assistant.py # 21 tests, plain-python runnable
└── data/                   # created at runtime (gitignored): DB, uploads, .secret
```

Only four runtime dependencies: auth, the vector store, the LLM client and
all persistence are implemented on the Python standard library on purpose —
fewer supply-chain surprises, and the internals are there to be read.

## Roadmap / ideas

* Dense embeddings (sentence-transformers or API embeddings) + ANN index (FAISS/Chroma) behind the existing `VectorStore` interface
* OCR for scanned PDFs (Tesseract), DOCX/PPTX ingestion
* Streaming chat responses (SSE) and LLM function-calling instead of regex intents
* Browser timezone offset for chat-parsed reminder times; recurring reminders
* Server-side TTS (e.g. Piper) for browsers without `speechSynthesis`
* OAuth login, refresh tokens, and Postgres for multi-instance deploys
