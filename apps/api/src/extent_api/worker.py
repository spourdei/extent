"""Native RQ worker entrypoint for local development and Render workers."""

from resource import struct_rusage
from uuid import UUID

from rq import SpawnWorker, Worker
from rq.job import Job

from extent_api.config import get_settings
from extent_api.database.session import create_database_engine, create_session_factory
from extent_api.database.workspace_repository import WorkspaceRepository
from extent_api.jobs import sync_folder as _sync_folder
from extent_api.providers.tesseract_ocr import ensure_tesseract_available
from extent_api.queueing import create_redis_connection

_JOB_ENTRYPOINTS = (_sync_folder,)


def _worker_class(environment: str) -> type[Worker]:
    return Worker if environment == "production" else SpawnWorker


def _ingestion_run_id(job: Job) -> UUID | None:
    if job.func_name != "extent_api.jobs.sync_folder":
        return None
    args = job.args
    if len(args) != 1 or not isinstance(args[0], str):
        return None
    try:
        return UUID(args[0])
    except ValueError:
        return None


def _mark_killed_ingestion_retryable(
    job: Job,
    _retpid: int,
    _ret_val: int,
    _rusage: struct_rusage,
) -> None:
    run_id = _ingestion_run_id(job)
    if run_id is None:
        return
    settings = get_settings()
    engine = create_database_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        with session_factory() as database_session:
            repository = WorkspaceRepository(database_session)
            repository.mark_retryable(run_id, error_code="worker_process_terminated")
            repository.commit()
    finally:
        engine.dispose()


def run_worker() -> None:
    """Run the single Extent queue until the process receives a stop signal."""

    settings = get_settings()
    settings.require_runtime_capabilities()
    ensure_tesseract_available(settings.ocr_executable)
    connection = create_redis_connection(settings.redis_url)
    connection.ping()
    _worker_class(settings.environment)(
        [settings.queue_name],
        connection=connection,
        work_horse_killed_handler=_mark_killed_ingestion_retryable,
    ).work(with_scheduler=False)


if __name__ == "__main__":
    run_worker()
