"""init

Revision ID: 0001_init
Revises:
Create Date: 2026-01-09
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_tg_user_id", "users", ["tg_user_id"], unique=True)

    op.create_table(
        "balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_balances_user_id", "balances", ["user_id"], unique=True)

    op.create_table(
        "presets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("provider_target", sa.String(length=32), nullable=False),
        sa.Column("price_credits", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_trending", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("config_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_presets_slug", "presets", ["slug"], unique=True)

    task_status = sa.Enum("queued", "processing", "success", "failed", name="taskstatus")
    ledger_type = sa.Enum("topup", "reserve", "capture", "release", "adjust", name="ledgereventtype")

    task_status.create(op.get_bind(), checkfirst=True)
    ledger_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("preset_slug", sa.String(length=64), nullable=False, server_default="dummy"),
        sa.Column("status", task_status, nullable=False, server_default="queued"),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("input_tg_file_id", sa.String(length=256), nullable=True),
        sa.Column("result_file_key", sa.String(length=512), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_created_at", "tasks", ["created_at"])

    op.create_table(
        "ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", ledger_type, nullable=False),
        sa.Column("amount_credits", sa.Integer(), nullable=False),
        sa.Column("meta_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index("ix_ledger_user_id", "ledger", ["user_id"])
    op.create_index("ix_ledger_created_at", "ledger", ["created_at"])


def downgrade():
    op.drop_index("ix_ledger_created_at", table_name="ledger")
    op.drop_index("ix_ledger_user_id", table_name="ledger")
    op.drop_table("ledger")

    op.drop_index("ix_tasks_created_at", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_presets_slug", table_name="presets")
    op.drop_table("presets")

    op.drop_index("ix_balances_user_id", table_name="balances")
    op.drop_table("balances")

    op.drop_index("ix_users_tg_user_id", table_name="users")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS ledgereventtype")
