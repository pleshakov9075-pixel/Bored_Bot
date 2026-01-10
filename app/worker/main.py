import time
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import Task, TaskStatus
from app.worker.executor import execute_task

POLL_INTERVAL_SEC = 1.0


def main():
    print("Worker started. Scanning for queued tasks…")
    while True:
        db = SessionLocal()
        try:
            task = db.execute(
                select(Task)
                .where(Task.status == TaskStatus.queued)
                .order_by(Task.id.asc())
                .limit(1)
            ).scalar_one_or_none()
        finally:
            db.close()

        if task:
            print(f"Processing task #{task.id} preset={task.preset_slug}")
            execute_task(task.id)
        else:
            time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
