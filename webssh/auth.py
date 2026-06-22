from __future__ import annotations

import argparse
import hashlib
import hmac
import secrets
from dataclasses import dataclass

from fastapi import HTTPException, Request, Response, WebSocket


COOKIE_NAME = "py_web_ssh_pin"


@dataclass
class PinAuth:
    pin_hash: str | None = None
    secret: str = ""

    @classmethod
    def disabled(cls) -> "PinAuth":
        return cls(pin_hash=None, secret=secrets.token_hex(32))

    @classmethod
    def from_pin(cls, pin: str | None) -> "PinAuth":
        if not pin:
            return cls.disabled()
        return cls(pin_hash=_hash_pin(pin), secret=secrets.token_hex(32))

    @property
    def enabled(self) -> bool:
        return self.pin_hash is not None

    def status_payload(self) -> dict[str, bool]:
        return {"enabled": self.enabled}

    def verify_pin(self, pin: str) -> bool:
        if not self.enabled:
            return True
        return hmac.compare_digest(_hash_pin(pin), self.pin_hash or "")

    def set_cookie(self, response: Response, pin: str) -> None:
        if not self.enabled:
            return
        salt = secrets.token_hex(16)
        digest = _hash_with_salt(pin, salt)
        signature = self._signature(salt, digest)
        response.set_cookie(
            COOKIE_NAME,
            f"{salt}:{digest}:{signature}",
            httponly=True,
            samesite="lax",
            secure=False,
            path="/",
            max_age=7 * 24 * 60 * 60,
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    def is_request_authorized(self, request: Request) -> bool:
        if not self.enabled:
            return True
        return self._valid_cookie(request.cookies.get(COOKIE_NAME))

    def is_websocket_authorized(self, websocket: WebSocket) -> bool:
        if not self.enabled:
            return True
        return self._valid_cookie(websocket.cookies.get(COOKIE_NAME))

    def require_request(self, request: Request) -> None:
        if not self.is_request_authorized(request):
            raise HTTPException(status_code=401, detail="PIN authentication required.")

    def _valid_cookie(self, value: str | None) -> bool:
        if not value:
            return False
        try:
            salt, digest, signature = value.split(":", 2)
        except ValueError:
            return False
        if not hmac.compare_digest(signature, self._signature(salt, digest)):
            return False
        for candidate_pin_hash in [self.pin_hash]:
            if candidate_pin_hash and hmac.compare_digest(digest, _rehash_pin_hash(candidate_pin_hash, salt)):
                return True
        return False

    def _signature(self, salt: str, digest: str) -> str:
        return hmac.new(
            self.secret.encode("utf-8"),
            f"{salt}:{digest}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


pin_auth = PinAuth.disabled()


def configure_pin(pin: str | None) -> None:
    global pin_auth
    pin_auth = PinAuth.from_pin(pin)


def add_pin_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pin",
        default=None,
        help="Require this PIN before the web client can access SSH APIs.",
    )


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def _hash_with_salt(pin: str, salt: str) -> str:
    return _rehash_pin_hash(_hash_pin(pin), salt)


def _rehash_pin_hash(pin_hash: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{pin_hash}".encode("utf-8")).hexdigest()
