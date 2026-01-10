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

    # UX helpers
    requires_text: bool = False
    input_hint: str = "Пришли файл."
    mode_title: str = ""

    # имя поля для входа:
    # - function: multipart поле (image / audio)
    # - network: URL-поле (image_url и т.п.)
    input_field: str = "image"


PRESETS: dict[str, Preset] = {

    # ============================================================
    # FUNCTIONS (multipart, БЕЗ URL)
    # ============================================================

    "analyze-call": Preset(
        slug="analyze-call",
        title="🎧 Анализ звонка",
        category="tools",
        provider_target="function",
        provider_id="analyze-call",
        implementation="claude",
        input_kind="audio",
        price_credits=49,
        params={
            "model": "claude-3-7-sonnet-20250219",
        },
        input_field="audio",
        requires_text=True,
        input_hint="Пришли аудиофайл (mp3/wav/ogg). Текст (скрипт) можно дописать сообщением до аудио.",
        mode_title="🎧 Анализ звонка",
    ),

    # === REFRAME / OUTPAINT ===
    # Единственный правильный вариант: FUNCTION outpainting
    "outpainting": Preset(
        slug="outpainting",
        title="🖼 Outpaint / Reframe",
        category="tools",
        provider_target="function",
        provider_id="outpainting",
        implementation="outpainting-v1",
        input_kind="image",
        price_credits=19,
        params={
            "prompt": "outpaint image",
        },
        input_field="image",
        input_hint="Пришли изображение (фото или документ).",
        mode_title="🖼 Outpaint / Reframe",
    ),

    # ============================================================
    # NETWORKS (ТОЛЬКО через URL)
    # ============================================================

    # --- Upscale ---
    "seedvr": Preset(
        slug="seedvr",
        title="🔼 Upscale (SeedVR x4)",
        category="tools",
        provider_target="network",
        provider_id="seedvr",
        implementation=None,
        input_kind="image",
        price_credits=29,
        params={
            "upscale_factor": 4,
        },
        input_field="image_url",
        input_hint="Пришли изображение для апскейла.",
        mode_title="🔼 Upscale x4",
    ),

    # --- Image → SVG ---
    "image-2-svg": Preset(
        slug="image-2-svg",
        title="🧾 Картинка → SVG",
        category="tools",
        provider_target="network",
        provider_id="image-2-svg",
        implementation=None,
        input_kind="image",
        price_credits=9,
        params={},
        input_field="image_url",
        input_hint="Пришли изображение, я конвертирую в SVG.",
        mode_title="🧾 Image → SVG",
    ),

    # --- 3D MODELS ---
    "3d_trellis": Preset(
        slug="3d_trellis",
        title="🧊 3D (Trellis, быстро)",
        category="tools",
        provider_target="network",
        provider_id="trellis",
        implementation=None,
        input_kind="image",
        price_credits=29,
        params={},
        input_field="image_url",
        input_hint="Пришли изображение, я сделаю 3D (быстро).",
        mode_title="🧊 3D Trellis",
    ),

    "3d_hunyuan": Preset(
        slug="3d_hunyuan",
        title="🧊 3D (Hunyuan, баланс)",
        category="tools",
        provider_target="network",
        provider_id="hunyuan-3d-multi-view",
        implementation=None,
        input_kind="image",
        price_credits=89,
        params={},
        input_field="image_url",
        input_hint="Пришли изображение, я сделаю 3D (баланс).",
        mode_title="🧊 3D Hunyuan",
    ),

    "3d_rodin": Preset(
        slug="3d_rodin",
        title="🧊 3D (Rodin, качество)",
        category="tools",
        provider_target="network",
        provider_id="rodin",
        implementation=None,
        input_kind="image",
        price_credits=149,
        params={},
        input_field="image_url",
        input_hint="Пришли изображение, я сделаю 3D (качество).",
        mode_title="🧊 3D Rodin",
    ),
}


def get_preset(slug: str) -> Preset:
    slug = (slug or "").strip().lower()
    if slug not in PRESETS:
        raise KeyError(f"Preset not found: {slug}")
    return PRESETS[slug]
