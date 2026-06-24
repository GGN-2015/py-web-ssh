from webssh.models import ConnectRequest
from webssh.session import BrowserConnection, CWD_OSC_PREFIX, CWD_OSC_SUFFIX, SessionManager, TerminalSession
from webssh.ssh_client import HostKeyInfo


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


def test_host_key_confirmation_input_accepts_y(monkeypatch) -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    outputs: list[bytes] = []
    monkeypatch.setattr(session, "_append_output", lambda data: outputs.append(data))

    with session._host_key_lock:
        session._awaiting_host_key_confirmation = True

    assert session._handle_host_key_confirmation_input(b"Y") is True

    with session._host_key_lock:
        assert session._host_key_decision is True


def test_host_key_prompt_contains_fingerprints() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    host_key = HostKeyInfo(
        key_type="ssh-ed25519",
        sha256_fingerprint="SHA256:test",
        md5_fingerprint="MD5:00",
        key_base64="key",
    )

    prompt = session._host_key_prompt(host_key)

    assert "SHA256:test" in prompt
    assert "MD5:00" in prompt
    assert "Continue connecting? Type Y or N" in prompt


def test_hidden_cwd_osc_updates_replay_without_terminal_output() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    output = b"before" + CWD_OSC_PREFIX + b"/srv/app" + CWD_OSC_SUFFIX + b"after"

    assert session._filter_hidden_terminal_output(output) == b"beforeafter"

    payload = session.replay_payload()
    assert payload["cwd"] == "/srv/app"
    assert payload["history_next_seq"] == 0


def test_hidden_cwd_osc_can_span_recv_chunks() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    first = b"visible" + CWD_OSC_PREFIX[:4]
    second = CWD_OSC_PREFIX[4:] + b"/home/root" + CWD_OSC_SUFFIX + b"done"

    assert session._filter_hidden_terminal_output(first) == b"visible"
    assert session._filter_hidden_terminal_output(second) == b"done"
    assert session.replay_payload()["cwd"] == "/home/root"


def test_hidden_terminal_command_echo_is_removed_across_chunks() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    session._hidden_command_echoes.append(b"secret command")

    assert session._filter_hidden_terminal_output(b"before secret") == b"before "
    assert session._filter_hidden_terminal_output(b" command\r\nafter") == b"after"


def test_hidden_terminal_command_echo_waits_for_trailing_newline() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    session._hidden_command_echoes.append(b"secret command")

    assert session._filter_hidden_terminal_output(b"secret command") == b""
    assert session._filter_hidden_terminal_output(b"\r\nafter") == b"after"
