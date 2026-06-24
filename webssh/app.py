from __future__ import annotations

import asyncio
import argparse
import base64
import os
import socket
import sys
import webbrowser
from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import auth
from .auth import add_pin_argument, configure_pin
from .client_session import ensure_client_session_cookie
from .files import (
    FileTransferCancelled,
    MIN_UPLOAD_COMMAND_BYTES,
    REQUESTED_UPLOAD_COMMAND_BYTES,
    download_file_via_ssh,
    filename_for_download,
    upload_file_via_ssh,
)
from .models import ConnectRequest, CreateSessionResponse, FileTransferResponse
from .runtime_config import add_runtime_lock_arguments, configure_runtime_locks
from . import runtime_config as runtime_config_module
from .session import SessionManager
from .ssh_client import supported_algorithms_payload, validate_disabled_algorithms
from .transfers import TransferManager


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PUBLIC_PATHS = {"/", "/api/auth/status", "/api/auth/login", "/favicon.ico"}
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8022
WINDOWS_EXE_DEFAULT_ARGS = ["--host", "127.0.0.1", "--auto-port", "--launch-browser"]

app = FastAPI(title="py-web-ssh", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
sessions = SessionManager()
transfers = TransferManager()


@app.middleware("http")
async def require_pin_cookie(request: Request, call_next):
    path = request.url.path
    if not (
        path.startswith("/static/")
        or path in PUBLIC_PATHS
        or auth.pin_auth.is_request_authorized(request)
    ):
        response = JSONResponse({"detail": "PIN authentication required."}, status_code=401)
        ensure_client_session_cookie(request, response)
        return response

    response = await call_next(request)
    ensure_client_session_cookie(request, response)
    return response


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    config = runtime_config_module.runtime_config
    replacements = {
        "__APP_TITLE__": escape(config.title, quote=True),
        "__APP_SUBTITLE__": escape(config.subtitle, quote=True),
        "__APP_VERSION__": escape(__version__, quote=True),
    }
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return HTMLResponse(html)


@app.get("/api/auth/status")
def auth_status(request: Request) -> JSONResponse:
    return JSONResponse(
        {
            **auth.pin_auth.status_payload(),
            "authorized": auth.pin_auth.is_request_authorized(request),
        }
    )


@app.get("/api/config")
def public_config() -> JSONResponse:
    return JSONResponse(runtime_config_module.runtime_config.public_payload())


@app.get("/api/algorithms")
def algorithms() -> JSONResponse:
    return JSONResponse(supported_algorithms_payload())


@app.post("/api/auth/login")
async def auth_login(request: Request) -> JSONResponse:
    payload = await request.json()
    pin = str(payload.get("pin", ""))
    if not auth.pin_auth.verify_pin(pin):
        raise HTTPException(status_code=401, detail="Invalid PIN.")
    response = JSONResponse({"ok": True, "enabled": auth.pin_auth.enabled})
    auth.pin_auth.set_cookie(response, pin)
    return response


@app.get("/sessions/{session_id}/logs", response_class=HTMLResponse)
def logs_page(session_id: str) -> HTMLResponse:
    html = (STATIC_DIR / "logs.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("__SESSION_ID__", session_id))


@app.post("/api/sessions", response_model=CreateSessionResponse)
def create_session(config: ConnectRequest) -> CreateSessionResponse:
    locked_config = runtime_config_module.runtime_config.apply_to_connect_request(config)
    try:
        locked_config.disabled_algorithms = {
            group: list(values)
            for group, values in validate_disabled_algorithms(locked_config.disabled_algorithms).items()
        }
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session = sessions.create(locked_config)
    return CreateSessionResponse(
        session_id=session.id,
        logs_url=f"/sessions/{session.id}/logs",
        websocket_url=f"/ws/sessions/{session.id}",
    )


@app.get("/api/sessions")
def list_sessions() -> JSONResponse:
    return JSONResponse([session.summary().model_dump(mode="json") for session in sessions.list()])


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str) -> JSONResponse:
    session = _require_session(session_id)
    return JSONResponse(session.summary().model_dump(mode="json"))


@app.get("/api/sessions/{session_id}/logs")
def get_logs(session_id: str) -> JSONResponse:
    session = _require_session(session_id)
    return JSONResponse(
        {
            "session": session.summary().model_dump(mode="json"),
            "logs": [entry.model_dump(mode="json") for entry in session.logs()],
        }
    )


@app.delete("/api/sessions/{session_id}")
def close_session(session_id: str) -> JSONResponse:
    if not sessions.close(session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    return JSONResponse({"ok": True})


@app.post("/api/sessions/{session_id}/files/upload", response_model=FileTransferResponse)
def upload(
    session_id: str,
    remote_path: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile, File()],
    transfer_id: Annotated[str | None, Form()] = None,
    total_bytes: Annotated[int | None, Form()] = None,
    upload_command_size_bytes: Annotated[int | None, Form()] = None,
) -> FileTransferResponse:
    session = _require_session(session_id)
    expected_host_key = session.confirmed_host_key
    if expected_host_key is None:
        raise HTTPException(
            status_code=409,
            detail="SSH server host key has not been confirmed in the terminal yet.",
        )
    tracker = transfers.get(transfer_id) if transfer_id else None
    if transfer_id and tracker is None:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    requested_command_size = _normalize_upload_command_size(upload_command_size_bytes)
    if tracker is None:
        tracker = transfers.create_upload(total_bytes or _content_length(file), remote_path)
    try:
        method, transferred, final_remote_path = upload_file_via_ssh(
            session.config,
            file.file,
            remote_path,
            total_bytes or _content_length(file),
            expected_host_key,
            requested_command_size=requested_command_size,
            original_filename=file.filename,
            cancel_event=tracker.cancel_event,
            progress=tracker.update_progress,
            log=session.log,
        )
    except FileTransferCancelled as exc:
        message = f"File upload cancelled: {exc}"
        tracker.cancelled(message)
        session.log("warning", message, None)
        raise HTTPException(status_code=499, detail=message) from exc
    except Exception as exc:
        tracker.fail(str(exc))
        session.log("error", f"File upload failed: {exc}", None)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    message = f"Uploaded {transferred} bytes to {final_remote_path} using {method}."
    tracker.complete(transferred, message, remote_path=final_remote_path)
    session.log("info", message, None)
    return FileTransferResponse(
        ok=True,
        method=method,
        bytes_transferred=transferred,
        remote_path=final_remote_path,
        message=message,
        transfer_id=tracker.id,
    )


@app.post("/api/sessions/{session_id}/files/uploads")
async def create_upload_task(session_id: str, request: Request) -> JSONResponse:
    session = _require_session(session_id)
    if session.confirmed_host_key is None:
        raise HTTPException(
            status_code=409,
            detail="SSH server host key has not been confirmed in the terminal yet.",
        )
    payload = await request.json()
    remote_path = str(payload.get("remote_path", "")).strip()
    if not remote_path:
        raise HTTPException(status_code=422, detail="remote_path is required.")
    total_bytes = payload.get("total_bytes")
    if total_bytes is not None:
        total_bytes = int(total_bytes)
    tracker = transfers.create_upload(total_bytes, remote_path)
    return JSONResponse(
        {
            "transfer_id": tracker.id,
            "state": tracker.status().state,
            "remote_path": remote_path,
            "total_bytes": total_bytes,
        }
    )


@app.get("/api/transfers/{transfer_id}")
def get_transfer(transfer_id: str) -> JSONResponse:
    tracker = transfers.get(transfer_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    status = tracker.status()
    return JSONResponse(
        {
            "transfer_id": status.transfer_id,
            "state": status.state,
            "bytes_transferred": status.bytes_transferred,
            "total_bytes": status.total_bytes,
            "remote_path": status.remote_path,
            "message": status.message,
            "created_at": status.created_at.isoformat(),
            "updated_at": status.updated_at.isoformat(),
        }
    )


@app.delete("/api/transfers/{transfer_id}")
def cancel_transfer(transfer_id: str) -> JSONResponse:
    if not transfers.cancel(transfer_id):
        raise HTTPException(status_code=404, detail="Transfer not found.")
    return JSONResponse({"ok": True})


@app.get("/api/sessions/{session_id}/files/download")
def download(session_id: str, remote_path: str) -> StreamingResponse:
    session = _require_session(session_id)
    expected_host_key = session.confirmed_host_key
    if expected_host_key is None:
        raise HTTPException(
            status_code=409,
            detail="SSH server host key has not been confirmed in the terminal yet.",
        )
    try:
        method, stream = download_file_via_ssh(session.config, remote_path, expected_host_key)
    except Exception as exc:
        session.log("error", f"File download failed: {exc}", None)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session.log("info", f"Downloading {remote_path} using {method}.", None)
    return StreamingResponse(
        stream,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_for_download(remote_path)}"',
            "X-Transfer-Method": method,
        },
    )


