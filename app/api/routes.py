from datetime import datetime
import io
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

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


# -----------------------
# Public files for GenAPI callbacks / image_urls
# -----------------------
@router.get("/files/{key:path}")
def public_file(key: str):
    """
    Публичная раздача файлов для GenAPI (image_urls/input_files).
    Никаких ключей. Важно: отдаём только из локального data/files.
    """
    try:
        body = read_bytes(key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")

    filename = key.split("/")[-1]
    return StreamingResponse(
        io.BytesIO(body),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


# -----------------------
# Internal tasks
# -----------------------
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
            db.commit()

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
            "preset_slug": task.preset_slug,
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


# -----------------------
# Balance
# -----------------------
@router.get("/internal/balance/{tg_user_id}")
def get_balance(tg_user_id: int, x_api_key: str | None = Header(default=None)):
    require_internal_key(x_api_key)
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.tg_user_id == int(tg_user_id))).scalar_one_or_none()
        if not user:
            # Создаём пользователя лениво
            user = User(tg_user_id=int(tg_user_id), created_at=datetime.utcnow())
            db.add(user)
            db.flush()
            bal = Balance(user_id=user.id, credits=0)
            db.add(bal)
            db.commit()
        bal = db.execute(select(Balance).where(Balance.user_id == user.id)).scalar_one()
        return {"tg_user_id": int(tg_user_id), "credits": int(bal.credits)}
    finally:
        db.close()


# -----------------------
# YooKassa (каркас)
# -----------------------
@router.post("/internal/payments/topup")
def create_topup_payment(payload: dict[str, Any], x_api_key: str | None = Header(default=None)):
    """
    Создаёт платеж YooKassa и возвращает confirmation_url.
    payload:
      tg_user_id: int
      amount_rub: int (например 99)
      description: str
    """
    require_internal_key(x_api_key)

    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise HTTPException(status_code=400, detail="YooKassa is not configured")

    tg_user_id = int(payload["tg_user_id"])
    amount_rub = int(payload.get("amount_rub", 0))
    description = str(payload.get("description") or "Top-up credits")

    if amount_rub <= 0:
        raise HTTPException(status_code=400, detail="amount_rub must be > 0")

    # SDK import here to keep requirements optional until you enable it
    from yookassa import Configuration, Payment  # type: ignore

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY

    idempotence_key = f"tg{tg_user_id}-{datetime.utcnow().timestamp()}"

    payment = Payment.create(
        {
            "amount": {"value": f"{amount_rub}.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": settings.YOOKASSA_RETURN_URL or "https://t.me/",
            },
            "capture": True,
            "description": description,
            "metadata": {
                "tg_user_id": str(tg_user_id),
                "purpose": "credits_topup",
            },
        },
        idempotence_key,
    )

    return {
        "payment_id": payment.id,
        "status": payment.status,
        "confirmation_url": (payment.confirmation or {}).get("confirmation_url"),
    }
