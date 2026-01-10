from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

async_engine = create_async_engine(settings.DATABASE_URL_ASYNC, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)

sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=sync_engine)
