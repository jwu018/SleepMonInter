"""Who may call the API.

The browser never talks to this API. Only the Next.js server does, after it has checked the
login session, and it proves who it is by sending a shared secret in the X-API-Key header.
That keeps session handling in one place (Next.js + Supabase Auth) while the API still
refuses anyone who finds its address.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    expected = settings.api_shared_secret
    if not expected:
        return  # no secret configured: open, for local development only
    # compare_digest takes the same time whether the first or the last character is wrong,
    # so response timing cannot be used to guess the secret one character at a time.
    if x_api_key is None or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing or wrong API key")
