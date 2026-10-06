import pytest
from fastapi import HTTPException

from backend.app import _validate_public_http_url


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "https://user:password@example.com/jobs",
    "http://localhost:8765/jobs",
    "http://127.0.0.1/jobs",
    "http://192.168.1.5/jobs",
])
def test_custom_site_url_rejects_unsafe_targets(url):
    with pytest.raises(HTTPException) as error:
        _validate_public_http_url(url, "Base URL")
    assert error.value.status_code == 400


def test_custom_site_url_accepts_public_https_url():
    assert _validate_public_http_url("https://careers.example.com/jobs", "Base URL") == "https://careers.example.com/jobs"
