from fastapi import FastAPI

from app.api.routes import router
from app.db.base import Base
from app.db.session import sync_engine
from app.storage.local import ensure_dirs

app = FastAPI(title="GenBot API", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
def on_startup():
    ensure_dirs()
    Base.metadata.create_all(bind=sync_engine)
