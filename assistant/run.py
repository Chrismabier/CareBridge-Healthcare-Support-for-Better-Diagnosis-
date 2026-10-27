#!/usr/bin/env python3
"""Start the CareBridge AI Personal Assistant.

    python run.py            # http://localhost:8000  (API docs at /docs)

Environment: HOST, PORT, LLM_API_KEY / OPENAI_API_KEY, LLM_BASE_URL, LLM_MODEL
(see .env.example). With no key set the assistant runs in offline demo mode.
"""
import uvicorn

from app import config

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)
