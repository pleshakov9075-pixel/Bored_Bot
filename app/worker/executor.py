from __future__ import annotations

from datetime import datetime, UTC
import mimetypes
import json
import time
import random
import logging

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.db.models import Task, TaskStatus
from app.db.session import SessionLocal
from app.genapi.client import GenApiClient
from app.presets.registry import get_preset
from app.storage.local import save_bytes
from app.worker.telegram_files import tg_download_file


def _log_task_event(
    *,
    event: str,
    task_id: int,
    preset: str,
    file_url: str | None,
    result_file_key: str | None,
    error_message: str | None,
) -> None:
    logger = logging.getLogger("task_events")
    try:
        payload = {
            "event": event,
            "task_id": task_id,
            "preset": preset,
            "file_url": file_url,
            "result_file_key": result_file_key,
            "error_message": error_message,
        }
        logger.info("task_event=%s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        logging.getLogger(__name__).warning("Failed to log task event", exc_info=True)


def _guess_mime(filename: str) -> str:
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"


def _parse_text_and_meta(input_text: str | None) -> tuple[str, dict]:
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
    for e in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".mp4", ".mov", ".webm"):
        if low.endswith(e):
            return e
    return ".bin"


def _download_with_retry(url: str, timeout_total: float = 300.0) -> bytes:
    deadline = time.time() + timeout_total
    delay = 1.0

    with httpx.Client(timeout=httpx.Timeout(60.0, connect=30.0), trust_env=False, follow_redirects=True) as client:
        while True:
            try:
                r = client.get(url)
                if r.status_code in (500, 502, 503, 504, 429):
                    if time.time() > deadline:
                        raise RuntimeError(f"Download failed by deadline: HTTP {r.status_code} {r.text[:200]}")
                    time.sleep(delay * (0.85 + random.random() * 0.3))
                    delay = min(delay * 1.6, 8.0)
                    continue

                r.raise_for_status()
                return r.content

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if time.time() > deadline:
                    raise RuntimeError(f"Download failed by deadline: {e}") from e
                time.sleep(delay * (0.85 + random.random() * 0.3))
                delay = min(delay * 1.6, 8.0)


def _collect_urls(x) -> list[str]:
    urls: list[str] = []

    def rec(v):
        if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")):
            urls.append(v)
            return
        if isinstance(v, dict):
            for vv in v.values():
                rec(vv)
            return
        if isinstance(v, list):
            for vv in v:
                rec(vv)
            return

    rec(x)
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _pick_best_url(urls: list[str]) -> str | None:
    if not urls:
        return None

    prio_ext = [
        ".mp3", ".wav",
        ".mp4", ".mov", ".webm",
        ".png", ".jpg", ".jpeg", ".webp", ".gif",
        ".zip",
    ]

    def score(u: str) -> tuple[int, int]:
        low = u.lower()
        penalty = 0
        if "cover" in low:
            penalty += 5
        if "/input_files/" in low:
            penalty += 4
        ext_rank = 999
        for i, ext in enumerate(prio_ext):
            if ext in low:
                ext_rank = i
                break
        return (ext_rank, penalty)

    return sorted(urls, key=score)[0]


def _grok_extract_text(payload: dict) -> str | None:
    try:
        ch = payload.get("choices")
        if isinstance(ch, list) and ch:
            m = ch[0].get("message") if isinstance(ch[0], dict) else None
            if isinstance(m, dict):
                c = m.get("content")
                if isinstance(c, str) and c.strip():
                    return c.strip()
    except Exception:
        pass
    return None


def _input_size_limit_bytes() -> int:
    return int(settings.MAX_INPUT_FILE_SIZE_MB) * 1024 * 1024


def _ensure_file_size(filename: str, content: bytes) -> None:
    limit = _input_size_limit_bytes()
    size = len(content or b"")
    if size > limit:
        raise RuntimeError(
            f"Слишком большой файл {filename} ({size / 1024 / 1024:.2f} МБ). "
            f"Лимит {settings.MAX_INPUT_FILE_SIZE_MB} МБ."
        )


def _ensure_file_count(count: int) -> None:
    if count > settings.MAX_INPUT_FILES:
        raise RuntimeError(f"Слишком много файлов: максимум {settings.MAX_INPUT_FILES}.")


