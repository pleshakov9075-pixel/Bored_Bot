import enum
from datetime import datetime
from sqlalchemy import (
    String, Integer, BigInteger, DateTime, Boolean, Enum, ForeignKey, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base


class TaskStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    success = "success"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    balance: Mapped["Balance"] = relationship(back_populates="user", uselist=False)


class Balance(Base):
    __tablename__ = "balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, index=True)
    credits: Mapped[int] = mapped_column(Integer, default=0)

    user: Mapped["User"] = relationship(back_populates="balance")


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    provider_target: Mapped[str] = mapped_column(String(32))  # "function" | "composite"
    price_credits: Mapped[int] = mapped_column(Integer, default=1)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_trending: Mapped[bool] = mapped_column(Boolean, default=False)
    config_json: Mapped[str] = mapped_column(Text, default="{}")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    preset_slug: Mapped[str] = mapped_column(String(64), default="dummy")
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.queued, index=True)

    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tg_file_id: Mapped[str | None] = mapped_column(String(256), nullable=True)

    result_file_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # user rel можно добавить позже, не обязателен для MVP


class LedgerEventType(str, enum.Enum):
    topup = "topup"
    reserve = "reserve"
    capture = "capture"
    release = "release"
    adjust = "adjust"


class Ledger(Base):
    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[LedgerEventType] = mapped_column(Enum(LedgerEventType))
    amount_credits: Mapped[int] = mapped_column(Integer)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
