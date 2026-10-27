"""Personal notes: CRUD + semantic search over the vector store."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import auth, db
from ..vectorstore import store

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteBody(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(default="", max_length=50000)
    tags: str = Field(default="", max_length=200)


def _require_note(user: dict, note_id: int) -> dict:
    note = db.get_note(user["id"], note_id)
    if note is None:
        raise HTTPException(404, "Note not found.")
    return note


@router.post("", status_code=201)
def create_note(body: NoteBody, user: dict = Depends(auth.get_current_user)):
    note = db.create_note(user["id"], body.title.strip(), body.body, body.tags.strip())
    store.index_note(user["id"], note)
    return note


@router.get("")
def list_notes(user: dict = Depends(auth.get_current_user)):
    return {"notes": db.list_notes(user["id"])}


@router.get("/search")
def search_notes(q: str = Query(min_length=1, max_length=500), user: dict = Depends(auth.get_current_user)):
    hits = store.search(user["id"], q, top_k=8, source_types=("note",))
    seen: dict[int, dict] = {}
    for hit in hits:  # best chunk per note
        if hit.note_id is not None and hit.note_id not in seen:
            seen[hit.note_id] = hit.citation()
    return {"query": q, "results": list(seen.values())}


@router.get("/{note_id}")
def get_note(note_id: int, user: dict = Depends(auth.get_current_user)):
    return _require_note(user, note_id)


@router.put("/{note_id}")
def update_note(note_id: int, body: NoteBody, user: dict = Depends(auth.get_current_user)):
    _require_note(user, note_id)
    note = db.update_note(user["id"], note_id, body.title.strip(), body.body, body.tags.strip())
    store.index_note(user["id"], note)
    return note


@router.delete("/{note_id}")
def delete_note(note_id: int, user: dict = Depends(auth.get_current_user)):
    _require_note(user, note_id)
    store.remove_note(user["id"], note_id)
    db.delete_note(user["id"], note_id)
    return {"deleted": True}
