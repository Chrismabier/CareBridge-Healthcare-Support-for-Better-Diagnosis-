"""Chat + conversation history endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db, tools

router = APIRouter(prefix="/api", tags=["chat"])


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=6000)
    conversation_id: int | None = None
    document_id: int | None = None  # scope retrieval to one document ("ask this PDF")
    # Browser-direct BYOK: client will call its own LLM provider with the
    # grounded prompt and persist the answer via /chat/{id}/complete.
    client_llm: bool = False


class CompleteBody(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    citations: list[dict] = Field(default_factory=list, max_length=20)
    tools: list[str] = Field(default_factory=list, max_length=10)


class ConversationBody(BaseModel):
    title: str = Field(default="New chat", max_length=120)


@router.post("/conversations", status_code=201)
def create_conversation(body: ConversationBody, user: dict = Depends(auth.get_current_user)):
    return db.create_conversation(user["id"], body.title.strip() or "New chat")


@router.get("/conversations")
def list_conversations(user: dict = Depends(auth.get_current_user)):
    return {"conversations": db.list_conversations(user["id"])}


@router.get("/conversations/{conversation_id}/messages")
def list_messages(conversation_id: int, user: dict = Depends(auth.get_current_user)):
    if db.get_conversation(user["id"], conversation_id) is None:
        raise HTTPException(404, "Conversation not found.")
    return {"messages": db.list_messages(conversation_id)}


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: int, user: dict = Depends(auth.get_current_user)):
    if not db.delete_conversation(user["id"], conversation_id):
        raise HTTPException(404, "Conversation not found.")
    return {"deleted": True}


@router.post("/chat")
def chat(body: ChatBody, user: dict = Depends(auth.get_current_user)):
    message = body.message.strip()
    if body.document_id is not None and db.get_document(user["id"], body.document_id) is None:
        raise HTTPException(404, "That document no longer exists.")
    if body.conversation_id is not None:
        conversation = db.get_conversation(user["id"], body.conversation_id)
        if conversation is None:
            raise HTTPException(404, "Conversation not found.")
    else:
        conversation = db.create_conversation(user["id"])

    db.add_message(conversation["id"], "user", message)
    result = tools.handle_chat(user, conversation["id"], message,
                                document_id=body.document_id, client_llm=body.client_llm)
    if result.pending_llm is not None:
        # Don't persist an assistant message yet: the browser asks its own
        # provider with ``pending_llm.messages`` and POSTs the final text to
        # /chat/{id}/complete. ``offline_reply`` is the ready-made fallback.
        return {
            "conversation_id": conversation["id"],
            "pending_llm": result.pending_llm,
            "offline_reply": result.reply,
            "citations": result.citations,
            "tools_used": result.tools_used,
            "refresh": result.refresh,
        }
    saved = db.add_message(conversation["id"], "assistant", result.reply,
                           citations=result.citations, tools=result.tools_used)
    return {
        "conversation_id": conversation["id"],
        "message_id": saved["id"],
        "reply": result.reply,
        "citations": result.citations,
        "tools_used": result.tools_used,
        "refresh": result.refresh,
    }


@router.post("/chat/{conversation_id}/complete")
def complete_chat(conversation_id: int, body: CompleteBody,
                  user: dict = Depends(auth.get_current_user)):
    """Persist a browser-generated (BYOK) assistant reply to the history."""
    if db.get_conversation(user["id"], conversation_id) is None:
        raise HTTPException(404, "Conversation not found.")
    saved = db.add_message(conversation_id, "assistant", body.content.strip(),
                           citations=body.citations, tools=body.tools)
    return {"conversation_id": conversation_id, "message_id": saved["id"]}
