"""CareBridge AI Personal Assistant - FastAPI application.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000   (or: python run.py)

Reliability features (the "portfolio value" bits):
* structured JSON errors - every failure returns
  ``{"error": {"code", "message", "request_id"}}`` and is logged with the same id;
* per-IP rate limiting (tighter on auth endpoints);
* request-id propagation + basic security headers;
* graceful degradation - no LLM key / provider outage => offline brain answers.
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, config, db
from .routers import auth_router, chat, documents, misc, notes, tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("assistant")

app = FastAPI(
    title="CareBridge AI Personal Assistant",
    version=__version__,
    description="Voice-enabled personal assistant: PDF Q&A with page citations, summaries, "
                "notes, tasks, reminders and programming explanations. Works offline; "
                "connect any OpenAI-compatible LLM via LLM_API_KEY for open-ended answers.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # the UI is served from this same origin; permissive for local dev
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------ rate limiting
# Simple in-memory sliding window per client IP. Enough to stop accidental
# floods / credential stuffing in a single-process deployment; swap for Redis
# if you scale out (see README).
_hits: dict[str, deque] = defaultdict(deque)


def _rate_limited(request: Request) -> bool:
    ip = request.client.host if request.client else "unknown"
    is_auth = request.url.path.startswith("/api/auth/")
    limit, window = (30, 60.0) if is_auth else (600, 60.0)
    key = f"{ip}:{'auth' if is_auth else 'api'}"
    now = time.time()
    bucket = _hits[key]
    while bucket and bucket[0] < now - window:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


@app.middleware("http")
async def reliability_middleware(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    if request.url.path.startswith("/api/") and _rate_limited(request):
        return JSONResponse(
            status_code=429,
            content={"error": {"code": "rate_limited",
                               "message": "Too many requests - please slow down and try again in a minute.",
                               "request_id": request_id}},
            headers={"Retry-After": "60", "X-Request-Id": request_id},
        )
    started = time.time()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    log.info("%s %s -> %s (%.0f ms) [%s]", request.method, request.url.path,
             response.status_code, (time.time() - started) * 1000, request_id)
    return response


# ------------------------------------------------------------ error handling

def _error_body(request: Request, status_code: int, message: str, code: str = "error") -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


@app.exception_handler(HTTPException)
@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    message = exc.detail if isinstance(exc.detail, str) else "Request failed."
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict",
            413: "too_large", 422: "validation_error", 429: "rate_limited",
            501: "not_implemented", 502: "upstream_error"}.get(exc.status_code, "error")
    response = _error_body(request, exc.status_code, message, code)
    for key, value in (exc.headers or {}).items():
        response.headers[key] = value
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    first = errors[0] if errors else {}
    field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
    message = f"Invalid input{f' for {field}' if field else ''}: {first.get('msg', 'validation failed')}."
    return _error_body(request, 422, message, "validation_error")


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    log.exception("Unhandled error [%s]", request_id)
    return _error_body(request, 500,
                       "Something went wrong on the server. Your data is safe - please try again.",
                       "internal_error")


# ------------------------------------------------------------------- routes

for router in (auth_router.router, chat.router, documents.router,
               notes.router, tasks.router, misc.router):
    app.include_router(router)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")


@app.on_event("startup")
def startup() -> None:
    config.ensure_dirs()
    db.init_db()
    mode = f"LLM: {config.LLM_MODEL} via {config.LLM_BASE_URL}" if config.llm_enabled() \
        else "offline demo mode (set LLM_API_KEY for full AI answers)"
    log.info("CareBridge Assistant %s ready - %s", __version__, mode)
