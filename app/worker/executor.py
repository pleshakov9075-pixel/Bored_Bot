from __future__ import annotations

from datetime import datetime, UTC
import mimetypes
import json

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


def _parse_text_and_meta(input_text: str | None) -> tuple[str, dict]:
    """
    Формат:
      <prompt text>
      ---
      {json meta}

    Для Suno можно отправлять только meta (prompt_text будет пустой).
    """
    if not input_text:
        return "", {}
    raw = str(input_text)

    sep = "\n---\n"
    if sep not in raw:
        return raw.strip(), {}

    prompt, meta_raw = raw.split(sep, 1)
    prompt = prompt.strip()

    meta = {}
    try:
        meta = json.loads(meta_raw.strip())
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        meta = {}

    return prompt, meta


def _ext_from_filename(filename: str | None) -> str:
    low = (filename or "").lower()
    for e in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if low.endswith(e):
            return e
    return ".bin"


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

        params: dict = dict(preset.params or {})
        prompt_text, meta = _parse_text_and_meta(task.input_text)

        # ---- Special: Suno (network) ----
        if preset.slug == "suno":
            title = (meta.get("title") or "").strip()
            tags = (meta.get("tags") or "").strip()
            prompt = (meta.get("prompt") or prompt_text or "").strip()

            if not title or not tags or not prompt:
                raise RuntimeError("Suno requires title, tags, prompt")

            params["title"] = title
            params["tags"] = tags
            params["prompt"] = prompt
            params["model"] = "v5"
            params["translate_input"] = False

        # ---- Special: Grok (network) ----
        if preset.slug == "grok":
            user_prompt = (prompt_text or "").strip()
            if not user_prompt:
                raise RuntimeError("Grok requires prompt text")

            messages = [{"role": "user", "content": user_prompt}]
            params["messages"] = json.dumps(messages, ensure_ascii=False)
            params.setdefault("model", "grok-4-1-fast-reasoning")
            params.setdefault("stream", False)

        # ---- Image presets: img_* ----
        if preset.slug.startswith("img_"):
            if prompt_text:
                params["prompt"] = prompt_text

            # всегда выключаем автоперевод
            params["translate_input"] = False

            allowed = {
                "aspect_ratio",
                "image_size",
                "quality",
                "resolution",
                "num_images",
                "output_format",
                "translate_input",
                "tg_file_ids",  # служебное поле для multi-image
                "title", "tags", "prompt", "model", "messages", "stream"  # безопасно для универсальности
            }
            for k, v in (meta or {}).items():
                if k in allowed and v is not None:
                    params[k] = v

        # ---- download single file if needed by functions OR by networks w/ img2img ----
        filename = content = mime = None
        if preset.provider_target == "function" and preset.input_kind != "none":
            if not task.input_tg_file_id:
                raise RuntimeError("No input file. Send image/audio file.")
            filename, content = tg_download_file(settings.BOT_TOKEN, task.input_tg_file_id)
            mime = _guess_mime(filename)

        # ---- run ----
        if preset.provider_target == "function":
            files = None
            if preset.input_kind != "none":
                files = {preset.input_field: (filename, content, mime)}

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
            # network:
            # - text2img: input_kind == "none" -> only params
            # - img2img: input_kind == "image" -> 1 or 2 images
            if preset.input_kind != "none":
                # 1) collect tg file ids from meta (preferred)
                tg_file_ids: list[str] = []
                v = (meta or {}).get("tg_file_ids")
                if isinstance(v, list):
                    tg_file_ids = [str(x) for x in v if x]

                # fallback to task.input_tg_file_id
                if not tg_file_ids:
                    if not task.input_tg_file_id:
                        raise RuntimeError("No input file. Send image file.")
                    tg_file_ids = [task.input_tg_file_id]

                # 2) download each file and create public urls
                public_base = str(settings.API_PUBLIC_BASE_URL).rstrip("/")
                urls: list[str] = []
                for idx, fid in enumerate(tg_file_ids, start=1):
                    fn, body = tg_download_file(settings.BOT_TOKEN, fid)
                    ext = _ext_from_filename(fn)
                    input_key = f"uploads/task_{task_id}_{preset.slug}_{idx}{ext}"
                    save_bytes(input_key, body)
                    urls.append(f"{public_base}/files/{input_key}")

                # 3) inject into params: multi-image for nano uses image_urls
                if preset.input_field == "image_urls":
                    params["image_urls"] = urls
                else:
                    params[preset.input_field] = urls[0]

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
            with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), trust_env=False) as client:
                with client.stream("GET", result.file_url) as r:
                    r.raise_for_status()
                    out_bytes = b"".join(chunk for chunk in r.iter_bytes())

            low_url = (result.file_url or "").lower()
            ext = ".bin"
            for e in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".mp4", ".mov", ".mp3", ".wav", ".glb", ".obj", ".txt", ".json"):
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
