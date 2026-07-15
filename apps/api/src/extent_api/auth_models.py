"""Public authentication read models generated into the React client."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from extent_api.models import ApiModel


class GoogleAccountView(ApiModel):
    display_name: Annotated[str, Field(min_length=1, max_length=200)] | None
    email: Annotated[str, Field(min_length=3, max_length=320)]


class SignedOutSessionView(ApiModel):
    google_oauth_available: bool
    status: Literal["signed_out"] = "signed_out"


class AuthenticatedSessionView(ApiModel):
    account: GoogleAccountView
    expires_at: AwareDatetime
    google_oauth_available: Literal[True] = True
    status: Literal["authenticated"] = "authenticated"


SessionView = SignedOutSessionView | AuthenticatedSessionView


class AuthErrorView(ApiModel):
    code: Literal["configuration_unavailable", "origin_rejected"]
    message: Annotated[str, Field(min_length=1, max_length=280)]
