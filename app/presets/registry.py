from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderTarget = Literal["function", "network"]
InputKind = Literal["image", "audio", "none"]
Category = Literal["tools"]


@dataclass(frozen=True)
class Preset:
    slug: str
    title: str
    category: Category
    provider_target: ProviderTarget
    provider_id: str
    implementation: str | None
    input_kind: InputKind
    price_credits: int
    params: dict

    requires_text: bool = False
    input_hint: str = "Пришли файл."
    mode_title: str = ""
    input_field: str = "image"


PRESETS: dict[str, Preset] = {
    # ==========================
    # AUDIO: Suno v5
    # ==========================
    "suno": Preset(
        slug="suno",
        title="🎵 Музыка (Suno v5)",
        category="tools",
        provider_target="network",
        provider_id="suno",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "model": "v5",
            "translate_input": False,
        },
        input_field="image_url",
        input_hint="Соберу title/tags/prompt и сгенерирую трек.",
        mode_title="🎵 Suno v5",
    ),

    # ==========================
    # TEXT: Grok 4.1
    # ==========================
    "grok": Preset(
        slug="grok",
        title="✍️ Текст (Grok 4.1)",
        category="tools",
        provider_target="network",
        provider_id="grok-4-1",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "model": "grok-4-1-fast-reasoning",
            "stream": False,
        },
        input_field="image_url",
        input_hint="Напиши запрос, я верну ответ.",
        mode_title="✍️ Grok 4.1",
    ),

    # ==========================
    # SeedVR upscale
    # ==========================
    "seedvr_x2": Preset(
        slug="seedvr_x2",
        title="✨ Upscale (SeedVR x2)",
        category="tools",
        provider_target="network",
        provider_id="seedvr",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={"upscale_factor": 2},
        input_field="image_url",
        input_hint="Пришли изображение для апскейла x2.",
        mode_title="✨ Upscale x2",
    ),
    "seedvr_x4": Preset(
        slug="seedvr_x4",
        title="✨ Upscale (SeedVR x4)",
        category="tools",
        provider_target="network",
        provider_id="seedvr",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={"upscale_factor": 4},
        input_field="image_url",
        input_hint="Пришли изображение для апскейла x4.",
        mode_title="✨ Upscale x4",
    ),

    # ==========================
    # IMAGES: NanoBanana + GPTImage
    # ==========================
    # NanoBanana create (text2img)
    "img_nb_std_create": Preset(
        slug="img_nb_std_create",
        title="🍌 NanoBanana Standard • Создать",
        category="tools",
        provider_target="network",
        provider_id="nano-banana",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "resolution": "2K",
        },
        input_field="image_urls",
        input_hint="Напиши промпт (можно выбрать пресет).",
        mode_title="🍌 NB Std • Create",
    ),
    "img_nb_pro_create": Preset(
        slug="img_nb_pro_create",
        title="🍌 NanoBanana Pro • Создать",
        category="tools",
        provider_target="network",
        provider_id="nano-banana-pro",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "resolution": "2K",
            "quality": "high",
        },
        input_field="image_urls",
        input_hint="Напиши промпт (можно выбрать пресет).",
        mode_title="🍌 NB Pro • Create",
    ),

    # NanoBanana edit (img2img), multi-image supported via input_field=image_urls
    "img_nb_std_edit": Preset(
        slug="img_nb_std_edit",
        title="🍌 NanoBanana Standard • Редактировать",
        category="tools",
        provider_target="network",
        provider_id="nano-banana",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "resolution": "2K",
        },
        input_field="image_urls",
        input_hint="Отправь 1–2 фото одним сообщением (альбомом), потом промпт.",
        mode_title="🍌 NB Std • Edit",
    ),
    "img_nb_pro_edit": Preset(
        slug="img_nb_pro_edit",
        title="🍌 NanoBanana Pro • Редактировать",
        category="tools",
        provider_target="network",
        provider_id="nano-banana-pro",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "resolution": "2K",
            "quality": "high",
        },
        input_field="image_urls",
        input_hint="Отправь 1–2 фото одним сообщением (альбомом), потом промпт.",
        mode_title="🍌 NB Pro • Edit",
    ),

    # GPTImage create/edit (text2img + img2img)
    # ✅ важное: для gpt-image-1-5 используем image_urls (список), а не image_url
    "img_gpt_std_create": Preset(
        slug="img_gpt_std_create",
        title="🎨 GPTImage Standard • Создать",
        category="tools",
        provider_target="network",
        provider_id="gpt-image-1-5",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "image_size": "1024x1024",
            "quality": "low",
        },
        input_field="image_urls",
        input_hint="Напиши промпт (можно выбрать пресет).",
        mode_title="🎨 GPT Std • Create",
    ),
    "img_gpt_pro_create": Preset(
        slug="img_gpt_pro_create",
        title="🎨 GPTImage Pro • Создать",
        category="tools",
        provider_target="network",
        provider_id="gpt-image-1-5",
        implementation=None,
        input_kind="none",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "image_size": "1024x1024",
            "quality": "medium",
        },
        input_field="image_urls",
        input_hint="Напиши промпт (можно выбрать пресет).",
        mode_title="🎨 GPT Pro • Create",
    ),
    "img_gpt_std_edit": Preset(
        slug="img_gpt_std_edit",
        title="🎨 GPTImage Standard • Редактировать",
        category="tools",
        provider_target="network",
        provider_id="gpt-image-1-5",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "image_size": "1024x1024",
            "quality": "low",
        },
        input_field="image_urls",
        input_hint="Отправь 1 фото, потом промпт.",
        mode_title="🎨 GPT Std • Edit",
    ),
    "img_gpt_pro_edit": Preset(
        slug="img_gpt_pro_edit",
        title="🎨 GPTImage Pro • Редактировать",
        category="tools",
        provider_target="network",
        provider_id="gpt-image-1-5",
        implementation=None,
        input_kind="image",
        price_credits=0,
        params={
            "translate_input": False,
            "num_images": 1,
            "output_format": "png",
            "image_size": "1024x1024",
            "quality": "medium",
        },
        input_field="image_urls",
        input_hint="Отправь 1 фото, потом промпт.",
        mode_title="🎨 GPT Pro • Edit",
    ),
}


def get_preset(slug: str) -> Preset:
    slug = (slug or "").strip().lower()
    if slug not in PRESETS:
        raise KeyError(f"Preset not found: {slug}")
    return PRESETS[slug]
