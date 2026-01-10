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
        preset = get_preset((task.preset_slug or "").strip().lower())

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
            raise RuntimeError("GENAPI_TOKEN is empty in .env")

        gen = GenApiClient(settings.GENAPI_BASE_URL, settings.GENAPI_TOKEN)

        filename = None
        content = None
        mime = None

        if preset.input_kind != "none":
            if not task.input_tg_file_id:
                raise RuntimeError("No input file. Send image/audio file.")
            filename, content = tg_download_file(settings.BOT_TOKEN, task.input_tg_file_id)
            mime = _guess_mime(filename)

        # ---- build params/files ----
        params: dict = dict(preset.params or {})
        files = None

        # Smart prompt mode for outpainting:
        # - preset.params["prompt"] is a master prompt
        # - task.input_text is user's extra instruction
        if preset.slug == "outpainting":
            user_text = (task.input_text or "").strip()
            base_prompt = (params.get("prompt") or "").strip()
            if user_text:
                if base_prompt:
                    params["prompt"] = f"{base_prompt}\nUser request: {user_text}"
                else:
                    params["prompt"] = user_text

        if preset.provider_target == "function":
            if preset.input_kind != "none":
                files = {preset.input_field: (filename, content, mime)}

            # Special case kept: analyze-call (audio + script)
            if preset.slug == "analyze-call":
                request_id = gen.submit_function(
                    function_id="analyze-call",
                    implementation="claude",
                    files={"audio": (filename, content, mime)},
                    params={
                        "model": "claude-3-7-sonnet-20250219",
                        "script": task.input_text or None,
                    },
                )
            else:
                request_id = gen.submit_function(
                    function_id=preset.provider_id,
                    implementation=preset.implementation or "default",
                    files=files,
                    params=params,
                )

        elif preset.provider_target == "network":
            if preset.input_kind == "none":
                raise RuntimeError("Network preset requires input file.")

            # For networks we always provide a public URL in params[preset.input_field]
            ext = ".bin"
            low = (filename or "").lower()
            for e in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                if low.endswith(e):
                    ext = e
                    break

            input_key = f"uploads/task_{task_id}_{preset.slug}{ext}"
            save_bytes(input_key, content)

            public_base = settings.API_PUBLIC_BASE_URL.rstrip("/")
            params[preset.input_field] = f"{public_base}/files/{input_key}"

            request_id = gen.submit_network(
                network_id=preset.provider_id,
                files=None,
                params=params,
            )

        else:
            raise RuntimeError(f"Unsupported provider_target={preset.provider_target}")

        # ---- poll ----
        result = gen.poll(request_id, timeout_sec=600)
        if result.status != "success":
            raise RuntimeError(f"GenAPI failed: {result.payload}")

        # ---- store result ----
        if result.file_url:
            # Streaming download to avoid timeouts on large files
            with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), trust_env=False) as client:
                with client.stream("GET", result.file_url) as r:
                    r.raise_for_status()
                    out_bytes = b"".join(chunk for chunk in r.iter_bytes())

            low_url = (result.file_url or "").lower()
            ext = ".bin"
            for e in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".mov", ".glb", ".obj", ".txt", ".json"):
                if e in low_url:
                    ext = e
                    break

            key = f"results/task_{task_id}_{preset.slug}{ext}"
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
            db.commit()
        else:
            db.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    status=TaskStatus.success,
                    result_file_key=None,
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
