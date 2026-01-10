import io
import time
from datetime import datetime

from sqlalchemy import select, update
from app.db.session import SessionLocal
from app.db.models import User, Balance, Task, TaskStatus
from app.storage.minio import s3_client, ensure_bucket
from app.core.config import settings


def _get_or_create_user_and_balance(db, tg_user_id: int) -> int:
    user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if not user:
        user = User(tg_user_id=tg_user_id, created_at=datetime.utcnow())
        db.add(user)
        db.flush()
        bal = Balance(user_id=user.id, credits=0)
        db.add(bal)
        db.flush()
    return user.id


def process_dummy_task(task_id: int) -> None:
    # 1) помечаем processing
    db = SessionLocal()
    try:
        task = db.execute(select(Task).where(Task.id == task_id)).scalar_one()
        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(status=TaskStatus.processing, updated_at=datetime.utcnow(), error_message=None)
        )
        db.commit()

        # 2) имитация работы
        time.sleep(2)

        # 3) создаём dummy файл
        content = f"Dummy result for task={task_id}\nInput text: {task.input_text}\n"
        buf = io.BytesIO(content.encode("utf-8"))
        key = f"results/task_{task_id}.txt"

        ensure_bucket()
        s3 = s3_client()
        s3.put_object(
            Bucket=settings.MINIO_BUCKET,
            Key=key,
            Body=buf.getvalue(),
            ContentType="text/plain",
        )

        # 4) обновляем task success
        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                status=TaskStatus.success,
                result_file_key=key,
                result_text="Готово ✅ (dummy)",
                updated_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception as e:
        db.rollback()
        db.execute(
            update(Task)
            .where(Task.id == task_id)
            .values(
                status=TaskStatus.failed,
                error_message=str(e),
                updated_at=datetime.utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()
