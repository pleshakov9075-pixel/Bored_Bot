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
from aiogram.exceptions import TelegramBadRequest

from app.bot.api_client import ApiClient
from app.bot.polling import wait_task_done
from app.presets.registry import get_preset

router = Router()

MAX_TG_TEXT = 3500

# Runtime state
USER_MODE: dict[int, str] = {}            # preset_slug selected
USER_PENDING_TEXT: dict[int, str] = {}    # prompt (preset prompt + user details)
USER_PENDING_FILES: dict[int, list[str]] = {}  # list of tg file_id (1-2 photos)
USER_IMAGE_FLOW: dict[int, dict] = {}     # flow state + meta

# Album buffers (Telegram sends album as multiple messages with same media_group_id)
ALBUM_PHOTOS: dict[tuple[int, str], list[str]] = {}     # (user_id, media_group_id) -> [file_id...]
ALBUM_TASKS: dict[tuple[int, str], asyncio.Task] = {}   # finalize timers


def _truncate(text: str, limit: int = MAX_TG_TEXT) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 50] + "\n\n…(обрезано)…"


async def safe_edit_text(msg: Message, text: str, reply_markup=None):
    text = _truncate(text)
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
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
            [KeyboardButton(text="🔊 Аудио"), KeyboardButton(text="✍️ Тексты")],
            [KeyboardButton(text="👛 Баланс")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери раздел…",
    )


def load_image_presets() -> list[dict]:
    # app/bot/image_presets.json
    p = Path(__file__).resolve().parent / "image_presets.json"
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("presets", [])


# -----------------------
# Keyboards
# -----------------------
def kb_img_action():
    kb = InlineKeyboardBuilder()
    kb.button(text="✨ Увеличить качество (SeedVR)", callback_data="img:action:upscale")
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


def kb_img_ar():
    kb = InlineKeyboardBuilder()
    kb.button(text="default", callback_data="img:ar:default")
    kb.button(text="1:1", callback_data="img:ar:1_1")
    kb.button(text="4:3", callback_data="img:ar:4_3")
    kb.button(text="3:4", callback_data="img:ar:3_4")
    kb.button(text="3:2", callback_data="img:ar:3_2")
    kb.button(text="2:3", callback_data="img:ar:2_3")
    kb.button(text="⬅️ Назад", callback_data="img:back:tier")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def kb_gpt_image_size():
    kb = InlineKeyboardBuilder()
    kb.button(text="1024x1024", callback_data="img:size:1024x1024")
    kb.button(text="1536x1024", callback_data="img:size:1536x1024")
    kb.button(text="1024x1536", callback_data="img:size:1024x1536")
    kb.button(text="⬅️ Назад", callback_data="img:back:ar")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def kb_img_presets():
    presets = load_image_presets()
    kb = InlineKeyboardBuilder()
    for p in presets:
        kb.button(text=p["title"], callback_data=f"img:preset:{p['id']}")
    kb.button(text="➡️ Пропустить пресет", callback_data="img:preset:skip")
    kb.button(text="⬅️ Назад", callback_data="img:back:presetprev")
    kb.adjust(2)
    return kb.as_markup()


def kb_seedvr_scale():
    kb = InlineKeyboardBuilder()
    kb.button(text="🔍 x2", callback_data="img:seedvr:x2")
    kb.button(text="🔎 x4", callback_data="img:seedvr:x4")
    kb.button(text="⬅️ Назад", callback_data="img:back:action")
    kb.adjust(2, 1)
    return kb.as_markup()


# -----------------------
# Helpers
# -----------------------
def _img_flow(uid: int) -> dict:
    return USER_IMAGE_FLOW.setdefault(uid, {"step": "action", "meta": {}})


def _reset(uid: int):
    USER_MODE.pop(uid, None)
    USER_PENDING_TEXT.pop(uid, None)
    USER_PENDING_FILES.pop(uid, None)
    USER_IMAGE_FLOW.pop(uid, None)


def _build_slug(flow: dict) -> str:
    # img_{engine}_{tier}_{action} -> matches registry.py slugs
    return f"img_{flow['engine']}_{flow['tier']}_{flow['action']}"


