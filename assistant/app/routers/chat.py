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
    result = tools.handle_chat(user, conversation["id"], message, document_id=body.document_id)
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
