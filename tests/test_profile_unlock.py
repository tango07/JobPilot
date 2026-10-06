import asyncio

import pytest
from fastapi import HTTPException, Request

from backend.app import api_activate_profile, api_verify_password
from backend.database import create_profile, set_profile_password


def _request(cookie: str = "") -> Request:
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


def test_password_protected_profile_requires_unlock_cookie():
    profile = create_profile("Protected")
    set_profile_password(profile["id"], "correct horse battery staple")

    with pytest.raises(HTTPException) as error:
        asyncio.run(api_activate_profile(profile["id"], _request()))
    assert error.value.status_code == 403

    response = asyncio.run(api_verify_password(profile["id"], type("Body", (), {"password": "correct horse battery staple"})()))
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    activated = asyncio.run(api_activate_profile(profile["id"], _request(cookie)))
    assert activated["id"] == profile["id"]
