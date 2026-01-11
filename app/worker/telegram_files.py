import time
import random
import httpx


def tg_download_file(bot_token: str, file_id: str) -> tuple[str, bytes]:
    """
    Возвращает (filename, bytes) по Telegram file_id через Bot API.
    С ретраями на сетевые/5xx.
    """
    delay = 1.0
    for attempt in range(6):
        try:
            with httpx.Client(timeout=60, trust_env=False, follow_redirects=True) as client:
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

        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as e:
            if attempt == 5:
                raise
            time.sleep(delay * (0.85 + random.random() * 0.3))
            delay = min(delay * 1.6, 8.0)

    raise RuntimeError("Unreachable: tg_download_file retries exhausted")
