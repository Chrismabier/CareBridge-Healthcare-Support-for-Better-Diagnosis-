"""Task lists and reminders (including the due-reminder polling feed)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import auth, db

router = APIRouter(prefix="/api", tags=["tasks & reminders"])


def _parse_iso(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, f"{field} must be an ISO date/time like 2026-11-02T09:00:00Z.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


# --------------------------------------------------------------------- tasks

class TaskBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(default="", max_length=2000)
    list_name: str = Field(default="Tasks", max_length=80)
    priority: str = Field(default="normal", pattern="^(low|normal|high)$")
    due_at: str | None = None


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    details: str | None = Field(default=None, max_length=2000)
    list_name: str | None = Field(default=None, max_length=80)
    priority: str | None = Field(default=None, pattern="^(low|normal|high)$")
    due_at: str | None = None
    done: bool | None = None


@router.post("/tasks", status_code=201)
def create_task(body: TaskBody, user: dict = Depends(auth.get_current_user)):
    return db.create_task(user["id"], body.title.strip(), body.details, body.list_name.strip(),
                          body.priority, _parse_iso(body.due_at, "due_at"))


@router.get("/tasks")
def list_tasks(include_done: bool = True, user: dict = Depends(auth.get_current_user)):
    return {"tasks": db.list_tasks(user["id"], include_done=include_done)}


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, body: TaskPatch, user: dict = Depends(auth.get_current_user)):
    fields = body.model_dump(exclude_unset=True)
    if "due_at" in fields:
        fields["due_at"] = _parse_iso(fields["due_at"], "due_at")
    if "title" in fields and fields["title"]:
        fields["title"] = fields["title"].strip()
    task = db.update_task(user["id"], task_id, **fields)
    if task is None:
        raise HTTPException(404, "Task not found.")
    return task


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, user: dict = Depends(auth.get_current_user)):
    if not db.delete_task(user["id"], task_id):
        raise HTTPException(404, "Task not found.")
    return {"deleted": True}


# ----------------------------------------------------------------- reminders

class ReminderBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    remind_at: str = Field(min_length=4, max_length=40)
    task_id: int | None = None


class ReminderPatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    remind_at: str | None = None
    done: bool | None = None


@router.post("/reminders", status_code=201)
def create_reminder(body: ReminderBody, user: dict = Depends(auth.get_current_user)):
    remind_at = _parse_iso(body.remind_at, "remind_at")
    if body.task_id is not None and db.get_task(user["id"], body.task_id) is None:
        raise HTTPException(404, "Task not found.")
    return db.create_reminder(user["id"], body.title.strip(), remind_at, body.task_id)


@router.get("/reminders")
def list_reminders(include_done: bool = False, user: dict = Depends(auth.get_current_user)):
    return {"reminders": db.list_reminders(user["id"], include_done=include_done)}


@router.get("/reminders/due")
def due_reminders(user: dict = Depends(auth.get_current_user)):
    """Reminders that have just come due (marked notified as a side effect).

    The web UI polls this every ~30s and fires a toast / browser notification.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {"due": db.due_reminders(user["id"], now), "now": now}


@router.patch("/reminders/{reminder_id}")
def update_reminder(reminder_id: int, body: ReminderPatch, user: dict = Depends(auth.get_current_user)):
    fields = body.model_dump(exclude_unset=True)
    if "remind_at" in fields:
        fields["remind_at"] = _parse_iso(fields["remind_at"], "remind_at")
    if "title" in fields and fields["title"]:
        fields["title"] = fields["title"].strip()
    reminder = db.update_reminder(user["id"], reminder_id, **fields)
    if reminder is None:
        raise HTTPException(404, "Reminder not found.")
    return reminder


@router.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int, user: dict = Depends(auth.get_current_user)):
    if not db.delete_reminder(user["id"], reminder_id):
        raise HTTPException(404, "Reminder not found.")
    return {"deleted": True}
