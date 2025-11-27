import os
import redis
from rq import Worker, Queue, Connection
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

listen = ['default']

def get_redis_connection():
    redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
    return redis.from_url(redis_url)

if __name__ == '__main__':
    logger.info("Starting worker...")
    conn = get_redis_connection()
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()
