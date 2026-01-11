from __future__ import annotations

import json
import asyncio
from pathlib import Path

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.types.input_file import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

from app.core.config import settings
from app.bot.api_client import ApiClient
from app.bot.polling import wait_task_done

router = Router()

MAX_TG_TEXT = 3500
PAYMENTS_DISABLED = True

PAYMENTS_DISABLED_MESSAGE = (
    "⚠️ Оплаты YooKassa временно отключены до прохождения модерации.\n"
    "Пополнение баланса будет доступно позже."
)

# Global runtime state
USER_MODE: dict[int, str] = {}               # preset_slug
USER_PENDING_TEXT: dict[int, str] = {}       # prompt (preset + details)
USER_PENDING_FILES: dict[int, list[str]] = {}  # photo file_ids (1-2)

USER_IMAGE_FLOW: dict[int, dict] = {}
USER_SUNO_FLOW: dict[int, dict] = {}
USER_GROK_FLOW: dict[int, dict] = {}
USER_PAY_FLOW: dict[int, dict] = {}

ALBUM_PHOTOS: dict[tuple[int, str], list[str]] = {}
ALBUM_TASKS: dict[tuple[int, str], asyncio.Task] = {}


def _truncate(text: str, limit: int = MAX_TG_TEXT) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 50] + "\n\n…(обрезано)…"


