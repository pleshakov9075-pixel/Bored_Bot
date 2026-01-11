from __future__ import annotations

import compileall


def _import_settings():
    try:
        from app.core.config import settings
    except Exception as exc:  # pragma: no cover - smoke check only
        raise SystemExit(f"Failed to import settings: {exc}") from exc
    return settings


def _check_required(settings) -> None:
    required_fields = [
        "BOT_TOKEN",
        "GENAPI_TOKEN",
        "DATABASE_URL_ASYNC",
        "DATABASE_URL_SYNC",
        "INTERNAL_API_KEY",
    ]
    missing = [name for name in required_fields if not getattr(settings, name, None)]
    if missing:
        missing_list = ", ".join(missing)
        raise SystemExit(f"Missing required settings: {missing_list}")


def _compile_all() -> None:
    if not compileall.compile_dir("app", quiet=1):
        raise SystemExit("compileall failed")


def main() -> None:
    settings = _import_settings()
    _check_required(settings)
    _compile_all()
    print("Smoke check OK")


if __name__ == "__main__":
    main()
