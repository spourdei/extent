"""Maintained-client adapter for Google Drive metadata, traversal, and content."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from typing import Any, Protocol, cast

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build  # type: ignore[import-untyped]
from googleapiclient.errors import HttpError  # type: ignore[import-untyped]

from extent_api.providers.google_oauth import GOOGLE_DRIVE_READONLY_SCOPE
from extent_api.services.drive_discovery import (
    DriveGetRequest,
    DriveListRequest,
    DriveListResponse,
    DriveListSuccess,
    DriveMetadataResponse,
    DriveMetadataSuccess,
    DriveProviderError,
    DriveProviderItem,
    ShortcutDetails,
)
from extent_api.services.source_ingestion import (
    BinaryDownloadError,
    BinaryDownloadRequest,
    BinaryDownloadResponse,
    BinaryDownloadSuccess,
    TextExportRequest,
)

_FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,size,trashed,driveId,resourceKey,"
    "shortcutDetails(targetId,targetMimeType,targetResourceKey)"
)


class _ContentRequest(Protocol):
    headers: MutableMapping[str, str]

    def execute(self) -> object: ...


def create_google_drive_provider(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> GoogleDriveProvider:
    """Build a Drive v3 service from a server-only refresh credential."""

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=[GOOGLE_DRIVE_READONLY_SCOPE],
    )
    service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    return GoogleDriveProvider(service)


class GoogleDriveProvider:
    """Translate Google client responses into the provider-neutral discovery seam."""

    def __init__(self, service: Any) -> None:
        self._service = service

    def get_item(self, request: DriveGetRequest) -> DriveMetadataResponse:
        try:
            provider_request = self._service.files().get(
                fileId=request.file_id,
                fields=_FILE_FIELDS,
                supportsAllDrives=request.supports_all_drives,
            )
            if request.resource_key is not None:
                provider_request.headers["X-Goog-Drive-Resource-Keys"] = (
                    f"{request.file_id}/{request.resource_key}"
                )
            payload = cast(Mapping[str, object], provider_request.execute())
            return DriveMetadataSuccess(item=_parse_item(payload))
        except (HttpError, RefreshError, OSError) as error:
            return _provider_error(error)
        except (KeyError, TypeError, ValueError):
            return DriveProviderError(code="provider_failure", retryable=False)

    def list_children(self, request: DriveListRequest) -> DriveListResponse:
        try:
            escaped_folder_id = request.folder_id.replace("'", "\\'")
            arguments: dict[str, object] = {
                "corpora": request.corpora,
                "fields": f"nextPageToken,files({_FILE_FIELDS})",
                "includeItemsFromAllDrives": request.include_items_from_all_drives,
                "pageSize": request.page_size,
                "q": f"'{escaped_folder_id}' in parents and trashed = false",
                "spaces": "drive",
                "supportsAllDrives": request.supports_all_drives,
            }
            if request.drive_id is not None:
                arguments["driveId"] = request.drive_id
            if request.page_token is not None:
                arguments["pageToken"] = request.page_token
            payload = cast(
                Mapping[str, object], self._service.files().list(**arguments).execute()
            )
            raw_items = payload.get("files", [])
            if not isinstance(raw_items, list):
                raise TypeError("Drive files payload must be a list")
            items = [_parse_item(_mapping(item)) for item in raw_items]
            raw_page_token = payload.get("nextPageToken")
            if raw_page_token is not None and not isinstance(raw_page_token, str):
                raise TypeError("Drive page token must be text")
            return DriveListSuccess(items=items, next_page_token=raw_page_token)
        except (HttpError, RefreshError, OSError) as error:
            return _provider_error(error)
        except (KeyError, TypeError, ValueError):
            return DriveProviderError(code="provider_failure", retryable=False)

    def download_binary(self, request: BinaryDownloadRequest) -> BinaryDownloadResponse:
        return self._execute_content_request(
            lambda: self._service.files().get_media(
                fileId=request.file_id, supportsAllDrives=True
            ),
            file_id=request.file_id,
            resource_key=request.resource_key,
        )

    def export_text(self, request: TextExportRequest) -> BinaryDownloadResponse:
        return self._execute_content_request(
            lambda: self._service.files().export_media(
                fileId=request.file_id, mimeType="text/plain"
            ),
            file_id=request.file_id,
            resource_key=request.resource_key,
        )

    def _execute_content_request(
        self,
        build_request: Callable[[], _ContentRequest],
        *,
        file_id: str,
        resource_key: str | None,
    ) -> BinaryDownloadResponse:
        try:
            provider_request = build_request()
            if resource_key is not None:
                provider_request.headers["X-Goog-Drive-Resource-Keys"] = (
                    f"{file_id}/{resource_key}"
                )
            content = provider_request.execute()
            if not isinstance(content, bytes):
                return BinaryDownloadError(code="provider_failure", retryable=False)
            return BinaryDownloadSuccess(content=content)
        except (HttpError, RefreshError, OSError) as error:
            provider_error = _provider_error(error)
            return BinaryDownloadError(
                code=provider_error.code,
                retryable=provider_error.retryable,
            )


def _parse_item(payload: Mapping[str, object]) -> DriveProviderItem:
    shortcut_payload = payload.get("shortcutDetails")
    shortcut = None
    if shortcut_payload is not None:
        raw_shortcut = _mapping(shortcut_payload)
        shortcut = ShortcutDetails(
            target_id=_required_text(raw_shortcut, "targetId"),
            target_mime_type=_required_text(raw_shortcut, "targetMimeType"),
            target_resource_key=_optional_text(raw_shortcut, "targetResourceKey"),
        )
    raw_size = payload.get("size")
    size = int(raw_size) if isinstance(raw_size, (str, int)) else None
    return DriveProviderItem(
        drive_id=_optional_text(payload, "driveId"),
        id=_required_text(payload, "id"),
        mime_type=_required_text(payload, "mimeType"),
        modified_time=_optional_text(payload, "modifiedTime"),
        name=_required_text(payload, "name"),
        resource_key=_optional_text(payload, "resourceKey"),
        shortcut_details=shortcut,
        size_bytes=size,
        trashed=payload.get("trashed") is True,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("Drive payload item must be an object")
    return cast(Mapping[str, object], value)


def _required_text(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Drive payload is missing {key}")
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Drive payload has an invalid {key}")
    return value


def _provider_error(error: HttpError | RefreshError | OSError) -> DriveProviderError:
    if isinstance(error, RefreshError):
        return DriveProviderError(code="inaccessible", retryable=False)
    status = error.resp.status if isinstance(error, HttpError) else None
    if status == 404:
        return DriveProviderError(code="not_found", retryable=False)
    if status in {401, 403}:
        return DriveProviderError(code="inaccessible", retryable=False)
    if status == 429:
        return DriveProviderError(code="rate_limited", retryable=True)
    return DriveProviderError(
        code="provider_failure",
        retryable=status is None or status >= 500,
    )
