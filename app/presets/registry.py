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

    # ---- Nano Banana ----
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
            "translate_input": False,  # в nano по умолчанию true :contentReference[oaicite:2]{index=2}
            "num_images": 1,
            "output_format": "png",
            "aspect_ratio": "default",
            "resolution": "2K",
        },
        input_field="image_urls",  # не используется при create, но пусть будет едино
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
            "aspect_ratio": "default",
            "resolution": "2K",
            "quality": "high",
        },
        input_field="image_urls",
        input_hint="Напиши промпт (можно выбрать пресет).",
        mode_title="🍌 NB Pro • Create",
    ),
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
            "aspect_ratio": "default",
            "resolution": "2K",
        },
        input_field="image_urls",  # <<< мульти-вход
        input_hint="Пришли 2 фото (обязательно), потом промпт (или выбери пресет).",
        mode_title="🍌 NB Std • Edit (2 images)",
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
            "aspect_ratio": "default",
            "resolution": "2K",
            "quality": "high",
        },
        input_field="image_urls",  # <<< мульти-вход
        input_hint="Пришли 2 фото (обязательно), потом промпт (или выбери пресет).",
        mode_title="🍌 NB Pro • Edit (2 images)",
    ),

    # ---- GPT Image 1.5 ----
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
            "aspect_ratio": "default",
            "image_size": "1024x1024",
            "quality": "medium",
        },
        input_field="image_url",
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
            "aspect_ratio": "default",
            "image_size": "1024x1024",
            "quality": "high",
        },
        input_field="image_url",
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
            "aspect_ratio": "default",
            "image_size": "1024x1024",
            "quality": "medium",
        },
        input_field="image_url",
        input_hint="Пришли 1 фото, потом промпт (или выбери пресет).",
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
            "aspect_ratio": "default",
            "image_size": "1024x1024",
            "quality": "high",
        },
        input_field="image_url",
        input_hint="Пришли 1 фото, потом промпт (или выбери пресет).",
        mode_title="🎨 GPT Pro • Edit",
    ),
}


def get_preset(slug: str) -> Preset:
    slug = (slug or "").strip().lower()
    if slug not in PRESETS:
        raise KeyError(f"Preset not found: {slug}")
    return PRESETS[slug]