@app.websocket("/ws/sessions/{session_id}")
async def websocket_session(websocket: WebSocket, session_id: str) -> None:
    if not auth.pin_auth.is_websocket_authorized(websocket):
        await websocket.close(code=4401, reason="PIN authentication required")
        return

    session = sessions.get(session_id)
    if session is None:
        await websocket.close(code=4404, reason="Session not found")
        return

    await websocket.accept()
    connection = session.attach(websocket)
    sender: asyncio.Task | None = None
    try:
        await websocket.send_json({"type": "session", "session_id": session.id})
        await websocket.send_json(session.replay_payload())
        sender = asyncio.create_task(_websocket_sender(websocket, connection.queue))
        while True:
            message = await websocket.receive_json()
            await _handle_ws_message(session, message)
    except WebSocketDisconnect:
        pass
    finally:
        session.detach(connection)
        if sender is not None:
            sender.cancel()
            try:
                await sender
            except asyncio.CancelledError:
                pass


async def _websocket_sender(websocket: WebSocket, queue: asyncio.Queue[dict]) -> None:
    while True:
        message = await queue.get()
        await websocket.send_json(message)


async def _handle_ws_message(session, message: dict) -> None:
    message_type = message.get("type")
    try:
        if message_type == "input":
            session.send_input(base64.b64decode(message.get("data", "")))
        elif message_type == "resize":
            session.resize(int(message.get("cols", 100)), int(message.get("rows", 30)))
        elif message_type == "snapshot":
            session.save_snapshot(int(message.get("seq", 0)), base64.b64decode(message.get("data", "")))
        elif message_type == "disconnect":
            session.close("Browser requested SSH disconnect.")
        elif message_type == "ping":
            return
        else:
            session.log("warning", f"Unknown WebSocket message type: {message_type}", None)
    except Exception as exc:
        session.log("warning", f"Could not process browser message {message_type}: {exc}", None)


