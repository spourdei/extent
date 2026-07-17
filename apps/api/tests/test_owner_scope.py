"""A service-boundary test that keeps tenant identity explicit."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from extent_api.database.identity_repository import AccountRecord, ActiveSessionRecord
from extent_api.services.workspaces import WorkspaceService

USER_ID = UUID("10000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-4000-8000-000000000001")
NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


class RecordingWorkspaceStore:
    def __init__(self) -> None:
        self.requested_scope: tuple[UUID, UUID] | None = None

    def prepare_retry(self, *, user_id: UUID, workspace_id: UUID) -> None:
        self.requested_scope = (user_id, workspace_id)
        return None


class UnusedDependency:
    pass


def test_retry_passes_the_authenticated_owner_to_the_repository() -> None:
    store = RecordingWorkspaceStore()
    service = WorkspaceService(
        history_repository=UnusedDependency(),
        repository=store,  # type: ignore[arg-type]
        queue=UnusedDependency(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    session = ActiveSessionRecord(
        account=AccountRecord(
            display_name="Ada Analyst",
            email="ada@example.test",
            refresh_token_ciphertext=b"server-only",
            refresh_token_key_version=1,
            scopes=("https://www.googleapis.com/auth/drive.readonly",),
            token_status="active",
            user_id=USER_ID,
        ),
        expires_at=NOW + timedelta(days=1),
    )

    result = service.retry(active_session=session, workspace_id=WORKSPACE_ID)

    assert result is None
    assert store.requested_scope == (USER_ID, WORKSPACE_ID)
