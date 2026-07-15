"""Strict parsing for the Google Drive folder URLs accepted by Extent."""

from __future__ import annotations

import re
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict, Field

_FOLDER_ID = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
_RESOURCE_KEY = re.compile(r"^[A-Za-z0-9_-]{8,200}$")
_ALLOWED_UI_VALUES = {"drive_link", "sharing"}
_MAX_INPUT_LENGTH = 2_048

LocatorRejectionReason = Literal[
    "invalid_input_type",
    "empty_input",
    "input_too_long",
    "whitespace_not_allowed",
    "malformed_url",
    "unsupported_scheme",
    "credentials_not_allowed",
    "port_not_allowed",
    "fragment_not_allowed",
    "unsupported_host",
    "encoded_path_not_allowed",
    "path_traversal_not_allowed",
    "query_encoding_not_allowed",
    "query_smuggling_not_allowed",
    "duplicate_id_parameter",
    "duplicate_resource_key_parameter",
    "duplicate_ui_parameter",
    "unsupported_query_parameter",
    "missing_folder_id",
    "malformed_folder_id",
    "malformed_account_index",
    "malformed_resource_key",
    "single_file_url_not_allowed",
    "unsupported_path",
]


class LocatorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DriveFolderLocator(LocatorModel):
    account_index: Annotated[int, Field(ge=0, le=999)] | None = None
    folder_id: Annotated[str, Field(min_length=10, max_length=200)]
    kind: Literal["folder", "account_folder", "legacy_open"]
    resource_key: Annotated[str, Field(min_length=8, max_length=200)] | None = None


class AcceptedDriveFolderLocator(LocatorModel):
    api_confirmation_required: Literal[True] = True
    authorization_status: Literal["unverified"] = "unverified"
    locator: DriveFolderLocator
    provider: Literal["google_drive"] = "google_drive"
    status: Literal["accepted"] = "accepted"


class RejectedDriveFolderLocator(LocatorModel):
    reason_code: LocatorRejectionReason
    status: Literal["rejected"] = "rejected"


DriveFolderLocatorResult = AcceptedDriveFolderLocator | RejectedDriveFolderLocator


def parse_google_drive_folder_url(value: object) -> DriveFolderLocatorResult:
    """Accept known folder URL shapes without treating a URL as authorization."""

    if not isinstance(value, str):
        return _reject("invalid_input_type")
    if not value:
        return _reject("empty_input")
    if len(value) > _MAX_INPUT_LENGTH:
        return _reject("input_too_long")
    if any(character.isspace() for character in value):
        return _reject("whitespace_not_allowed")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return _reject("malformed_url")

    if parsed.scheme != "https":
        return _reject("unsupported_scheme")
    if parsed.username is not None or parsed.password is not None:
        return _reject("credentials_not_allowed")
    if port is not None:
        return _reject("port_not_allowed")
    if parsed.fragment:
        return _reject("fragment_not_allowed")
    if parsed.hostname != "drive.google.com":
        return _reject("unsupported_host")
    if "%" in parsed.path:
        return _reject("encoded_path_not_allowed")
    if ";" in parsed.query:
        return _reject("query_smuggling_not_allowed")
    if "%" in parsed.query:
        return _reject("query_encoding_not_allowed")

    raw_segments = parsed.path.split("/")
    if any(segment in {".", ".."} for segment in raw_segments):
        return _reject("path_traversal_not_allowed")
    if "//" in parsed.path[1:]:
        return _reject("unsupported_path")
    segments = [segment for segment in raw_segments if segment]

    try:
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return _reject("malformed_url")
    query: dict[str, str] = {}
    for key, item in query_pairs:
        if key not in {"id", "resourcekey", "usp"}:
            return _reject("unsupported_query_parameter")
        if key in query:
            duplicate_reasons: dict[str, LocatorRejectionReason] = {
                "id": "duplicate_id_parameter",
                "resourcekey": "duplicate_resource_key_parameter",
                "usp": "duplicate_ui_parameter",
            }
            return _reject(duplicate_reasons[key])
        query[key] = item

    if "usp" in query and query["usp"] not in _ALLOWED_UI_VALUES:
        return _reject("unsupported_query_parameter")
    resource_key = query.get("resourcekey")
    if resource_key is not None and _RESOURCE_KEY.fullmatch(resource_key) is None:
        return _reject("malformed_resource_key")

    if segments == ["open"]:
        folder_id = query.get("id")
        if folder_id is None or not folder_id:
            return _reject("missing_folder_id")
        if _FOLDER_ID.fullmatch(folder_id) is None:
            return _reject("malformed_folder_id")
        return _accept(
            DriveFolderLocator(
                folder_id=folder_id,
                kind="legacy_open",
                resource_key=resource_key,
            )
        )

    if "id" in query:
        return _reject("unsupported_query_parameter")
    if len(segments) >= 2 and segments[:2] == ["file", "d"]:
        return _reject("single_file_url_not_allowed")

    if len(segments) == 3 and segments[:2] == ["drive", "folders"]:
        folder_id = segments[2]
        kind: Literal["folder", "account_folder"] = "folder"
        account_index = None
    elif len(segments) == 5 and segments[:2] == ["drive", "u"] and segments[3] == "folders":
        account_value = segments[2]
        if not account_value.isascii() or not account_value.isdecimal():
            return _reject("malformed_account_index")
        account_index = int(account_value)
        if account_index > 999:
            return _reject("malformed_account_index")
        folder_id = segments[4]
        kind = "account_folder"
    else:
        return _reject("unsupported_path")

    if _FOLDER_ID.fullmatch(folder_id) is None:
        return _reject("malformed_folder_id")
    return _accept(
        DriveFolderLocator(
            account_index=account_index,
            folder_id=folder_id,
            kind=kind,
            resource_key=resource_key,
        )
    )


def _accept(locator: DriveFolderLocator) -> AcceptedDriveFolderLocator:
    return AcceptedDriveFolderLocator(locator=locator)


def _reject(reason: LocatorRejectionReason) -> RejectedDriveFolderLocator:
    return RejectedDriveFolderLocator(reason_code=reason)