def _require_session(session_id: str):
    session = sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


def _content_length(upload: UploadFile) -> int | None:
    size_header = upload.headers.get("content-length")
    if size_header:
        try:
            return int(size_header)
        except ValueError:
            return None
    return None


def _normalize_upload_command_size(value: int | None) -> int:
    if value is None:
        return REQUESTED_UPLOAD_COMMAND_BYTES
    if value < 1:
        raise HTTPException(
            status_code=422,
            detail="upload_command_size_bytes must be a positive integer.",
        )
    return max(value, MIN_UPLOAD_COMMAND_BYTES)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-web-ssh")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")
    parser.add_argument(
        "--auto-port",
        action="store_true",
        help="Start at --port and bind the first available port.",
    )
    parser.add_argument(
        "--launch-browser",
        action="store_true",
        help="Open the web UI in the system default browser after the server starts.",
    )
    add_pin_argument(parser)
    add_runtime_lock_arguments(parser)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(_effective_cli_args(argv))

    configure_pin(args.pin)
    configure_runtime_locks(
        title=args.title,
        subtitle=args.subtitle,
        lock_host=args.lock_host,
        lock_username=args.lock_username,
        lock_password=args.lock_pwd,
        lock_private_key=args.lock_private_key,
        ban_lan=args.ban_lan,
        ban_dns=args.ban_dns,
        ban_ipv6=args.ban_ipv6,
        ban_hosts=args.ban_host,
    )
    run_server(args.host, args.port, launch_browser=args.launch_browser, auto_port=args.auto_port)