def execute_task(task_id: int) -> None:
    db = SessionLocal()
    file_url_for_log: str | None = None
    result_file_key_for_log: str | None = None
    preset_slug = ""
    try:
        task = db.execute(select(Task).where(Task.id == task_id)).scalar_one()
        preset_slug = (task.preset_slug or "").strip().lower()
        preset = get_preset(preset_slug)

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

        gen = GenApiClient(
            settings.GENAPI_BASE_URL,
            settings.GENAPI_TOKEN,
            poll_timeout_sec=settings.TASK_TIMEOUT_SEC,
        )

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
            params["messages"] = [{"role": "user", "content": user_prompt}]
            params.setdefault("model", "grok-4-1-fast-reasoning")
            params.setdefault("stream", False)

        # ---- Image presets: img_* ----
        if preset.slug.startswith("img_"):
            if prompt_text:
                params["prompt"] = prompt_text

            params["translate_input"] = False

            allowed = {
                "aspect_ratio",
                "image_size",
                "quality",
                "resolution",
                "num_images",
                "output_format",
                "translate_input",
                "tg_file_ids",
            }
            for k, v in (meta or {}).items():
                if k in allowed and v is not None:
                    params[k] = v

        # ---- download single file if needed by functions ----
        filename = content = mime = None
        if preset.provider_target == "function" and preset.input_kind != "none":
            if not task.input_tg_file_id:
                raise RuntimeError("No input file. Send image/audio file.")
            filename, content = tg_download_file(settings.BOT_TOKEN, task.input_tg_file_id)
            _ensure_file_size(filename, content)
            mime = _guess_mime(filename)

        # ---- run ----
        if preset.provider_target == "function":
            files = None
            if preset.input_kind != "none":
                files = {preset.input_field: (filename, content, mime)}

            request_id = gen.submit_function(
                function_id=preset.provider_id,
                implementation=preset.implementation or "default",
                files=files or {},
                params=params,
            )

        elif preset.provider_target == "network":
            if preset.input_kind != "none":
                tg_file_ids: list[str] = []
                v = (meta or {}).get("tg_file_ids")
                if isinstance(v, list):
                    tg_file_ids = [str(x) for x in v if x]

                if not tg_file_ids:
                    if not task.input_tg_file_id:
                        raise RuntimeError("No input file. Send image file.")
                    tg_file_ids = [task.input_tg_file_id]

                _ensure_file_count(len(tg_file_ids))

                public_base = str(settings.API_PUBLIC_BASE_URL).rstrip("/")
                urls: list[str] = []
                for idx, fid in enumerate(tg_file_ids, start=1):
                    fn, body = tg_download_file(settings.BOT_TOKEN, fid)
                    _ensure_file_size(fn, body)
                    ext = _ext_from_filename(fn)
                    input_key = f"uploads/task_{task_id}_{preset.slug}_{idx}{ext}"
                    save_bytes(input_key, body)
                    urls.append(f"{public_base}/files/{input_key}")

                # ✅ Теперь и для GPT и для Nano используем image_urls
                if preset.input_field == "image_urls":
                    params["image_urls"] = urls
                else:
                    params[preset.input_field] = urls[0]

            params["translate_input"] = False
            _log_task_event(
                event="submit_network",
                task_id=task_id,
                preset=preset.slug,
                file_url=None,
                result_file_key=None,
                error_message=None,
            )

            request_id = gen.submit_network(
                network_id=preset.provider_id,
                files=None,
                params=params,
            )

        else:
            raise RuntimeError(f"Unsupported provider_target={preset.provider_target}")

        # ---- poll ----
        result = gen.poll(request_id, timeout_sec=settings.TASK_TIMEOUT_SEC)
        if result.status != "success":
            raise RuntimeError(f"GenAPI failed: {result.payload}")

        # ✅ Grok fallback: text from payload
        if preset.slug == "grok" and not (result.text or "").strip():
            t = _grok_extract_text(result.payload)
            if t:
                result.text = t

        # ✅ Suno: берём ТОЛЬКО mp3/wav, игнорируем обложку
        file_url = result.file_url
        all_urls = _collect_urls(result.payload)
        if preset.slug == "suno":
            audio_urls = [u for u in all_urls if any(ext in u.lower() for ext in (".mp3", ".wav"))]
            if audio_urls:
                file_url = _pick_best_url(audio_urls)

        # ✅ SeedVR / general: если extractor промахнулся, выберем лучший url по расширению
        if not file_url and all_urls:
            file_url = _pick_best_url(all_urls)
        file_url_for_log = file_url

        # ---- store result ----
        if file_url:
            out_bytes = _download_with_retry(file_url, timeout_total=600.0)

            low_url = (file_url or "").lower()
            ext = ".bin"
            for e in (".mp3", ".wav", ".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".json"):
                if e in low_url:
                    ext = e
                    break

            key = f"results/task_{task_id}_{preset.slug}{ext}"
            save_bytes(key, out_bytes)
            result_file_key_for_log = key

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
        _log_task_event(
            event="task_success",
            task_id=task_id,
            preset=preset.slug,
            file_url=file_url_for_log,
            result_file_key=result_file_key_for_log,
            error_message=None,
        )

    except Exception as e:
        error_message = str(e)
        db.rollback()
        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                status=TaskStatus.failed,
                error_message=error_message,
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()
        _log_task_event(
            event="task_failed",
            task_id=task_id,
            preset=preset_slug or "unknown",
            file_url=file_url_for_log,
            result_file_key=result_file_key_for_log,
            error_message=error_message,
        )
    finally:
        db.close()