def _set_common_meta(flow: dict):
    meta = flow.setdefault("meta", {})
    meta["translate_input"] = False
    meta.setdefault("num_images", 1)
    meta.setdefault("output_format", "png")


def _tier_apply_defaults(flow: dict):
    """
    Standard/Pro переключатель одинаковый для обоих движков:
    - GPT: quality=medium/high, image_size default
    - NB: std без quality, pro ставит quality=high, resolution default
    """
    _set_common_meta(flow)
    meta = flow["meta"]
    engine = flow.get("engine")
    tier = flow.get("tier")

    if engine == "gpt":
        meta["quality"] = "high" if tier == "pro" else "low"
        meta.setdefault("image_size", "1024x1024")
        meta.setdefault("aspect_ratio", "default")

    if engine == "nb":
        meta.setdefault("resolution", "2K")
        meta.setdefault("aspect_ratio", "default")
        if tier == "pro":
            meta["quality"] = "high"
        else:
            meta.pop("quality", None)


def _meta_to_input_text(prompt: str, meta: dict) -> str:
    prompt = (prompt or "").strip()
    return prompt + "\n---\n" + json.dumps(meta or {}, ensure_ascii=False)


def _preset_prompt(preset_id: str) -> str:
    if preset_id == "skip":
        return ""
    presets = {p["id"]: p for p in load_image_presets()}
    return (presets.get(preset_id) or {}).get("prompt", "") or ""


def _is_nano_edit(flow: dict) -> bool:
    return flow.get("action") == "edit" and flow.get("engine") == "nb"


def _album_key(uid: int, media_group_id: str) -> tuple[int, str]:
    return (uid, str(media_group_id))


async def _finalize_album(uid: int, media_group_id: str, message: Message):
    # ждём, пока Telegram дошлёт весь альбом (серия сообщений)
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


async def _run_and_deliver(message: Message, task_id: int):
    api = ApiClient()
    status_msg = await message.answer(
        f"🕒 Задача #{task_id} создана.\nСтатус: в очереди…",
        reply_markup=kb_bottom_panel(),
    )
    task = await wait_task_done(task_id, timeout_sec=900)

    if task["status"] == "success":
        key = task.get("result_file_key")
        if key:
            data = await api.download_file(key)
            filename = key.split("/")[-1]
            await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})")
            await message.answer_document(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
        else:
            await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})")

        if task.get("result_text"):
            await message.answer(_truncate(task["result_text"], 3500), reply_markup=kb_bottom_panel())
    else:
        await safe_edit_text(status_msg, f"❌ Ошибка (task #{task_id}): {task.get('error_message') or 'Unknown error'}")


# -----------------------
# /start + stubs
# -----------------------
@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer("🤖 GenBot\n\nВыбери раздел снизу 👇", reply_markup=kb_bottom_panel())


@router.message(F.text == "🔊 Аудио")
async def audio_stub(message: Message):
    await message.answer("🔊 Аудио пока в разработке.", reply_markup=kb_bottom_panel())


@router.message(F.text == "✍️ Тексты")
async def text_stub(message: Message):
    await message.answer("✍️ Тексты пока в разработке.", reply_markup=kb_bottom_panel())


@router.message(F.text == "👛 Баланс")
async def balance_stub(message: Message):
    await message.answer("👛 Баланс подключим позже.", reply_markup=kb_bottom_panel())


# -----------------------
# Images entry
# -----------------------
@router.message(F.text == "🖼 Изображения")
async def images_menu(message: Message):
    uid = message.from_user.id
    _reset(uid)
    USER_IMAGE_FLOW[uid] = {"step": "action", "meta": {}}
    await message.answer("🖼 Изображения\n\nВыбери действие:", reply_markup=kb_img_action())