def _effective_cli_args(argv: list[str] | None = None) -> list[str]:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args and _is_windows_frozen_exe():
        return WINDOWS_EXE_DEFAULT_ARGS.copy()
    return args


def _is_windows_frozen_exe() -> bool:
    return os.name == "nt" and bool(getattr(sys, "frozen", False))


def run_server(
    host: str,
    port: int,
    launch_browser: bool = False,
    auto_port: bool = False,
) -> None:
    import uvicorn

    sockets = None
    bind_port = port
    if auto_port:
        sockets, bind_port = _bind_auto_port_sockets(host, port)
        print(f"Auto-selected port {bind_port}.", flush=True)

    config = uvicorn.Config("webssh.app:app", host=host, port=bind_port, reload=False)
    server = uvicorn.Server(config)
    if launch_browser:
        _install_browser_launch_hook(server, host, bind_port)
    try:
        server.run(sockets=sockets)
    finally:
        if sockets is not None:
            for sock in sockets:
                try:
                    sock.close()
                except OSError:
                    pass


def _bind_auto_port_sockets(host: str, start_port: int) -> tuple[list[socket.socket], int]:
    if start_port < 1 or start_port > 65535:
        raise ValueError("auto-port requires --port to be between 1 and 65535.")

    last_error: OSError | None = None
    for port in range(start_port, 65536):
        try:
            return [_bind_tcp_socket(host, port)], port
        except OSError as exc:
            last_error = exc
            if not _is_port_bind_retryable(exc):
                raise

    message = f"No available port found for host {host!r} from {start_port} to 65535."
    raise OSError(message) from last_error


def _bind_tcp_socket(host: str, port: int) -> socket.socket:
    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    ):
        sock = socket.socket(family, socktype, proto)
        try:
            sock.bind(sockaddr)
            sock.listen(socket.SOMAXCONN)
            sock.set_inheritable(False)
            return sock
        except OSError as exc:
            last_error = exc
            sock.close()
    if last_error is None:
        raise OSError(f"Could not resolve host {host!r}.")
    raise last_error


def _is_port_bind_retryable(exc: OSError) -> bool:
    retryable_errnos = {
        13,
        48,
        98,
        10013,
        10048,
    }
    return getattr(exc, "errno", None) in retryable_errnos


def _install_browser_launch_hook(server, host: str, port: int, opener=webbrowser.open) -> None:
    original_startup = server.startup
    launched = False

    async def startup(*args, **kwargs):
        nonlocal launched
        await original_startup(*args, **kwargs)
        if not launched and getattr(server, "started", False):
            launched = True
            try:
                opener(_browser_launch_url(server, host, port))
            except Exception as exc:
                print(f"Could not launch browser: {exc}", file=sys.stderr)

    server.startup = startup


def _browser_launch_url(server, host: str, port: int) -> str:
    candidates = _server_socket_addresses(server)
    if not candidates:
        candidates = [(host, port)]
    browser_host, browser_port = min(
        (_browser_address(address_host, address_port) for address_host, address_port in candidates),
        key=_browser_address_priority,
    )
    return f"http://{_format_url_host(browser_host)}:{browser_port}"


def _server_socket_addresses(server) -> list[tuple[str, int]]:
    addresses: list[tuple[str, int]] = []
    for uvicorn_server in getattr(server, "servers", []) or []:
        for sock in getattr(uvicorn_server, "sockets", []) or []:
            try:
                address = sock.getsockname()
            except OSError:
                continue
            if isinstance(address, tuple) and len(address) >= 2:
                addresses.append((str(address[0]), int(address[1])))
    return addresses


def _browser_address(host: str, port: int) -> tuple[str, int]:
    if host == "0.0.0.0":
        return "127.0.0.1", port
    if host == "::":
        return "::1", port
    return host, port


def _browser_address_priority(address: tuple[str, int]) -> tuple[int, str, int]:
    host, port = address
    if host == "127.0.0.1":
        return (0, host, port)
    if host in {"localhost", "::1"}:
        return (1, host, port)
    return (2, host, port)


def _format_url_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


if __name__ == "__main__":
    main()
