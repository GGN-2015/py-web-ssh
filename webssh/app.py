from __future__ import annotations

import asyncio
import base64
import argparse
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from . import auth
from .auth import add_pin_argument, configure_pin
from .client_session import ensure_client_session_cookie
from .files import (
    FileTransferCancelled,
    download_file_via_ssh,
    filename_for_download,
    upload_file_via_ssh,
)
from .models import ConnectRequest, CreateSessionResponse, FileTransferResponse
from .session import SessionManager
from .transfers import TransferManager


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PUBLIC_PATHS = {"/", "/api/auth/status", "/api/auth/login", "/favicon.ico"}
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8022

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
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/auth/status")
def auth_status() -> JSONResponse:
    return JSONResponse(auth.pin_auth.status_payload())


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
    session = sessions.create(config)
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
) -> FileTransferResponse:
    session = _require_session(session_id)
    tracker = transfers.get(transfer_id) if transfer_id else None
    if transfer_id and tracker is None:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    if tracker is None:
        tracker = transfers.create_upload(total_bytes or _content_length(file), remote_path)
    try:
        method, transferred = upload_file_via_ssh(
            session.config,
            file.file,
            remote_path,
            total_bytes or _content_length(file),
            cancel_event=tracker.cancel_event,
            progress=tracker.update_progress,
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
    message = f"Uploaded {transferred} bytes to {remote_path} using {method}."
    tracker.complete(transferred, message)
    session.log("info", message, None)
    return FileTransferResponse(
        ok=True,
        method=method,
        bytes_transferred=transferred,
        remote_path=remote_path,
        message=message,
        transfer_id=tracker.id,
    )


@app.post("/api/sessions/{session_id}/files/uploads")
async def create_upload_task(session_id: str, request: Request) -> JSONResponse:
    _require_session(session_id)
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
    try:
        method, stream = download_file_via_ssh(session.config, remote_path)
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="py-web-ssh")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")
    add_pin_argument(parser)
    return parser


def main() -> None:
    import uvicorn

    args = build_arg_parser().parse_args()

    configure_pin(args.pin)
    uvicorn.run("webssh.app:app", host=args.host, port=args.port, reload=False)


if __name__ == "__main__":
    main()
