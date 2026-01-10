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
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            r = await client.get(f"{self.base}/internal/files/{key}", headers=self.headers)
            if r.status_code >= 400:
                raise RuntimeError(f"API error {r.status_code}: {r.text}")
            return r.content
