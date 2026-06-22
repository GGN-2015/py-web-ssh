from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal


TransferState = Literal["running", "completed", "cancelled", "failed"]


@dataclass
class TransferStatus:
    transfer_id: str
    state: TransferState
    bytes_transferred: int
    total_bytes: int | None
    remote_path: str
    message: str
    created_at: datetime
    updated_at: datetime


class TransferTracker:
    def __init__(self, total_bytes: int | None, remote_path: str) -> None:
        now = datetime.now(timezone.utc)
        self.id = str(uuid.uuid4())
        self.cancel_event = threading.Event()
        self._lock = threading.RLock()
        self._status = TransferStatus(
            transfer_id=self.id,
            state="running",
            bytes_transferred=0,
            total_bytes=total_bytes,
            remote_path=remote_path,
            message="Upload started.",
            created_at=now,
            updated_at=now,
        )

    def update_progress(self, bytes_transferred: int) -> None:
        with self._lock:
            self._status.bytes_transferred = bytes_transferred
            self._status.message = "Uploading."
            self._status.updated_at = datetime.now(timezone.utc)

    def complete(self, bytes_transferred: int, message: str, remote_path: str | None = None) -> None:
        with self._lock:
            self._status.state = "completed"
            self._status.bytes_transferred = bytes_transferred
            if remote_path is not None:
                self._status.remote_path = remote_path
            self._status.message = message
            self._status.updated_at = datetime.now(timezone.utc)

    def fail(self, message: str) -> None:
        with self._lock:
            self._status.state = "failed"
            self._status.message = message
            self._status.updated_at = datetime.now(timezone.utc)

    def cancel(self) -> None:
        self.cancel_event.set()
        with self._lock:
            self._status.state = "cancelled"
            self._status.message = "Upload cancellation requested."
            self._status.updated_at = datetime.now(timezone.utc)

    def cancelled(self, message: str) -> None:
        self.cancel_event.set()
        with self._lock:
            self._status.state = "cancelled"
            self._status.message = message
            self._status.updated_at = datetime.now(timezone.utc)

    def status(self) -> TransferStatus:
        with self._lock:
            return TransferStatus(**self._status.__dict__)


class TransferManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._transfers: dict[str, TransferTracker] = {}

    def create_upload(self, total_bytes: int | None, remote_path: str) -> TransferTracker:
        tracker = TransferTracker(total_bytes=total_bytes, remote_path=remote_path)
        with self._lock:
            self._transfers[tracker.id] = tracker
        return tracker

    def get(self, transfer_id: str) -> TransferTracker | None:
        with self._lock:
            return self._transfers.get(transfer_id)

    def cancel(self, transfer_id: str) -> bool:
        tracker = self.get(transfer_id)
        if tracker is None:
            return False
        tracker.cancel()
        return True
