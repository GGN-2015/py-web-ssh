from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from webssh.app import app
from webssh.auth import configure_pin


def teardown_function() -> None:
    configure_pin(None)


def test_auth_status_when_pin_is_disabled() -> None:
    configure_pin(None)
    client = TestClient(app)

    response = client.get("/api/auth/status")

    assert response.status_code == 200
    assert response.json() == {"enabled": False, "authorized": True}


def test_pin_protects_api_routes_until_login() -> None:
    configure_pin("123456")
    client = TestClient(app)

    assert client.get("/api/sessions").status_code == 401
    assert client.post("/api/auth/login", json={"pin": "bad"}).status_code == 401

    login = client.post("/api/auth/login", json={"pin": "123456"})

    assert login.status_code == 200
    assert client.get("/api/sessions").status_code == 200


def test_pin_auth_cookie_does_not_contain_plain_pin() -> None:
    configure_pin("123456")
    client = TestClient(app)

    response = client.post("/api/auth/login", json={"pin": "123456"})
    cookie = response.cookies.get("py_web_ssh_pin")

    assert response.status_code == 200
    assert cookie is not None
    assert "123456" not in cookie
    assert len(cookie.split(":")) == 3


def test_websocket_requires_pin_cookie() -> None:
    configure_pin("123456")
    client = TestClient(app)

    try:
        with client.websocket_connect("/ws/sessions/missing"):
            raise AssertionError("WebSocket unexpectedly connected")
    except WebSocketDisconnect as exc:
        assert exc.code == 4401
        assert exc.reason == "PIN authentication required"
