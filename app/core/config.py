from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: str = ""

    # API
    API_BASE_URL: str = "http://localhost:8080"
    # публичная база (то, что доступно GenAPI извне)
    API_PUBLIC_BASE_URL: str = "http://89.104.69.156:8000"
    PUBLIC_FILES_BASE_URL: str = ""

    INTERNAL_API_KEY: str = "dev-internal-key"

    # --- GenAPI ---
    GENAPI_BASE_URL: str = "https://api.gen-api.ru/api/v1"
    GENAPI_TOKEN: str = "sk-1xGvNoyLmRsfDfnglaPKdPvfcp5xPX0mM2lkiNJDfXGThQxdPgeeahUUriEU"

    # Limits
    MAX_INPUT_FILES: int = 2
    MAX_INPUT_FILE_SIZE_MB: int = 10
    TASK_TIMEOUT_SEC: int = 1800

    # DB
    DATABASE_URL_ASYNC: str
    DATABASE_URL_SYNC: str

    # Redis/RQ (если будешь использовать rq, оставляем)
    REDIS_URL: str = "redis://localhost:6379/0"
    RQ_QUEUE_NAME: str = "genbot"

    # MinIO (на будущее)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio"
    MINIO_SECRET_KEY: str = "minio12345"
    MINIO_BUCKET: str = "genbot"
    MINIO_SECURE: bool = False

    # YooKassa
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_RETURN_URL: str = ""   # куда вернуть пользователя после оплаты (если используешь redirect)
    YOOKASSA_WEBHOOK_SECRET: str = ""  # опционально: если захочешь подписывать вебхуки

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
