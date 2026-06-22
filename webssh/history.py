from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class OutputChunk:
    seq: int
    data: bytes

    @property
    def end_seq(self) -> int:
        return self.seq + len(self.data)


class OutputHistory:
    """Bounded byte history for terminal replay.

    The sequence number is an absolute byte offset in the SSH output stream.
    Keeping absolute offsets lets a reconnecting browser resume from the last
    xterm snapshot even when old chunks have been trimmed.
    """

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(1, max_bytes)
        self._chunks: deque[OutputChunk] = deque()
        self._bytes = 0
        self._next_seq = 0

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @property
    def earliest_seq(self) -> int:
        if not self._chunks:
            return self._next_seq
        return self._chunks[0].seq

    def append(self, data: bytes) -> OutputChunk:
        chunk = OutputChunk(seq=self._next_seq, data=data)
        self._chunks.append(chunk)
        self._next_seq = chunk.end_seq
        self._bytes += len(data)
        self._trim()
        return chunk

    def since(self, seq: int | None = None) -> list[OutputChunk]:
        if seq is None:
            return list(self._chunks)
        chunks: list[OutputChunk] = []
        for chunk in self._chunks:
            if chunk.end_seq <= seq:
                continue
            if chunk.seq < seq:
                offset = seq - chunk.seq
                chunks.append(OutputChunk(seq=seq, data=chunk.data[offset:]))
            else:
                chunks.append(chunk)
        return chunks

    def _trim(self) -> None:
        while self._bytes > self.max_bytes and self._chunks:
            dropped = self._chunks.popleft()
            self._bytes -= len(dropped.data)
