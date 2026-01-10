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

# per-user runtime state (MVP)
USER_MODE: dict[int, str] = {}          # preset_slug
USER_PENDING_TEXT: dict[int, str] = {}  # текст, который надо прикрепить к следующему файлу


def _truncate(text: str, limit: int = MAX_TG_TEXT) -> str:
    if text is None:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: limit - 50] + "\n\n…(обрезано)…"


async def safe_edit_text(msg: Message, text: str, reply_markup=None):
    """
    Telegram может ругаться:
      - message is not modified
      - message is too long
      - message can't be edited
    Тогда делаем fallback: отправляем новое сообщение.
    """
    text = _truncate(text)

    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        s = str(e).lower()

        if "message is not modified" in s:
            return

        if "message is too long" in s:
            # отправляем отдельно
            await msg.answer(_truncate(text, 3500))
            return

        if "message can't be edited" in s or "message cannot be edited" in s:
            # fallback: просто новое сообщение вместо edit
            await msg.answer(text, reply_markup=reply_markup)
            return

        # всё остальное — пробрасываем
        raise



def kb_bottom_panel() -> ReplyKeyboardMarkup:
    # Нижняя панель (в поле ввода)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧰 Инструменты"), KeyboardButton(text="🖼 Изображения")],
            [KeyboardButton(text="🎬 Видео"), KeyboardButton(text="🔊 Аудио")],
            [KeyboardButton(text="✍️ Тексты"), KeyboardButton(text="👛 Баланс")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выбери раздел или пришли файл…",
    )


def kb_tools_inline():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎧 Анализ звонка", callback_data="set:analyze-call")
    kb.button(text="🖼 Outpaint / Reframe", callback_data="set:image-reframe")
    kb.button(text="🔼 Upscale (SeedVR)", callback_data="set:seedvr")
    kb.button(text="🧾 Картинка → SVG", callback_data="set:image-2-svg")
    kb.button(text="🧊 3D (выбор качества)", callback_data="menu:3d")
    kb.adjust(1)
    return kb.as_markup()


def kb_3d_inline():
    kb = InlineKeyboardBuilder()
    kb.button(text="⚡ Дёшево/быстро (Trellis)", callback_data="set:3d_trellis")
    kb.button(text="⚖️ Баланс (Hunyuan)", callback_data="set:3d_hunyuan")
    kb.button(text="💎 Качество (Rodin)", callback_data="set:3d_rodin")
    kb.button(text="⬅️ Назад", callback_data="menu:tools")
    kb.adjust(1)
    return kb.as_markup()


def _mode_label(user_id: int) -> str:
    slug = USER_MODE.get(user_id)
    if not slug:
        return "Режим: не выбран"
    try:
        p = get_preset(slug)
        title = p.mode_title or p.title
    except Exception:
        title = slug
    return f"Режим: {title}"


@router.message(F.text == "/start")
async def start(message: Message):
    await message.answer(
        "🤖 GenBot\n\n"
        "Быстрые кнопки снизу 👇\n"
        f"{_mode_label(message.from_user.id)}",
        reply_markup=kb_bottom_panel(),
    )


# ---- Bottom panel handlers ----
@router.message(F.text == "🧰 Инструменты")
async def tools_menu(message: Message):
    await message.answer(
        "🧰 Инструменты\n\nВыбери инструмент:",
        reply_markup=kb_tools_inline(),
    )


@router.message(F.text == "🖼 Изображения")
async def images_stub(message: Message):
    await message.answer(
        "🖼 Изображения пока в разработке.\n\n"
        "Скоро добавим NanoBanana / GPT-Image и пресеты.",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "🎬 Видео")
async def video_stub(message: Message):
    await message.answer(
        "🎬 Видео пока в разработке (Kling 5/10/15 сек).",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "🔊 Аудио")
async def audio_stub(message: Message):
    await message.answer(
        "🔊 Аудио пока в разработке (Music/TTS/STT).",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "✍️ Тексты")
async def text_stub(message: Message):
    await message.answer(
        "✍️ Тексты пока в разработке (Grok + пресеты).",
        reply_markup=kb_bottom_panel(),
    )


@router.message(F.text == "👛 Баланс")
async def balance_stub(message: Message):
    await message.answer(
        "👛 Баланс подключим на этапе ЮKassa.\n"
        "Сейчас используем прямой GenAPI баланс для разработки.",
        reply_markup=kb_bottom_panel(),
    )


# ---- Inline menu handlers ----
@router.callback_query(F.data == "menu:tools")
async def cb_tools(cb: CallbackQuery):
    await safe_edit_text(cb.message, "🧰 Инструменты\n\nВыбери инструмент:", reply_markup=kb_tools_inline())
    await cb.answer()


@router.callback_query(F.data == "menu:3d")
async def cb_3d(cb: CallbackQuery):
    await safe_edit_text(cb.message, "🧊 3D\n\nВыбери качество:", reply_markup=kb_3d_inline())
    await cb.answer()


