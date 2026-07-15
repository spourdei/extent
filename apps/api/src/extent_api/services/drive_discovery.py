"""Provider-agnostic Google Drive folder discovery with traversal safety bounds.

The concrete Google client only has to satisfy ``DriveDiscoveryProvider``.  Keeping traversal
here makes pagination, recursion, and partial-coverage behavior deterministic and easy
to exercise without credentials.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from extent_api.models import CoverageGap
from extent_api.services.drive_locator import DriveFolderLocator
from extent_api.services.source_formats import AdmittedSourceFormat, select_source_format

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DRIVE_SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"

ProviderErrorCode = Literal["inaccessible", "not_found", "rate_limited", "provider_failure"]
DiscoveryGapReason = Literal[
    "depth_limit",
    "inaccessible",
    "not_a_folder",
    "not_found",
    "page_limit",
    "pagination_cycle",
    "provider_failure",
    "rate_limited",
    "resource_limit",
]
SourceReason = Literal[
    "mime_extension_conflict",
    "shortcut_not_followed",
    "unsupported_mime_type",
]


class DiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriveDiscoveryLimits(DiscoveryModel):
    """Folder traversal caps used while discovering a workspace."""

    max_depth: Annotated[int, Field(ge=0, le=5)] = 5
    max_pages: Annotated[int, Field(gt=0, le=100)] = 100
    max_resources: Annotated[int, Field(gt=0, le=500)] = 500
    max_transient_retries: Annotated[int, Field(ge=0, le=2)] = 2
    page_size: Annotated[int, Field(gt=0, le=100)] = 100


class ShortcutDetails(DiscoveryModel):
    target_id: Annotated[str, Field(min_length=1, max_length=200)]
    target_mime_type: Annotated[str, Field(min_length=1, max_length=255)]
    target_resource_key: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class DriveProviderItem(DiscoveryModel):
    drive_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    id: Annotated[str, Field(min_length=1, max_length=200)]
    mime_type: Annotated[str, Field(min_length=1, max_length=255)]
    modified_time: Annotated[str, Field(min_length=1, max_length=80)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=1_024)]
    resource_key: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    shortcut_details: ShortcutDetails | None = None
    size_bytes: Annotated[int, Field(ge=0)] | None = None
    trashed: bool = False

    @model_validator(mode="after")
    def shortcut_metadata_matches_mime_type(self) -> Self:
        is_shortcut = self.mime_type == DRIVE_SHORTCUT_MIME_TYPE
        if is_shortcut != (self.shortcut_details is not None):
            raise ValueError("every shortcut, and only a shortcut, needs shortcut details")
        return self


class DriveGetRequest(DiscoveryModel):
    file_id: Annotated[str, Field(min_length=1, max_length=200)]
    resource_key: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    supports_all_drives: Literal[True] = True


class DriveListRequest(DiscoveryModel):
    corpora: Literal["user", "drive"]
    drive_id: Annotated[str, Field(min_length=1, max_length=200)] | None
    folder_id: Annotated[str, Field(min_length=1, max_length=200)]
    include_items_from_all_drives: bool
    page_size: Annotated[int, Field(gt=0, le=100)]
    page_token: Annotated[str, Field(min_length=1, max_length=2_048)] | None
    supports_all_drives: Literal[True] = True

    @model_validator(mode="after")
    def shared_drive_flags_are_consistent(self) -> Self:
        is_shared_drive = self.drive_id is not None
        if is_shared_drive != (self.corpora == "drive"):
            raise ValueError("shared-drive listing requires corpora=drive and a drive id")
        if self.include_items_from_all_drives != is_shared_drive:
            raise ValueError("shared-drive listing must include items from all drives")
        return self


class DriveProviderError(DiscoveryModel):
    code: ProviderErrorCode
    retryable: bool
    status: Literal["error"] = "error"


class DriveMetadataSuccess(DiscoveryModel):
    item: DriveProviderItem
    status: Literal["ok"] = "ok"


class DriveListSuccess(DiscoveryModel):
    items: Annotated[list[DriveProviderItem], Field(max_length=100)]
    next_page_token: Annotated[str, Field(min_length=1, max_length=2_048)] | None = None
    status: Literal["ok"] = "ok"


DriveMetadataResponse = DriveMetadataSuccess | DriveProviderError
DriveListResponse = DriveListSuccess | DriveProviderError


class DriveDiscoveryProvider(Protocol):
    """Narrow synchronous seam implemented by the maintained Google client adapter."""

    def get_item(self, request: DriveGetRequest) -> DriveMetadataResponse: ...

    def list_children(self, request: DriveListRequest) -> DriveListResponse: ...


class DiscoveredSource(DiscoveryModel):
    depth: Annotated[int, Field(ge=0, le=6)]
    drive_file_id: Annotated[str, Field(min_length=1, max_length=200)]
    ingestion_mode: Literal["download_binary", "download_text", "export_text"] | None
    mime_type: Annotated[str, Field(min_length=1, max_length=255)]
    modified_time: Annotated[str, Field(min_length=1, max_length=80)] | None
    name: Annotated[str, Field(min_length=1, max_length=1_024)]
    parent_folder_id: Annotated[str, Field(min_length=1, max_length=200)]
    path: Annotated[list[str], Field(min_length=2, max_length=8)]
    reason_code: SourceReason | None
    resource_key: Annotated[str, Field(min_length=1, max_length=200)] | None
    size_bytes: Annotated[int, Field(ge=0)] | None
    status: Literal["queued", "unsupported", "capped"]


class DiscoveryGap(DiscoveryModel):
    folder_id: Annotated[str, Field(min_length=1, max_length=200)]
    folder_name: Annotated[str, Field(min_length=1, max_length=1_024)]
    path: Annotated[list[str], Field(min_length=1, max_length=7)]
    reason_code: DiscoveryGapReason


class DiscoveryCounts(DiscoveryModel):
    capped: Annotated[int, Field(ge=0)]
    discovered_files: Annotated[int, Field(ge=0)]
    folders_visited: Annotated[int, Field(ge=0)]
    provider_calls: Annotated[int, Field(ge=0)]
    queued: Annotated[int, Field(ge=0)]
    resources_seen: Annotated[int, Field(ge=0)]
    skipped_trashed: Annotated[int, Field(ge=0)]
    unsupported: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def file_counts_balance(self) -> Self:
        if self.queued + self.unsupported + self.capped != self.discovered_files:
            raise ValueError("every discovered file must have one terminal admission state")
        return self


class DriveDiscoveryResult(DiscoveryModel):
    counts: DiscoveryCounts
    coverage_gap_reasons: list[CoverageGap]
    discovery_complete: bool
    gaps: Annotated[list[DiscoveryGap], Field(max_length=100)]
    policy_version: Literal["drive-traversal-policy-v1"] = "drive-traversal-policy-v1"
    root_folder_id: Annotated[str, Field(min_length=1, max_length=200)]
    root_name: Annotated[str, Field(min_length=1, max_length=1_024)] | None
    sources: Annotated[list[DiscoveredSource], Field(max_length=500)]
    status: Literal["complete", "partial", "fatal"]


@dataclass(frozen=True)
class _FolderWork:
    depth: int
    drive_id: str | None
    folder_id: str
    name: str
    path: tuple[str, ...]


def discover_drive_folder(
    provider: DriveDiscoveryProvider,
    locator: DriveFolderLocator,
    *,
    limits: DriveDiscoveryLimits | None = None,
) -> DriveDiscoveryResult:
    """Confirm and recursively enumerate one folder within disclosed P0 caps."""

    active_limits = limits or DriveDiscoveryLimits()
    provider_calls = 1
    metadata = provider.get_item(
        DriveGetRequest(file_id=locator.folder_id, resource_key=locator.resource_key)
    )
    if metadata.status == "error":
        gap = _provider_gap(
            folder_id=locator.folder_id,
            folder_name="Pasted folder",
            path=("Pasted folder",),
            error=metadata,
        )
        return _result(
            capped=0,
            discovery_complete=False,
            folders_visited=0,
            gaps=[gap],
            provider_calls=provider_calls,
            resources_seen=0,
            root_folder_id=locator.folder_id,
            root_name=None,
            skipped_trashed=0,
            sources=[],
            status="fatal",
        )

    root = metadata.item
    if root.mime_type != DRIVE_FOLDER_MIME_TYPE or root.trashed:
        reason: DiscoveryGapReason = "not_found" if root.trashed else "not_a_folder"
        return _result(
            capped=0,
            discovery_complete=False,
            folders_visited=0,
            gaps=[
                DiscoveryGap(
                    folder_id=root.id,
                    folder_name=root.name,
                    path=[root.name],
                    reason_code=reason,
                )
            ],
            provider_calls=provider_calls,
            resources_seen=0,
            root_folder_id=locator.folder_id,
            root_name=root.name,
            skipped_trashed=0,
            sources=[],
            status="fatal",
        )

    queue = deque(
        [
            _FolderWork(
                depth=0,
                drive_id=root.drive_id,
                folder_id=root.id,
                name=root.name,
                path=(root.name,),
            )
        ]
    )
    scheduled_folder_ids = {root.id}
    visited_folder_ids: set[str] = set()
    sources: list[DiscoveredSource] = []
    gaps: list[DiscoveryGap] = []
    resources_seen = 0
    skipped_trashed = 0
    stop_run = False

    while queue and not stop_run:
        folder = queue.popleft()
        if folder.folder_id in visited_folder_ids:
            continue
        visited_folder_ids.add(folder.folder_id)
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        transient_retries = 0

        while True:
            if provider_calls >= active_limits.max_pages + 1:
                gaps.append(_limit_gap(folder, "page_limit"))
                stop_run = True
                break

            request = DriveListRequest(
                corpora="drive" if folder.drive_id is not None else "user",
                drive_id=folder.drive_id,
                folder_id=folder.folder_id,
                include_items_from_all_drives=folder.drive_id is not None,
                page_size=active_limits.page_size,
                page_token=page_token,
            )
            response = provider.list_children(request)
            provider_calls += 1

            if response.status == "error":
                if (
                    response.retryable
                    and transient_retries < active_limits.max_transient_retries
                ):
                    transient_retries += 1
                    continue
                gaps.append(
                    _provider_gap(
                        folder_id=folder.folder_id,
                        folder_name=folder.name,
                        path=folder.path,
                        error=response,
                    )
                )
                break

            transient_retries = 0
            for item in response.items:
                if resources_seen >= active_limits.max_resources:
                    gaps.append(_limit_gap(folder, "resource_limit"))
                    stop_run = True
                    break
                resources_seen += 1
                if item.trashed:
                    skipped_trashed += 1
                    continue

                child_depth = folder.depth + 1
                child_path = (*folder.path, item.name)
                if item.mime_type == DRIVE_FOLDER_MIME_TYPE:
                    if child_depth > active_limits.max_depth:
                        gaps.append(
                            DiscoveryGap(
                                folder_id=item.id,
                                folder_name=item.name,
                                path=list(child_path),
                                reason_code="depth_limit",
                            )
                        )
                    elif item.id not in scheduled_folder_ids:
                        scheduled_folder_ids.add(item.id)
                        queue.append(
                            _FolderWork(
                                depth=child_depth,
                                drive_id=item.drive_id or folder.drive_id,
                                folder_id=item.id,
                                name=item.name,
                                path=child_path,
                            )
                        )
                    continue

                sources.append(
                    _classify_source(
                        item,
                        depth=child_depth,
                        parent=folder,
                        path=child_path,
                    )
                )

            if stop_run or response.next_page_token is None:
                break
            if response.next_page_token in seen_page_tokens:
                gaps.append(_limit_gap(folder, "pagination_cycle"))
                break
            seen_page_tokens.add(response.next_page_token)
            page_token = response.next_page_token

    return _result(
        capped=sum(source.status == "capped" for source in sources),
        discovery_complete=not gaps,
        folders_visited=len(visited_folder_ids),
        gaps=gaps,
        provider_calls=provider_calls,
        resources_seen=resources_seen,
        root_folder_id=root.id,
        root_name=root.name,
        skipped_trashed=skipped_trashed,
        sources=sources,
        status="partial"
        if gaps or any(source.status != "queued" for source in sources)
        else "complete",
    )


def _classify_source(
    item: DriveProviderItem,
    *,
    depth: int,
    parent: _FolderWork,
    path: Sequence[str],
) -> DiscoveredSource:
    status: Literal["queued", "unsupported", "capped"]
    mode: Literal["download_binary", "download_text", "export_text"] | None
    reason: SourceReason | None

    if item.mime_type == DRIVE_SHORTCUT_MIME_TYPE:
        status, mode, reason = "unsupported", None, "shortcut_not_followed"
    else:
        source_format = select_source_format(name=item.name, mime_type=item.mime_type)
        if not isinstance(source_format, AdmittedSourceFormat):
            status, mode, reason = "unsupported", None, source_format.reason_code
        else:
            status, mode, reason = "queued", source_format.ingestion_mode, None

    return DiscoveredSource(
        depth=depth,
        drive_file_id=item.id,
        ingestion_mode=mode,
        mime_type=item.mime_type,
        modified_time=item.modified_time,
        name=item.name,
        parent_folder_id=parent.folder_id,
        path=list(path),
        reason_code=reason,
        resource_key=item.resource_key,
        size_bytes=item.size_bytes,
        status=status,
    )


def _provider_gap(
    *,
    folder_id: str,
    folder_name: str,
    path: Sequence[str],
    error: DriveProviderError,
) -> DiscoveryGap:
    return DiscoveryGap(
        folder_id=folder_id,
        folder_name=folder_name,
        path=list(path),
        reason_code=error.code,
    )


def _limit_gap(folder: _FolderWork, reason: DiscoveryGapReason) -> DiscoveryGap:
    return DiscoveryGap(
        folder_id=folder.folder_id,
        folder_name=folder.name,
        path=list(folder.path),
        reason_code=reason,
    )


def _result(
    *,
    capped: int,
    discovery_complete: bool,
    folders_visited: int,
    gaps: list[DiscoveryGap],
    provider_calls: int,
    resources_seen: int,
    root_folder_id: str,
    root_name: str | None,
    skipped_trashed: int,
    sources: list[DiscoveredSource],
    status: Literal["complete", "partial", "fatal"],
) -> DriveDiscoveryResult:
    coverage_reasons: list[CoverageGap] = []
    if any(source.status == "unsupported" for source in sources):
        coverage_reasons.append("unsupported")
    if capped or any(
        gap.reason_code in {"depth_limit", "page_limit", "resource_limit"} for gap in gaps
    ):
        coverage_reasons.append("capped")
    if any(gap.reason_code in {"inaccessible", "not_found"} for gap in gaps):
        coverage_reasons.append("inaccessible")
    if any(
        gap.reason_code in {"rate_limited", "provider_failure", "pagination_cycle"}
        for gap in gaps
    ):
        coverage_reasons.append("failed")

    queued = sum(source.status == "queued" for source in sources)
    unsupported = sum(source.status == "unsupported" for source in sources)
    return DriveDiscoveryResult(
        counts=DiscoveryCounts(
            capped=capped,
            discovered_files=len(sources),
            folders_visited=folders_visited,
            provider_calls=provider_calls,
            queued=queued,
            resources_seen=resources_seen,
            skipped_trashed=skipped_trashed,
            unsupported=unsupported,
        ),
        coverage_gap_reasons=coverage_reasons,
        discovery_complete=discovery_complete,
        gaps=gaps,
        root_folder_id=root_folder_id,
        root_name=root_name,
        sources=sources,
        status=status,
    )
