from fastapi.testclient import TestClient

from webssh.app import app
from webssh.auth import configure_pin
from webssh.client_session import COOKIE_NAME, client_sessions


def teardown_function() -> None:
    configure_pin(None)


def test_first_request_gets_client_session_cookie() -> None:
    configure_pin(None)
    client = TestClient(app)

    response = client.get("/api/auth/status")
    cookie = response.cookies.get(COOKIE_NAME)

    assert response.status_code == 200
    assert cookie is not None
    assert client_sessions.get(cookie) is not None


def test_client_session_cookie_is_reused() -> None:
    configure_pin(None)
    client = TestClient(app)

    first = client.get("/api/auth/status").cookies.get(COOKIE_NAME)
    second = client.get("/api/auth/status").cookies.get(COOKIE_NAME)

    assert first is not None
    assert second is None
    assert client_sessions.get(first) is not None


def test_pin_rejection_still_assigns_client_session_cookie() -> None:
    configure_pin("123456")
    client = TestClient(app)

    response = client.get("/api/sessions")
    cookie = response.cookies.get(COOKIE_NAME)

    assert response.status_code == 401
    assert cookie is not None
    assert client_sessions.get(cookie) is not None
