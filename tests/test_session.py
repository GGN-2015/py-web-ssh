from webssh.models import ConnectRequest
from webssh.session import (
    BrowserConnection,
    CWD_INSTALL_COMMAND_TEMPLATE,
    CWD_OSC_PREFIX,
    CWD_OSC_SUFFIX,
    SessionManager,
    TerminalSession,
)
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
    output = b"before" + session._cwd_osc_prefix + b"/srv/app" + CWD_OSC_SUFFIX + b"after"

    assert session._filter_hidden_terminal_output(output) == b"beforeafter"

    payload = session.replay_payload()
    assert payload["cwd"] == "/srv/app"
    assert payload["history_next_seq"] == 0


def test_hidden_cwd_osc_can_span_recv_chunks() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    first = b"visible" + session._cwd_osc_prefix[:4]
    second = session._cwd_osc_prefix[4:] + b"/home/root" + CWD_OSC_SUFFIX + b"done"

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


def test_cwd_sync_off_filters_but_does_not_store_hidden_cwd() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000, cwd_sync=False)
    )
    output = session._cwd_osc_prefix + b"/srv/app" + CWD_OSC_SUFFIX + b"visible"

    assert session._filter_hidden_terminal_output(output) == b"visible"
    assert session.replay_payload()["cwd"] == ""
    assert session.replay_payload()["cwd_sync"] is False


def test_reenabled_cwd_sync_waits_until_directory_changes() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    session._filter_hidden_terminal_output(session._cwd_osc_prefix + b"/srv/app" + CWD_OSC_SUFFIX)
    session.set_cwd_sync_enabled(False)
    session._filter_hidden_terminal_output(session._cwd_osc_prefix + b"/srv/app" + CWD_OSC_SUFFIX)

    session.set_cwd_sync_enabled(True)
    session._filter_hidden_terminal_output(session._cwd_osc_prefix + b"/srv/app" + CWD_OSC_SUFFIX)
    assert session.replay_payload()["cwd"] == ""

    session._filter_hidden_terminal_output(session._cwd_osc_prefix + b"/srv/next" + CWD_OSC_SUFFIX)
    assert session.replay_payload()["cwd"] == "/srv/next"


def test_non_session_cwd_osc_is_not_treated_as_hidden_sync() -> None:
    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    other = CWD_OSC_PREFIX + b"other-token=/tmp" + CWD_OSC_SUFFIX

    assert session._filter_hidden_terminal_output(other) == other
    assert session.replay_payload()["cwd"] == ""


def test_send_input_does_not_probe_based_on_cd_like_text() -> None:
    class FakeChannel:
        def __init__(self) -> None:
            self.sent: list[bytes] = []

        def sendall(self, data: bytes) -> None:
            self.sent.append(data)

    session = TerminalSession(
        ConnectRequest(host="example.com", username="root", scrollback_bytes=100_000)
    )
    channel = FakeChannel()
    session._channel = channel  # type: ignore[assignment]
    session.state = "connected"

    session.send_input(b"cd /tmp\r")

    assert channel.sent == [b"cd /tmp\r"]


def test_posix_cwd_monitor_does_not_override_cd_function() -> None:
    assert "PS1=" in CWD_INSTALL_COMMAND_TEMPLATE
    assert "PS2=" in CWD_INSTALL_COMMAND_TEMPLATE
    assert "cd(){" not in CWD_INSTALL_COMMAND_TEMPLATE
    assert "command cd" not in CWD_INSTALL_COMMAND_TEMPLATE
