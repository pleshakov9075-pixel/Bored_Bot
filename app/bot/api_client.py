import httpx
from app.core.config import settings


class ApiClient:
    def __init__(self):
        self.base = settings.API_BASE_URL.rstrip("/")
        self.headers = {"X-API-Key": settings.INTERNAL_API_KEY}

    async def create_task(self, tg_user_id: int, input_text: str | None, input_tg_file_id: str | None, preset_slug: str):
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.post(
                f"{self.base}/internal/tasks",
                headers=self.headers,
                json={
                    "tg_user_id": tg_user_id,
                    "input_text": input_text,
                    "input_tg_file_id": input_tg_file_id,
                    "preset_slug": preset_slug,
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.json()

    async def get_task(self, task_id: int):
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.get(f"{self.base}/internal/tasks/{task_id}", headers=self.headers)
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.json()

    async def download_file(self, key: str) -> bytes:
        # ✅ большие файлы (Suno/SeedVR) скачиваем терпеливо
        async with httpx.AsyncClient(timeout=300, trust_env=False, follow_redirects=True) as client:
            r = await client.get(f"{self.base}/internal/files/{key}", headers=self.headers)
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.content

    async def get_balance(self, tg_user_id: int) -> dict:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.get(f"{self.base}/internal/balance/{tg_user_id}", headers=self.headers)
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.json()

    async def create_topup(self, tg_user_id: int, amount_rub: int, description: str = "Пополнение баланса"):
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            r = await client.post(
                f"{self.base}/internal/payments/topup",
                headers=self.headers,
                json={"tg_user_id": tg_user_id, "amount_rub": amount_rub, "description": description},
            )
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.json()
