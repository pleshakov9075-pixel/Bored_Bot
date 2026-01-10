from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: str = ""

    # API
    API_BASE_URL: str = "http://localhost:8080"
    API_PUBLIC_BASE_URL=http://89.104.69.156:8000
    INTERNAL_API_KEY: str = "dev-internal-key"

    # --- GenAPI ---
    GENAPI_BASE_URL: str = "https://api.gen-api.ru/api/v1"
    GENAPI_TOKEN: str = "sk-1xGvNoyLmRsfDfnglaPKdPvfcp5xPX0mM2lkiNJDfXGThQxdPgeeahUUriEU"


    # DB
    DATABASE_URL_ASYNC: str
    DATABASE_URL_SYNC: str

    # Redis/RQ
    REDIS_URL: str = "redis://localhost:6379/0"
    RQ_QUEUE_NAME: str = "genbot"

    # MinIO
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minio"
    MINIO_SECRET_KEY: str = "minio12345"
    MINIO_BUCKET: str = "genbot"
    MINIO_SECURE: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
