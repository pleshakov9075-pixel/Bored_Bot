import asyncio

from app.bot.api_client import ApiClient
from app.core.config import settings


async def wait_task_done(task_id: int, timeout_sec: int | None = None) -> dict:
    api = ApiClient()
    timeout_sec = timeout_sec or settings.TASK_TIMEOUT_SEC
    deadline = asyncio.get_event_loop().time() + timeout_sec
    delay = 1.0

    while True:
        task = await api.get_task(task_id)
        status = task["status"]

        if status in ("success", "failed"):
            return task

        if asyncio.get_event_loop().time() > deadline:
            return {"task_id": task_id, "status": "failed", "error_message": "Timeout waiting result"}

        await asyncio.sleep(delay)
        delay = min(delay * 1.4, 5.0)
