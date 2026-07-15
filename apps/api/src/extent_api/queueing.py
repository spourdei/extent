"""Redis/RQ construction at the process boundary."""

from uuid import UUID

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import InvalidJobOperation
from rq.registry import FailedJobRegistry


def ingestion_job_id(run_id: str) -> str:
    """Return an RQ-compatible deterministic job id for one ingestion run."""

    return f"ingestion-{run_id}"


class IngestionEnqueueError(RuntimeError):
    """A queue-boundary failure that leaves durable ingestion state recoverable."""


def create_redis_connection(redis_url: str) -> Redis:
    """Create a lazy Redis client with bounded socket behavior."""

    return Redis.from_url(
        redis_url,
        decode_responses=False,
        health_check_interval=30,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def create_queue(connection: Redis, queue_name: str) -> Queue:
    """Create the single bounded queue shared by API and worker processes."""

    return Queue(name=queue_name, connection=connection, default_timeout=900)


class RqIngestionQueue:
    """Expose only the one deterministic job operation used by the API service."""

    def __init__(self, queue: Queue) -> None:
        self._queue = queue

    def enqueue_run(self, run_id: UUID) -> None:
        job_id = ingestion_job_id(str(run_id))
        try:
            failed_registry = FailedJobRegistry(queue=self._queue)
            if job_id in failed_registry:
                failed_registry.requeue(job_id)
                return
            self._queue.enqueue(
                "extent_api.jobs.sync_folder",
                str(run_id),
                job_id=job_id,
                result_ttl=0,
            )
        except (InvalidJobOperation, RedisError) as error:
            raise IngestionEnqueueError("ingestion queue is unavailable") from error


def create_ingestion_queue(connection: Redis, queue_name: str) -> RqIngestionQueue:
    return RqIngestionQueue(create_queue(connection, queue_name))