@router.callback_query(F.data.startswith("set:"))
async def cb_set_mode(cb: CallbackQuery):
    slug = cb.data.split(":", 1)[1]
    USER_MODE[cb.from_user.id] = slug

    # очищаем “подвешенный текст” при смене режима
    USER_PENDING_TEXT.pop(cb.from_user.id, None)

    p = get_preset(slug)
    msg = f"✅ {p.mode_title or p.title}\n\n{p.input_hint}\n\n(Можно прислать текст перед файлом, если нужно.)"
    # не всегда нужно edit, но пусть будет мягко
    await safe_edit_text(cb.message, msg, reply_markup=kb_tools_inline())
    await cb.answer("Ок")


@router.message()
async def any_message(message: Message):
    user_id = message.from_user.id

    # Если пользователь прислал обычный текст (не команду/не кнопку) — запомним как “текст к следующему файлу”
    if message.text and not message.text.startswith("/") and message.text not in {
        "🧰 Инструменты", "🖼 Изображения", "🎬 Видео", "🔊 Аудио", "✍️ Тексты", "👛 Баланс"
    }:
        # если режим выбран — сохраним как input_text к следующему файлу
        if USER_MODE.get(user_id):
            USER_PENDING_TEXT[user_id] = message.text.strip()
            await message.answer(
                f"✍️ Текст сохранён.\n{_mode_label(user_id)}\nТеперь пришли файл.",
                reply_markup=kb_bottom_panel(),
            )
        else:
            await message.answer("Сначала выбери раздел на нижней панели 👇", reply_markup=kb_bottom_panel())
        return

    # определяем input file_id
    input_tg_file_id = None
    if message.photo:
        input_tg_file_id = message.photo[-1].file_id
    elif message.document:
        input_tg_file_id = message.document.file_id
    elif message.audio:
        input_tg_file_id = message.audio.file_id
    elif message.voice:
        input_tg_file_id = message.voice.file_id

    if not input_tg_file_id:
        # не файл и не нужный текст
        await message.answer(f"{_mode_label(user_id)}\nВыбери действие на панели 👇", reply_markup=kb_bottom_panel())
        return

    preset_slug = USER_MODE.get(user_id)
    if not preset_slug:
        await message.answer("Сначала выбери инструмент: нажми 🧰 Инструменты 👇", reply_markup=kb_bottom_panel())
        return

    preset = get_preset(preset_slug)

    # если вдруг для каких-то будущих пресетов нужен текст строго перед файлом
    if preset.requires_text and not USER_PENDING_TEXT.get(user_id):
        await message.answer("Сначала пришли текст, потом файл 🙂", reply_markup=kb_bottom_panel())
        return

    input_text = USER_PENDING_TEXT.pop(user_id, None)

    api = ApiClient()
    try:
        created = await api.create_task(
            tg_user_id=user_id,
            input_text=input_text,
            input_tg_file_id=input_tg_file_id,
            preset_slug=preset_slug,
        )
    except Exception as e:
        await message.answer(f"❌ API ошибка: {_truncate(e)}", reply_markup=kb_bottom_panel())
        return

    task_id = created["task_id"]
    status_msg = await message.answer(
        f"🕒 Задача #{task_id} создана.\n{_mode_label(user_id)}\nСтатус: в очереди…",
        reply_markup=kb_bottom_panel(),
    )

    task = await wait_task_done(task_id, timeout_sec=900)

    if task["status"] == "success":
        key = task.get("result_file_key")
        if key:
            try:
                data = await api.download_file(key)
                filename = key.split("/")[-1]
                await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})\n{_mode_label(user_id)}")
                await message.answer_document(BufferedInputFile(data, filename=filename), reply_markup=kb_bottom_panel())
            except Exception as e:
                await safe_edit_text(status_msg, f"✅ Готово (task #{task_id}), но файл не скачался: {_truncate(e)}")
        else:
            await safe_edit_text(status_msg, f"✅ Готово! (task #{task_id})\n{_mode_label(user_id)}")

        if task.get("result_text"):
            await message.answer(_truncate(task["result_text"], 3500), reply_markup=kb_bottom_panel())

    else:
        err = task.get("error_message") or "Unknown error"
        err_str = str(err)

        if len(err_str) > MAX_TG_TEXT:
            await safe_edit_text(status_msg, f"❌ Ошибка (task #{task_id}): слишком длинная, отправляю файлом…")
            data = err_str.encode("utf-8", errors="ignore")
            await message.answer_document(
                BufferedInputFile(data, filename=f"task_{task_id}_error.txt"),
                reply_markup=kb_bottom_panel(),
            )
        else:
            await safe_edit_text(status_msg, f"❌ Ошибка (task #{task_id}): {err_str}")
