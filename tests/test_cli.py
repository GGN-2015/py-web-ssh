import asyncio
import socket

from webssh.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    WINDOWS_EXE_DEFAULT_ARGS,
    _bind_auto_port_sockets,
    _browser_launch_url,
    _effective_cli_args,
    _install_browser_launch_hook,
    _run_uvicorn_server,
    build_arg_parser,
)
import webssh.app as app_module
from webssh.runtime_config import DEFAULT_SUBTITLE, DEFAULT_TITLE


def test_cli_defaults_listen_on_all_interfaces_port_8022_and_default_branding() -> None:
    args = build_arg_parser().parse_args([])

    assert DEFAULT_HOST == "0.0.0.0"
    assert DEFAULT_PORT == 8022
    assert args.host == "0.0.0.0"
    assert args.port == 8022
    assert args.auto_port is False
    assert DEFAULT_TITLE == "py-web-ssh"
    assert DEFAULT_SUBTITLE == "Web SSH Client"
    assert args.title is None
    assert args.subtitle is None
    assert args.launch_browser is False
    assert args.ban_lan is False
    assert args.ban_dns is False
    assert args.ban_ipv6 is False
    assert args.ban_host == []


def test_cli_accepts_title_and_subtitle_arguments() -> None:
    args = build_arg_parser().parse_args(["--title", "Ops SSH", "--subtitle", "Production Access"])

    assert args.title == "Ops SSH"
    assert args.subtitle == "Production Access"


def test_cli_accepts_launch_browser_argument() -> None:
    args = build_arg_parser().parse_args(["--launch-browser"])

    assert args.launch_browser is True


def test_cli_accepts_auto_port_argument() -> None:
    args = build_arg_parser().parse_args(["--auto-port"])

    assert args.auto_port is True


def test_cli_accepts_ban_lan_argument() -> None:
    args = build_arg_parser().parse_args(["--ban-lan"])

    assert args.ban_lan is True


def test_cli_accepts_ban_dns_and_ban_ipv6_arguments() -> None:
    args = build_arg_parser().parse_args(["--ban-dns", "--ban-ipv6"])

    assert args.ban_dns is True
    assert args.ban_ipv6 is True


def test_cli_accepts_repeated_ban_host_arguments() -> None:
    args = build_arg_parser().parse_args(
        ["--ban-host", "internal.example.com", "--ban-host", "*.corp.local"]
    )

    assert args.ban_host == ["internal.example.com", "*.corp.local"]


def test_python_package_empty_args_keep_original_defaults(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_is_windows_frozen_exe", lambda: False)

    assert _effective_cli_args([]) == []


def test_windows_frozen_exe_empty_args_use_local_auto_launch_defaults(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_is_windows_frozen_exe", lambda: True)

    assert _effective_cli_args([]) == WINDOWS_EXE_DEFAULT_ARGS


def test_explicit_args_keep_python_package_behavior_even_for_windows_exe(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_is_windows_frozen_exe", lambda: True)

    assert _effective_cli_args(["--port", "9000"]) == ["--port", "9000"]


def test_auto_port_binds_first_available_port_after_occupied_port() -> None:
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    occupied_port = blocker.getsockname()[1]

    sockets, selected_port = _bind_auto_port_sockets("127.0.0.1", occupied_port)
    try:
        assert selected_port > occupied_port
        assert sockets[0].getsockname()[1] == selected_port
    finally:
        for sock in sockets:
            sock.close()
        blocker.close()


def test_browser_launch_url_prefers_loopback_socket() -> None:
    server = FakeServer(
        addresses=[
            ("192.168.1.10", 8022),
            ("127.0.0.1", 8022),
            ("0.0.0.0", 8022),
        ],
    )

    assert _browser_launch_url(server, "0.0.0.0", 8022) == "http://127.0.0.1:8022"


def test_browser_launch_url_uses_loopback_for_wildcard_host() -> None:
    server = FakeServer(addresses=[])

    assert _browser_launch_url(server, "0.0.0.0", 8022) == "http://127.0.0.1:8022"
    assert _browser_launch_url(server, "::", 8022) == "http://[::1]:8022"


def test_browser_launch_hook_opens_once_after_successful_startup() -> None:
    opened: list[str] = []
    server = FakeServer(addresses=[("127.0.0.1", 8022)])
    _install_browser_launch_hook(server, "0.0.0.0", 8022, opener=opened.append)

    asyncio.run(server.startup())
    asyncio.run(server.startup())

    assert opened == ["http://127.0.0.1:8022"]


def test_browser_launch_hook_does_not_open_when_server_did_not_start() -> None:
    opened: list[str] = []
    server = FakeServer(addresses=[("127.0.0.1", 8022)], started_after_startup=False)
    _install_browser_launch_hook(server, "0.0.0.0", 8022, opener=opened.append)

    asyncio.run(server.startup())

    assert opened == []


def test_browser_launch_hook_does_not_fail_server_when_browser_open_fails() -> None:
    server = FakeServer(addresses=[("127.0.0.1", 8022)])

    def failing_open(_url: str) -> None:
        raise RuntimeError("browser unavailable")

    _install_browser_launch_hook(server, "0.0.0.0", 8022, opener=failing_open)

    asyncio.run(server.startup())

    assert server.started is True


def test_uvicorn_keyboard_interrupt_is_treated_as_clean_shutdown() -> None:
    server = KeyboardInterruptServer()

    _run_uvicorn_server(server)

    assert server.run_called is True


class FakeSocket:
    def __init__(self, address: tuple[str, int]) -> None:
        self.address = address

    def getsockname(self) -> tuple[str, int]:
        return self.address


class FakeAsyncioServer:
    def __init__(self, addresses: list[tuple[str, int]]) -> None:
        self.sockets = [FakeSocket(address) for address in addresses]


class FakeServer:
    def __init__(
        self,
        addresses: list[tuple[str, int]],
        started_after_startup: bool = True,
    ) -> None:
        self.servers = [FakeAsyncioServer(addresses)]
        self.started = False
        self.started_after_startup = started_after_startup

    async def startup(self) -> None:
        self.started = self.started_after_startup


class KeyboardInterruptServer:
    def __init__(self) -> None:
        self.run_called = False

    def run(self, sockets=None) -> None:
        self.run_called = True
        raise KeyboardInterrupt
