from __future__ import annotations

import secrets
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import Request
from fastapi.responses import Response


COOKIE_NAME = "py_web_ssh_client_session"


@dataclass
class ClientSession:
    session_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ClientSessionStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, ClientSession] = {}

    def get_or_create(self, session_id: str | None) -> tuple[ClientSession, bool]:
        with self._lock:
            if session_id and session_id in self._sessions:
                session = self._sessions[session_id]
                session.updated_at = datetime.now(timezone.utc)
                return session, False

            session = ClientSession(session_id=str(uuid.uuid4()))
            self._sessions[session.session_id] = session
            return session, True

    def get(self, session_id: str) -> ClientSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


client_sessions = ClientSessionStore()


def ensure_client_session_cookie(request: Request, response: Response) -> ClientSession:
    session, created = client_sessions.get_or_create(request.cookies.get(COOKIE_NAME))
    request.state.client_session_id = session.session_id
    if created:
        response.set_cookie(
            COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
            max_age=30 * 24 * 60 * 60,
        )
    return session
