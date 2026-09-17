import base64
import importlib


def test_fernet_key_supports_env_secret(monkeypatch):
    raw_secret = "jobpilot-dev-secret-key-123456"
    env_key = base64.urlsafe_b64encode(raw_secret.encode()).decode().rstrip("=")
    monkeypatch.setenv("JOBPILOT_SECRET_KEY", env_key)

    import backend.encryption as encryption
    importlib.reload(encryption)

    token = encryption.encrypt("hello-jobpilot")
    assert token
    assert encryption.decrypt(token) == "hello-jobpilot"
