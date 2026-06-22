from webssh.models import ConnectRequest
from webssh.session import BrowserConnection, SessionManager, TerminalSession


def test_browser_connection_is_hashable() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    connection = BrowserConnection(loop=None, queue=None)  # type: ignore[arg-type]

    session._clients.add(connection)

    assert connection in session._clients


def test_manager_reaps_session_after_idle_timeout(monkeypatch) -> None:
    now = 1000.0

    def clock() -> float:
        return now

    manager = SessionManager(
        idle_timeout_seconds=300.0,
        autostart_reaper=False,
        clock=clock,
    )
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000),
        clock=clock,
    )
    closed: list[str] = []
    monkeypatch.setattr(session, "close", lambda reason: closed.append(reason))

    manager._sessions[session.id] = session

    now = 1299.0
    assert manager.cleanup_expired() == []
    assert manager.get(session.id) is session

    now = 1300.0
    assert manager.cleanup_expired() == [session.id]
    assert manager.get(session.id) is None
    assert closed == ["No browser reconnected for 300 seconds; SSH session is being cleaned up."]


def test_manager_does_not_reap_attached_session() -> None:
    now = 1000.0

    def clock() -> float:
        return now

    manager = SessionManager(
        idle_timeout_seconds=300.0,
        autostart_reaper=False,
        clock=clock,
    )
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000),
        clock=clock,
    )
    connection = BrowserConnection(loop=None, queue=None)  # type: ignore[arg-type]
    session._clients.add(connection)
    session._last_client_detached_at = None
    manager._sessions[session.id] = session

    now = 2000.0

    assert manager.cleanup_expired() == []
    assert manager.get(session.id) is session
