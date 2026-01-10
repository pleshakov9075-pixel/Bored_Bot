from __future__ import annotations

from datetime import datetime, UTC
import mimetypes

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.db.models import Task, TaskStatus
from app.db.session import SessionLocal
from app.genapi.client import GenApiClient
from app.presets.registry import get_preset
from app.storage.local import save_bytes
from app.worker.telegram_files import tg_download_file


def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def execute_task(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.execute(select(Task).where(Task.id == task_id)).scalar_one()
        preset = get_preset(task.preset_slug)

        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                status=TaskStatus.processing,
                updated_at=datetime.now(UTC),
                error_message=None,
            )
        )
        db.commit()

        if not settings.GENAPI_TOKEN:
            raise RuntimeError("GENAPI_TOKEN is empty")

        gen = GenApiClient(settings.GENAPI_BASE_URL, settings.GENAPI_TOKEN)

        filename = None
        content = None
        mime = None

        if preset.input_kind != "none":
            if not task.input_tg_file_id:
                raise RuntimeError("No input file")
            filename, content = tg_download_file(
                settings.BOT_TOKEN, task.input_tg_file_id
            )
            mime = _guess_mime(filename)

        files = None
        params = dict(preset.params or {})

        # --- FUNCTION: всегда multipart ---
        if preset.provider_target == "function":
            if preset.input_kind != "none":
                files = {preset.input_field: (filename, content, mime)}

            request_id = gen.submit_function(
                function_id=preset.provider_id,
                implementation=preset.implementation or "default",
                files=files,
                params=params,
            )

        # --- NETWORK: всегда URL ---
        elif preset.provider_target == "network":
            if preset.input_kind == "none":
                raise RuntimeError("Network requires input file")

            ext = ".bin"
            low = (filename or "").lower()
            for e in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                if low.endswith(e):
                    ext = e
                    break

            key = f"uploads/task_{task_id}_{preset.slug}{ext}"
            save_bytes(key, content)

            base = settings.API_PUBLIC_BASE_URL.rstrip("/")
            params[preset.input_field] = f"{base}/files/{key}"

            request_id = gen.submit_network(
                network_id=preset.provider_id,
                files=None,
                params=params,
            )

        else:
            raise RuntimeError(f"Unsupported provider_target={preset.provider_target}")

        # --- poll ---
        result = gen.poll(request_id, timeout_sec=600)
        if result.status != "success":
            raise RuntimeError(f"GenAPI failed: {result.payload}")

        # --- save result ---
        if result.file_url:
            with httpx.Client(timeout=180) as client:
                r = client.get(result.file_url)
                r.raise_for_status()
                out_bytes = r.content

            key = f"results/task_{task_id}_{preset.slug}"
            save_bytes(key, out_bytes)

            db.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    status=TaskStatus.success,
                    result_file_key=key,
                    result_text=result.text or "Готово ✅",
                    updated_at=datetime.now(UTC),
                )
            )
        else:
            db.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    status=TaskStatus.success,
                    result_text=result.text or "Готово ✅",
                    updated_at=datetime.now(UTC),
                )
            )

        db.commit()

    except Exception as e:
        db.rollback()
        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                status=TaskStatus.failed,
                error_message=str(e),
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
    finally:
        db.close()
