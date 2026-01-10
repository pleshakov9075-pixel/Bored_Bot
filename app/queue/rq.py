import os
import redis
from rq import Worker, Queue, Connection
from app.core.config import settings

listen = [settings.RQ_QUEUE_NAME]


def main():
    redis_conn = redis.from_url(settings.REDIS_URL)
    with Connection(redis_conn):
        worker = Worker(map(Queue, listen))
        worker.work(with_scheduler=False)


if __name__ == "__main__":
    main()
