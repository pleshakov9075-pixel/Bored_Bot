import httpx


def tg_download_file(bot_token: str, file_id: str) -> tuple[str, bytes]:
    """
    Возвращает (filename, bytes) по Telegram file_id через Bot API.
    """
    with httpx.Client(timeout=60, trust_env=False) as client:
        r = client.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
        )
        r.raise_for_status()
        js = r.json()
        if not js.get("ok"):
            raise RuntimeError(f"Telegram getFile failed: {js}")

        file_path = js["result"]["file_path"]
        filename = file_path.split("/")[-1]

        dl = client.get(f"https://api.telegram.org/file/bot{bot_token}/{file_path}")
        dl.raise_for_status()
        return filename, dl.content
