"""Strict input-boundary tests for Google Drive folder locators."""

import pytest

from extent_api.services.drive_locator import (
    AcceptedDriveFolderLocator,
    RejectedDriveFolderLocator,
    parse_google_drive_folder_url,
)

FOLDER_ID = "1AbCdEfGhIjKlMnOpQrStUv"
RESOURCE_KEY = "resourceKey_123"


def test_supported_folder_urls_are_parsed_without_claiming_authorization() -> None:
    direct = parse_google_drive_folder_url(
        f"https://drive.google.com/drive/folders/{FOLDER_ID}"
        f"?resourcekey={RESOURCE_KEY}&usp=drive_link"
    )
    account = parse_google_drive_folder_url(
        f"https://drive.google.com/drive/u/2/folders/{FOLDER_ID}/"
    )
    legacy = parse_google_drive_folder_url(
        f"https://drive.google.com/open?id={FOLDER_ID}&usp=sharing"
    )

    assert isinstance(direct, AcceptedDriveFolderLocator)
    assert direct.authorization_status == "unverified"
    assert direct.api_confirmation_required is True
    assert direct.locator.resource_key == RESOURCE_KEY
    assert isinstance(account, AcceptedDriveFolderLocator)
    assert account.locator.kind == "account_folder"
    assert account.locator.account_index == 2
    assert isinstance(legacy, AcceptedDriveFolderLocator)
    assert legacy.locator.kind == "legacy_open"


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (None, "invalid_input_type"),
        ("", "empty_input"),
        (f"http://drive.google.com/drive/folders/{FOLDER_ID}", "unsupported_scheme"),
        (f"https://evil.example/drive/folders/{FOLDER_ID}", "unsupported_host"),
        (
            f"https://user@drive.google.com/drive/folders/{FOLDER_ID}",
            "credentials_not_allowed",
        ),
        (f"https://drive.google.com:443/drive/folders/{FOLDER_ID}", "port_not_allowed"),
        (
            f"https://drive.google.com/drive/folders/{FOLDER_ID}#fragment",
            "fragment_not_allowed",
        ),
        (
            f"https://drive.google.com/file/d/{FOLDER_ID}/view",
            "single_file_url_not_allowed",
        ),
        (
            f"https://drive.google.com/drive/folders/%2e%2e{FOLDER_ID}",
            "encoded_path_not_allowed",
        ),
        (
            f"https://drive.google.com/open?id={FOLDER_ID}&id={FOLDER_ID}",
            "duplicate_id_parameter",
        ),
        (
            f"https://drive.google.com/drive/folders/{FOLDER_ID}?next=https://evil.example",
            "unsupported_query_parameter",
        ),
    ],
)
def test_ambiguous_or_unsafe_folder_urls_fail_with_a_stable_reason(
    value: object, reason: str
) -> None:
    result = parse_google_drive_folder_url(value)

    assert isinstance(result, RejectedDriveFolderLocator)
    assert result.reason_code == reason