def _split_chunks(text: str, limit: int = MAX_TG_TEXT) -> list[str]:
    text = str(text or "")
    if len(text) <= limit:
        return [text]

    chunks = []
    s = text
    while len(s) > limit:
        cut = s.rfind("\n", 0, limit)
        if cut < max(500, limit // 3):
            cut = limit
        chunks.append(s[:cut].rstrip())
        s = s[cut:].lstrip()
    if s:
        chunks.append(s)
    return chunks


async def safe_edit_text(msg: Message, text: str, reply_markup=None):
    text = _truncate(text)
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramNetworkError:
        await msg.answer(text, reply_markup=reply_markup)
        return
    except TelegramBadRequest as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        if "message is too long" in s:
            await msg.answer(_truncate(text, 3500))
            return
        if "message can't be edited" in s or "message cannot be edited" in s:
            await msg.answer(text, reply_markup=reply_markup)
            return
        raise


def kb_bottom_panel() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖼 Изображения")],
            [KeyboardButton(text="🎵 Музыка"), KeyboardButton(text="✍️ Текст")],
            [KeyboardButton(text="👛 Баланс")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери раздел…",
    )


def load_image_presets() -> list[dict]:
    p = Path(__file__).resolve().parent / "image_presets.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("presets", [])


def _public_file_url(key: str) -> str:
    base = str(settings.API_PUBLIC_BASE_URL).rstrip("/")
    key = (key or "").lstrip("/")
    return f"{base}/files/{key}"


def kb_payments():
    kb = InlineKeyboardBuilder()
    kb.button(text="💳 99 ₽", callback_data="pay:topup:99")
    kb.button(text="💳 299 ₽", callback_data="pay:topup:299")
    kb.button(text="💳 459 ₽", callback_data="pay:topup:459")
    kb.button(text="💳 999 ₽", callback_data="pay:topup:999")
    kb.button(text="✍️ Другая сумма", callback_data="pay:topup:custom")
    kb.adjust(2, 2, 1)
    return kb.as_markup()


def kb_img_action():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Upscale (SeedVR)", callback_data="img:action:upscale")
    kb.button(text="🧠 Создать по тексту", callback_data="img:action:create")
    kb.button(text="🪄 Редактировать фото", callback_data="img:action:edit")
    kb.adjust(1)
    return kb.as_markup()


def kb_img_engine():
    kb = InlineKeyboardBuilder()
    kb.button(text="🍌 NanoBanana", callback_data="img:engine:nb")
    kb.button(text="🎨 GPTImage", callback_data="img:engine:gpt")
    kb.button(text="⬅️ Назад", callback_data="img:back:action")
    kb.adjust(2, 1)
    return kb.as_markup()


def kb_img_tier():
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Standard", callback_data="img:tier:std")
    kb.button(text="🔴 Pro", callback_data="img:tier:pro")
    kb.button(text="⬅️ Назад", callback_data="img:back:engine")
    kb.adjust(2, 1)
    return kb.as_markup()


def kb_img_size3():
    kb = InlineKeyboardBuilder()
    kb.button(text="1024x1024", callback_data="img:size:1024x1024")
    kb.button(text="1536x1024", callback_data="img:size:1536x1024")
    kb.button(text="1024x1536", callback_data="img:size:1024x1536")
    kb.button(text="⬅️ Назад", callback_data="img:back:tier")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def kb_img_presets():
    presets = load_image_presets()
    kb = InlineKeyboardBuilder()
    for p in presets:
        kb.button(text=p["title"], callback_data=f"img:preset:{p['id']}")
    kb.button(text="➡️ Без пресета", callback_data="img:preset:skip")
    kb.button(text="⬅️ Назад", callback_data="img:back:size")
    kb.adjust(2)
    return kb.as_markup()


def kb_seedvr_scale():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 x2", callback_data="img:seedvr:x2")
    kb.button(text="🔎 x4", callback_data="img:seedvr:x4")
    kb.button(text="⬅️ Назад", callback_data="img:back:action")
    kb.adjust(2, 1)
    return kb.as_markup()


def _img_flow(uid: int) -> dict:
    return USER_IMAGE_FLOW.setdefault(uid, {"step": "action", "meta": {}})


def _reset_all(uid: int):
    USER_MODE.pop(uid, None)
    USER_PENDING_TEXT.pop(uid, None)
    USER_PENDING_FILES.pop(uid, None)
    USER_IMAGE_FLOW.pop(uid, None)
    USER_SUNO_FLOW.pop(uid, None)
    USER_GROK_FLOW.pop(uid, None)
    USER_PAY_FLOW.pop(uid, None)


def _build_slug(flow: dict) -> str:
    return f"img_{flow['engine']}_{flow['tier']}_{flow['action']}"


def _set_common_meta(flow: dict):
    meta = flow.setdefault("meta", {})
    meta["translate_input"] = False
    meta.setdefault("num_images", 1)
    meta.setdefault("output_format", "png")


def _tier_apply_defaults(flow: dict):
    _set_common_meta(flow)
    meta = flow["meta"]
    engine = flow.get("engine")
    tier = flow.get("tier")

    if engine == "gpt":
        meta["quality"] = "medium" if tier == "pro" else "low"
        meta.setdefault("image_size", "1024x1024")

    if engine == "nb":
        meta.setdefault("resolution", "2K")
        if tier == "pro":
            meta["quality"] = "high"
        else:
            meta.pop("quality", None)


def _size_to_ratio(size: str) -> str:
    if size == "1024x1024":
        return "1:1"
    if size == "1024x1536":
        return "2:3"
    if size == "1536x1024":
        return "3:2"
    return "default"


def _meta_to_input_text(prompt: str, meta: dict) -> str:
    prompt = (prompt or "").strip()
    return prompt + "\n---\n" + json.dumps(meta or {}, ensure_ascii=False)


def _preset_prompt(preset_id: str) -> str:
    if preset_id == "skip":
        return ""
    presets = {p["id"]: p for p in load_image_presets()}
    return (presets.get(preset_id) or {}).get("prompt", "") or ""


def _album_key(uid: int, media_group_id: str) -> tuple[int, str]:
    return (uid, str(media_group_id))


async def _finalize_album(uid: int, media_group_id: str, message: Message):
    await asyncio.sleep(0.9)

    key = _album_key(uid, media_group_id)
    photos = ALBUM_PHOTOS.pop(key, [])
    ALBUM_TASKS.pop(key, None)

    flow = USER_IMAGE_FLOW.get(uid)
    if not flow or flow.get("step") != "wait_photos_edit":
        return

    if not photos:
        await message.answer("Не увидел фото. Отправь 1 или 2 фото одним сообщением (альбомом).")
        return

    if len(photos) > 2:
        photos = photos[:2]
        await message.answer("Принял первые 2 фото, остальные игнорю 🙂", reply_markup=kb_bottom_panel())

    USER_PENDING_FILES[uid] = photos
    flow["step"] = "wait_text_edit"

    if len(photos) == 1:
        await message.answer("Фото принято ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())
    else:
        await message.answer("2 фото принято ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())


def _file_kind_by_name(filename: str) -> str:
    low = (filename or "").lower()
    if any(low.endswith(x) for x in (".mp3", ".wav", ".ogg")):
        return "audio"
    if any(low.endswith(x) for x in (".mp4", ".mov", ".webm")):
        return "video"
    if any(low.endswith(x) for x in (".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    return "document"


async def _send_file_best_effort(message: Message, data: bytes, filename: str):
    kind = _file_kind_by_name(filename)

    # 1) preferred send methods
    try:
        if kind == "audio":
            await message.answer_audio(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
            return
        if kind == "video":
            await message.answer_video(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
            return
        if kind == "image":
            # Telegram likes photos, but fallback to document if needed
            try:
                await message.answer_photo(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
                return
            except Exception:
                await message.answer_document(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
                return

        await message.answer_document(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
        return
    except Exception:
        # 2) hard fallback to document
        await message.answer_document(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())


async def _run_and_deliver(message: Message, task_id: int):
    api = ApiClient()
    status_msg = await message.answer(
        f"🕒 Задача #{task_id} создана.\nСтатус: в очереди…",
        reply_markup=kb_bottom_panel(),
    )

    task = await wait_task_done(task_id, timeout_sec=1800)

    if task["status"] == "success":
        sent_anything = False

        key = task.get("result_file_key")
        if key:
            filename = key.split("/")[-1]
            try:
                data = await api.download_file(key)
                await safe_edit_text(
                    status_msg,
                    f"✅ Готово! (task #{task_id})\n\nФайл: {filename} ({len(data)/1024/1024:.2f} MB)",
                )
                await _send_file_best_effort(message, data, filename)
                sent_anything = True
            except Exception as e:
                await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})")
                pub = _public_file_url(key)
                await message.answer(
                    "⚠️ Результат готов, но не смог скачать/отправить файл.\n"
                    f"Файл: {filename}\n"
                    f"Причина: {e}\n\n"
                    f"✅ Ссылка на файл:\n{pub}",
                    reply_markup=kb_bottom_panel(),
                )
                sent_anything = True
        else:
            await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})")

        if task.get("result_text"):
            text = str(task["result_text"])
            parts = _split_chunks(text, MAX_TG_TEXT)
            total = len(parts)
            for i, part in enumerate(parts, start=1):
                if total == 1:
                    await message.answer(part, reply_markup=kb_bottom_panel())
                else:
                    await message.answer(f"({i}/{total})\n{part}", reply_markup=kb_bottom_panel())
            sent_anything = True

        if not sent_anything:
            await message.answer("✅ Готово! Но в ответе нет ни файла, ни текста.", reply_markup=kb_bottom_panel())

    else:
        await safe_edit_text(
            status_msg,
            f"❌ Ошибка (task #{task_id}): {task.get('error_message') or 'Unknown error'}",
        )


@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("🤖 GenBot\n\nВыбери раздел снизу 👇", reply_markup=kb_bottom_panel())


@router.message(F.text.in_({"/cancel", "Отмена"}))
async def cancel(message: Message):
    _reset_all(message.from_user.id)
    await message.answer("Ок, отменил ✅", reply_markup=kb_bottom_panel())


@router.message(F.text == "🖼 Изображения")
async def images_menu(message: Message):
    uid = message.from_user.id
    _reset_all(uid)
    USER_IMAGE_FLOW[uid] = {"step": "action", "meta": {}}
    await message.answer("🖼 Изображения\n\nВыбери действие:", reply_markup=kb_img_action())


@router.message(F.text == "🎵 Музыка")
async def suno_menu(message: Message):
    uid = message.from_user.id
    _reset_all(uid)
    USER_SUNO_FLOW[uid] = {"step": "title"}
    await message.answer(
        "🎵 Suno v5\n\n"
        "Шаг 1/3: Название песни (title)\n"
        "Напиши название:",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "✍️ Текст")
async def grok_menu(message: Message):
    uid = message.from_user.id
    _reset_all(uid)
    USER_GROK_FLOW[uid] = {"step": "prompt"}
    await message.answer(
        "✍️ Grok 4.1\n\n"
        "Напиши запрос одним сообщением.\n"
        "Если ответ будет длинный, пришлю частями (1/2, 2/2...).",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "👛 Баланс")
async def balance(message: Message):
    api = ApiClient()
    b = await api.get_balance(message.from_user.id)
    if PAYMENTS_DISABLED:
        await message.answer(
            f"👛 Баланс: {b['credits']} кредит(ов)\n\n{PAYMENTS_DISABLED_MESSAGE}",
            reply_markup=kb_bottom_panel(),
        )
        return
    await message.answer(
        f"👛 Баланс: {b['credits']} кредит(ов)\n\nВыбери сумму пополнения:",
        reply_markup=kb_payments(),
    )


@router.callback_query(F.data == "pay:topup:custom")
async def cb_pay_custom(cb: CallbackQuery):
    if PAYMENTS_DISABLED:
        await cb.message.answer(PAYMENTS_DISABLED_MESSAGE, reply_markup=kb_bottom_panel())
        await cb.answer("Оплаты временно отключены", show_alert=True)
        return
    uid = cb.from_user.id
    USER_PAY_FLOW[uid] = {"step": "amount"}
    await cb.message.answer(
        "✍️ Введи сумму пополнения в рублях одним сообщением.\n"
        "Пример: 550\n\n"
        "Ограничения: от 10 до 50000 ₽.\n"
        "Отмена: /cancel",
        reply_markup=kb_bottom_panel(),
    )
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("pay:topup:") & ~F.data.endswith(":custom"))
async def cb_topup(cb: CallbackQuery):
    if PAYMENTS_DISABLED:
        await cb.message.answer(PAYMENTS_DISABLED_MESSAGE, reply_markup=kb_bottom_panel())
        await cb.answer("Оплаты временно отключены", show_alert=True)
        return
    uid = cb.from_user.id
    try:
        amount = int(cb.data.split(":")[-1])
    except Exception:
        await cb.answer("Некорректная сумма", show_alert=True)
        return

    api = ApiClient()
    try:
        resp = await api.create_topup(uid, amount_rub=amount, description="Пополнение кредитов GenBot")
        url = resp.get("confirmation_url")
        if not url:
            await cb.answer("Не удалось получить ссылку на оплату", show_alert=True)
            return

        await cb.message.answer(
            f"💳 Оплата на {amount} ₽\n\n"
            f"Ссылка для оплаты:\n{url}\n\n"
            "Начисление кредитов через вебхук подключим следующим шагом.",
            reply_markup=kb_bottom_panel(),
        )
        await cb.answer("Ссылка готова ✅")
    except Exception as e:
        await cb.answer("Ошибка создания платежа", show_alert=True)
        await cb.message.answer(f"❌ Не смог создать платеж: {e}", reply_markup=kb_bottom_panel())


# ---- Images callbacks & main handler ----
@router.callback_query(F.data.startswith("img:back:"))
async def cb_back(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    where = cb.data.split(":")[-1]

    if where == "action":
        flow.clear()
        flow["step"] = "action"
        flow["meta"] = {}
        await safe_edit_text(cb.message, "🖼 Изображения\n\nВыбери действие:", reply_markup=kb_img_action())
        await cb.answer()
        return

    if where == "engine":
        flow["step"] = "engine"
        await safe_edit_text(cb.message, "Выбери движок:", reply_markup=kb_img_engine())
        await cb.answer()
        return

    if where == "tier":
        flow["step"] = "tier"
        await safe_edit_text(cb.message, "Выбери режим (Standard/Pro):", reply_markup=kb_img_tier())
        await cb.answer()
        return

    if where == "size":
        flow["step"] = "size"
        await safe_edit_text(cb.message, "Выбери размер:", reply_markup=kb_img_size3())
        await cb.answer()
        return

    await cb.answer()


@router.callback_query(F.data.startswith("img:action:"))
async def cb_action(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    action = cb.data.split(":")[-1]

    flow.clear()
    flow["meta"] = {}
    flow["action"] = action

    USER_PENDING_TEXT.pop(uid, None)
    USER_PENDING_FILES.pop(uid, None)

    if action == "upscale":
        flow["step"] = "seedvr"
        await safe_edit_text(cb.message, "✨ Upscale (SeedVR)\n\nВыбери увеличение:", reply_markup=kb_seedvr_scale())
    else:
        flow["step"] = "engine"
        await safe_edit_text(cb.message, "Выбери движок:", reply_markup=kb_img_engine())

    await cb.answer()


@router.callback_query(F.data.startswith("img:seedvr:"))
async def cb_seedvr(cb: CallbackQuery):
    uid = cb.from_user.id
    scale = cb.data.split(":")[-1]
    flow = _img_flow(uid)

    flow["step"] = "wait_file_seedvr"
    USER_MODE[uid] = "seedvr_x2" if scale == "x2" else "seedvr_x4"
    USER_PENDING_TEXT.pop(uid, None)

    await safe_edit_text(cb.message, f"✅ Upscale {scale} выбран.\n\nПришли изображение.")
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:engine:"))
async def cb_engine(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    engine = cb.data.split(":")[-1]
    flow["engine"] = engine
    flow["step"] = "tier"
    await safe_edit_text(cb.message, "Выбери режим (Standard/Pro):", reply_markup=kb_img_tier())
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:tier:"))
async def cb_tier(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    tier = cb.data.split(":")[-1]

    flow["tier"] = tier
    _tier_apply_defaults(flow)

    flow["step"] = "size"
    await safe_edit_text(cb.message, "Выбери размер:", reply_markup=kb_img_size3())
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:size:"))
async def cb_size(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    size = cb.data.split(":")[-1]

    _set_common_meta(flow)
    flow["meta"]["image_size"] = size

    if flow.get("engine") == "nb":
        flow["meta"]["aspect_ratio"] = _size_to_ratio(size)

    flow["step"] = "preset"
    await safe_edit_text(cb.message, "Пресет (опционально):", reply_markup=kb_img_presets())
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:preset:"))
async def cb_preset(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    preset_id = cb.data.split(":")[-1]

    flow["preset_id"] = preset_id
    _tier_apply_defaults(flow)

    USER_MODE[uid] = _build_slug(flow)
    USER_PENDING_TEXT[uid] = _preset_prompt(preset_id).strip()

    if flow["action"] == "create":
        flow["step"] = "wait_text_create"
        await safe_edit_text(
            cb.message,
            "✅ Готово.\n\n"
            "Теперь напиши промпт.\n"
            "Если выбрал пресет, можно просто уточнить детали.\n"
            "Отмена: /cancel",
        )
    else:
        flow["step"] = "wait_photos_edit"
        USER_PENDING_FILES[uid] = []
        await safe_edit_text(
            cb.message,
            "✅ Готово.\n\n"
            "Отправь 1 или 2 фото ОДНИМ сообщением (альбомом).\n"
            "После этого напиши промпт.\n\n"
            "Отмена: /cancel",
        )

    await cb.answer("Ок")


@router.message()
async def any_message(message: Message):
    uid = message.from_user.id

    panel_buttons = {"🖼 Изображения", "🎵 Музыка", "✍️ Текст", "👛 Баланс"}
    is_panel_button = message.text in panel_buttons if message.text else False

    # payment custom
    pf = USER_PAY_FLOW.get(uid)
    if pf and pf.get("step") == "amount" and message.text and not message.text.startswith("/") and not is_panel_button:
        s = message.text.strip().replace(" ", "")
        try:
            amount = int(s)
        except Exception:
            await message.answer("Напиши сумму числом. Пример: 550", reply_markup=kb_bottom_panel())
            return
        if amount < 10 or amount > 50000:
            await message.answer("Сумма должна быть от 10 до 50000 ₽.", reply_markup=kb_bottom_panel())
            return
        api = ApiClient()
        try:
            resp = await api.create_topup(uid, amount_rub=amount, description="Пополнение кредитов GenBot")
            url = resp.get("confirmation_url")
            if not url:
                await message.answer("Не удалось получить ссылку на оплату.", reply_markup=kb_bottom_panel())
                USER_PAY_FLOW.pop(uid, None)
                return
            await message.answer(
                f"💳 Оплата на {amount} ₽\n\nСсылка:\n{url}\n\n"
                "Начисление кредитов через вебхук подключим следующим шагом.",
                reply_markup=kb_bottom_panel(),
            )
        except Exception as e:
            await message.answer(f"❌ Ошибка создания платежа: {e}", reply_markup=kb_bottom_panel())
        USER_PAY_FLOW.pop(uid, None)
        return

    # suno flow
    sf = USER_SUNO_FLOW.get(uid)
    if sf and message.text and not message.text.startswith("/") and not is_panel_button:
        step = sf.get("step")
        if step == "title":
            sf["title"] = message.text.strip()
            sf["step"] = "tags"
            await message.answer(
                "Шаг 2/3: Музыкальные стили (tags)\n"
                "Напиши через запятую (например: pop, cinematic, upbeat):",
                reply_markup=kb_bottom_panel(),
            )
            return
        if step == "tags":
            sf["tags"] = message.text.strip()
            sf["step"] = "prompt"
            await message.answer(
                "Шаг 3/3: Подсказки (prompt)\n"
                "Опиши, о чём трек, настроение, инструменты и т.д.:",
                reply_markup=kb_bottom_panel(),
            )
            return
        if step == "prompt":
            sf["prompt"] = message.text.strip()
            meta = {"title": sf["title"], "tags": sf["tags"], "prompt": sf["prompt"]}
            input_text = "\n---\n" + json.dumps(meta, ensure_ascii=False)
            api = ApiClient()
            created = await api.create_task(uid, input_text, None, "suno")
            await _run_and_deliver(message, created["task_id"])
            USER_SUNO_FLOW.pop(uid, None)
            return

    # grok flow
    gf = USER_GROK_FLOW.get(uid)
    if gf and message.text and not message.text.startswith("/") and not is_panel_button:
        prompt = message.text.strip()
        api = ApiClient()
        created = await api.create_task(uid, prompt, None, "grok")
        await _run_and_deliver(message, created["task_id"])
        USER_GROK_FLOW.pop(uid, None)
        return

    input_photo_id = message.photo[-1].file_id if message.photo else None
    input_doc_id = message.document.file_id if message.document else None

    flow = USER_IMAGE_FLOW.get(uid)
    if flow and flow.get("step") == "wait_text_create":
        if message.photo or message.document:
            await message.answer(
                "Это режим 🧠 *Создать по тексту*.\n"
                "Фото сюда не нужно 🙂\n\n"
                "Если хочешь обработать фото — выбери 🪄 *Редактировать фото*.",
                reply_markup=kb_bottom_panel(),
            )
            return

        if message.text and not message.text.startswith("/") and not is_panel_button:
            user_text = message.text.strip()
            base_prompt = (USER_PENDING_TEXT.get(uid) or "").strip()
            final_prompt = (base_prompt + "\n\n" + user_text).strip() if base_prompt else user_text

            meta = flow.get("meta", {})
            meta["translate_input"] = False
            input_text = _meta_to_input_text(final_prompt, meta)

            api = ApiClient()
            created = await api.create_task(uid, input_text, None, USER_MODE.get(uid))
            await _run_and_deliver(message, created["task_id"])
            _reset_all(uid)
        return

    if flow and flow.get("step") == "wait_photos_edit":
        if message.text and not message.text.startswith("/") and not is_panel_button:
            await message.answer(
                "Сначала отправь 1 или 2 фото одним сообщением (альбомом), потом напиши промпт 🙂\n"
                "Отмена: /cancel",
                reply_markup=kb_bottom_panel(),
            )
            return

        if message.photo:
            fid = input_photo_id
            if message.media_group_id:
                key = _album_key(uid, str(message.media_group_id))
                ALBUM_PHOTOS.setdefault(key, []).append(fid)
                if key in ALBUM_TASKS:
                    ALBUM_TASKS[key].cancel()
                ALBUM_TASKS[key] = asyncio.create_task(_finalize_album(uid, str(message.media_group_id), message))
                return
            USER_PENDING_FILES[uid] = [fid]
            flow["step"] = "wait_text_edit"
            await message.answer("Фото принято ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())
            return

        if message.document:
            USER_PENDING_FILES[uid] = [input_doc_id]
            flow["step"] = "wait_text_edit"
            await message.answer("Файл принят ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())
            return

        return

    if flow and flow.get("step") == "wait_text_edit":
        if message.text and not message.text.startswith("/") and not is_panel_button:
            user_text = message.text.strip()
            base_prompt = (USER_PENDING_TEXT.get(uid) or "").strip()
            final_prompt = (base_prompt + "\n\n" + user_text).strip() if base_prompt else user_text

            photos = USER_PENDING_FILES.get(uid, [])
            if not photos:
                await message.answer("Не вижу фото. Отправь 1–2 фото одним сообщением (альбомом).", reply_markup=kb_bottom_panel())
                return

            meta = flow.get("meta", {})
            meta["translate_input"] = False

            if flow.get("engine") == "nb" and flow.get("action") == "edit":
                meta["tg_file_ids"] = photos[:2]
                file_id_for_api = photos[0]
            else:
                file_id_for_api = photos[0]

            input_text = _meta_to_input_text(final_prompt, meta)

            api = ApiClient()
            created = await api.create_task(uid, input_text, file_id_for_api, USER_MODE.get(uid))
            await _run_and_deliver(message, created["task_id"])
            _reset_all(uid)
        return

    if message.photo or message.document:
        preset_slug = USER_MODE.get(uid)
        if not preset_slug:
            await message.answer("Зайди в 🖼 Изображения и выбери действие 👇", reply_markup=kb_bottom_panel())
            return
        if preset_slug and "_create" in preset_slug:
            await message.answer(
                "Сейчас выбран режим *Создать по тексту*.\n"
                "Файл сюда не нужен 🙂\n\n"
                "Если хочешь обработать файл — выбери *Редактировать фото* или *Upscale*.",
                reply_markup=kb_bottom_panel(),
            )
            return

        input_tg_file_id = input_photo_id or input_doc_id
        api = ApiClient()
        created = await api.create_task(uid, USER_PENDING_TEXT.pop(uid, None), input_tg_file_id, preset_slug)
        await _run_and_deliver(message, created["task_id"])
        _reset_all(uid)
        return

    if message.text and not message.text.startswith("/") and not is_panel_button:
        await message.answer(
            "Выбери раздел снизу 👇\n"
            "🖼 Изображения / 🎵 Музыка / ✍️ Текст\n"
            "Отмена: /cancel",
            reply_markup=kb_bottom_panel(),
        )