# -----------------------
# Callbacks
# -----------------------
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

    if where == "ar":
        flow["step"] = "ar"
        await safe_edit_text(cb.message, "Выбери соотношение сторон (aspect_ratio):", reply_markup=kb_img_ar())
        await cb.answer()
        return

    # назад с пресетов
    if where == "presetprev":
        if flow.get("engine") == "gpt":
            flow["step"] = "size"
            await safe_edit_text(cb.message, "Выбери image_size:", reply_markup=kb_gpt_image_size())
        else:
            flow["step"] = "ar"
            await safe_edit_text(cb.message, "Выбери соотношение сторон (aspect_ratio):", reply_markup=kb_img_ar())
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
    engine = cb.data.split(":")[-1]  # nb/gpt
    flow["engine"] = engine
    flow["step"] = "tier"
    await safe_edit_text(cb.message, "Выбери режим (Standard/Pro):", reply_markup=kb_img_tier())
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:tier:"))
async def cb_tier(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    tier = cb.data.split(":")[-1]  # std/pro

    flow["tier"] = tier
    _tier_apply_defaults(flow)

    flow["step"] = "ar"
    await safe_edit_text(cb.message, "Выбери соотношение сторон (aspect_ratio):", reply_markup=kb_img_ar())
    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:ar:"))
async def cb_ar(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)

    v = cb.data.split(":")[-1]
    ar = "default" if v == "default" else v.replace("_", ":")

    _set_common_meta(flow)
    flow["meta"]["aspect_ratio"] = ar

    # GPT: после aspect_ratio спрашиваем image_size
    if flow.get("engine") == "gpt":
        flow["step"] = "size"
        await safe_edit_text(cb.message, "Выбери image_size:", reply_markup=kb_gpt_image_size())
    else:
        flow["step"] = "preset"
        await safe_edit_text(cb.message, "Пресет (опционально):", reply_markup=kb_img_presets())

    await cb.answer("Ок")


@router.callback_query(F.data.startswith("img:size:"))
async def cb_size(cb: CallbackQuery):
    uid = cb.from_user.id
    flow = _img_flow(uid)
    size = cb.data.split(":")[-1]

    _set_common_meta(flow)
    flow["meta"]["image_size"] = size

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

    # preset_slug для воркера
    USER_MODE[uid] = _build_slug(flow)

    # базовый промпт из пресета (можно пусто)
    USER_PENDING_TEXT[uid] = _preset_prompt(preset_id).strip()

    if flow["action"] == "create":
        flow["step"] = "wait_text_create"
        await safe_edit_text(
            cb.message,
            "✅ Готово.\n\n"
            "Теперь напиши промпт.\n"
            "Если выбрал пресет, можно просто уточнить детали.",
        )
    else:
        # Мягко: просим 1–2 фото ОДНИМ сообщением (альбомом), потом промпт
        flow["step"] = "wait_photos_edit"
        USER_PENDING_FILES[uid] = []
        await safe_edit_text(
            cb.message,
            "✅ Готово.\n\n"
            "Теперь отправь 1 или 2 фото ОДНИМ сообщением (альбомом).\n"
            "После этого напиши промпт.\n\n"
            "Подсказка: выбери 2 фото в галерее и отправь одним разом.",
        )

    await cb.answer("Ок")


# -----------------------
# Main message handler
# -----------------------
@router.message()
async def any_message(message: Message):
    uid = message.from_user.id
    flow = USER_IMAGE_FLOW.get(uid)

    panel_buttons = {"🖼 Изображения", "🔊 Аудио", "✍️ Тексты", "👛 Баланс"}
    is_panel_button = message.text in panel_buttons if message.text else False

    # detect file_id (photo/document)
    input_photo_id = message.photo[-1].file_id if message.photo else None
    input_doc_id = message.document.file_id if message.document else None

    # ---- CREATE: ждём текст ----
    if flow and flow.get("step") == "wait_text_create":
        if message.text and not message.text.startswith("/") and not is_panel_button:
            user_text = message.text.strip()
            base_prompt = (USER_PENDING_TEXT.get(uid) or "").strip()
            final_prompt = (base_prompt + "\n\n" + user_text).strip() if base_prompt else user_text

            meta = flow.get("meta", {})
            meta["translate_input"] = False
            input_text = _meta_to_input_text(final_prompt, meta)

            preset_slug = USER_MODE.get(uid)
            api = ApiClient()
            try:
                created = await api.create_task(uid, input_text, None, preset_slug)
            except Exception as e:
                await message.answer(f"❌ API ошибка: {_truncate(e)}", reply_markup=kb_bottom_panel())
                return

            await _run_and_deliver(message, created["task_id"])
            _reset(uid)
        return

    # ---- EDIT: ждём 1–2 фото одним сообщением (альбомом) ----
    if flow and flow.get("step") == "wait_photos_edit":
        # если юзер пишет текст — просим сначала фото
        if message.text and not message.text.startswith("/") and not is_panel_button:
            await message.answer(
                "Сначала отправь 1 или 2 фото одним сообщением (альбомом), потом напиши промпт 🙂",
                reply_markup=kb_bottom_panel(),
            )
            return

        # фото (в альбоме или одиночное)
        if message.photo:
            fid = input_photo_id

            # album mode
            if message.media_group_id:
                key = _album_key(uid, str(message.media_group_id))
                ALBUM_PHOTOS.setdefault(key, []).append(fid)

                # reset timer
                if key in ALBUM_TASKS:
                    ALBUM_TASKS[key].cancel()

                ALBUM_TASKS[key] = asyncio.create_task(_finalize_album(uid, str(message.media_group_id), message))
                return

            # single photo
            USER_PENDING_FILES[uid] = [fid]
            flow["step"] = "wait_text_edit"
            await message.answer("Фото принято ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())
            return

        # document as fallback (single)
        if message.document:
            USER_PENDING_FILES[uid] = [input_doc_id]
            flow["step"] = "wait_text_edit"
            await message.answer("Файл принят ✅ Теперь напиши промпт (что сделать).", reply_markup=kb_bottom_panel())
            return

        return

    # ---- EDIT: ждём текст после фото ----
    if flow and flow.get("step") == "wait_text_edit":
        if message.text and not message.text.startswith("/") and not is_panel_button:
            user_text = message.text.strip()

            base_prompt = (USER_PENDING_TEXT.get(uid) or "").strip()
            final_prompt = (base_prompt + "\n\n" + user_text).strip() if base_prompt else user_text

            photos = USER_PENDING_FILES.get(uid, [])
            if not photos:
                await message.answer("Не вижу фото. Отправь 1 или 2 фото одним сообщением (альбомом).", reply_markup=kb_bottom_panel())
                return

            meta = flow.get("meta", {})
            meta["translate_input"] = False

            # nano edit: 1–2 фото через tg_file_ids (worker сделает image_urls)
            if _is_nano_edit(flow):
                meta["tg_file_ids"] = photos[:2]
                file_id_for_api = photos[0]
            else:
                # gpt edit: берём первое фото
                file_id_for_api = photos[0]

            input_text = _meta_to_input_text(final_prompt, meta)
            preset_slug = USER_MODE.get(uid)

            api = ApiClient()
            try:
                created = await api.create_task(uid, input_text, file_id_for_api, preset_slug)
            except Exception as e:
                await message.answer(f"❌ API ошибка: {_truncate(e)}", reply_markup=kb_bottom_panel())
                return

            await _run_and_deliver(message, created["task_id"])
            _reset(uid)
        return

    # ---- Generic file submit (SeedVR) ----
    # После выбора seedvr_x2/x4 бот ждёт файл; тут просто отправляем как обычную задачу.
    if message.photo or message.document:
        preset_slug = USER_MODE.get(uid)
        if not preset_slug:
            # не в режиме, просто подсказка
            if message.photo or message.document:
                await message.answer("Зайди в 🖼 Изображения и выбери действие 👇", reply_markup=kb_bottom_panel())
            return

        api = ApiClient()
        input_tg_file_id = input_photo_id or input_doc_id
        try:
            created = await api.create_task(uid, USER_PENDING_TEXT.pop(uid, None), input_tg_file_id, preset_slug)
        except Exception as e:
            await message.answer(f"❌ API ошибка: {_truncate(e)}", reply_markup=kb_bottom_panel())
            return

        await _run_and_deliver(message, created["task_id"])
        _reset(uid)
        return

    # ---- Text outside flows ----
    if message.text and not message.text.startswith("/") and not is_panel_button:
        await message.answer("Зайди в 🖼 Изображения и выбери действие 👇", reply_markup=kb_bottom_panel())
