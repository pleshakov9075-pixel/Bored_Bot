from datetime import datetime
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse
import io

from sqlalchemy import select
from app.core.config import settings
from app.db.session import SessionLocal
from app.db.models import User, Balance, Task, TaskStatus
from app.storage.local import read_bytes

router = APIRouter()


def require_internal_key(x_api_key: str | None):
    if x_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/internal/tasks")
def create_task(payload: dict, x_api_key: str | None = Header(default=None)):
    """
    payload:
      tg_user_id: int
      input_text: str | None
      input_tg_file_id: str | None
      preset_slug: str
    """
    require_internal_key(x_api_key)

    tg_user_id = int(payload["tg_user_id"])
    input_text = payload.get("input_text")
    input_tg_file_id = payload.get("input_tg_file_id")
    preset_slug = payload.get("preset_slug", "dummy")

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
        if not user:
            user = User(tg_user_id=tg_user_id, created_at=datetime.utcnow())
            db.add(user)
            db.flush()
            db.add(Balance(user_id=user.id, credits=0))
            db.flush()

        task = Task(
            user_id=user.id,
            preset_slug=preset_slug,
            status=TaskStatus.queued,
            input_text=input_text,
            input_tg_file_id=input_tg_file_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return {"task_id": task.id, "status": task.status}
    finally:
        db.close()


@router.get("/internal/tasks/{task_id}")
def get_task(task_id: int, x_api_key: str | None = Header(default=None)):
    require_internal_key(x_api_key)
    db = SessionLocal()
    try:
        task = db.execute(select(Task).where(Task.id == task_id)).scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "task_id": task.id,
            "status": task.status,
            "result_file_key": task.result_file_key,
            "result_text": task.result_text,
            "error_message": task.error_message,
        }
    finally:
        db.close()


@router.get("/internal/files/{key:path}")
def download_file(key: str, x_api_key: str | None = Header(default=None)):
    require_internal_key(x_api_key)

    try:
        body = read_bytes(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    filename = key.split("/")[-1]
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
