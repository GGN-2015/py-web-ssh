from __future__ import annotations

import base64
import binascii
import os
import posixpath
import shlex
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import BinaryIO, Protocol

from .models import ConnectRequest
from .ssh_client import HostKeyInfo, connect_ssh


class FileTransferError(RuntimeError):
    pass


class FileTransferCancelled(FileTransferError):
    pass


ProgressCallback = Callable[[int], None]
UPLOAD_BLOCK_SIZE = 4096


class ShellClient(Protocol):
    def exec_command(self, command: str): ...


def upload_file_via_ssh(
    config: ConnectRequest,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
    expected_host_key: HostKeyInfo,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[str, int]:
    """Upload using only bounded SSH exec commands and POSIX-ish shell commands.

    This intentionally does not use SFTP or SCP. It follows the simple-ssh-copy
    style: append base64 fragments with short remote commands, decode into a
    temporary file, and move that temp file into place after the complete upload
    succeeds.
    """

    connected = connect_ssh(
        config,
        lambda _level, _message, _details=None: None,
        expected_host_key=expected_host_key,
    )
    client = connected.client
    remote_dir = posixpath.dirname(remote_path) or "."
    token = uuid.uuid4().hex
    base64_temp_path = posixpath.join(remote_dir, f".py-web-ssh-upload-{token}.b64")
    data_temp_path = posixpath.join(remote_dir, f".py-web-ssh-upload-{token}.tmp")
    transferred = 0
    completed = False
    try:
        _run_remote_command(client, f"mkdir -p {shlex.quote(remote_dir)}")
        _run_remote_command(client, f": > {shlex.quote(base64_temp_path)}")
        transferred = _write_base64_temp_file(
            client,
            source,
            base64_temp_path,
            cancel_event=cancel_event,
            progress=progress,
        )

        if cancel_event and cancel_event.is_set():
            raise FileTransferCancelled("Upload cancelled by client.")

        _run_remote_command(client, _decode_and_move_command(base64_temp_path, data_temp_path, remote_path))
        completed = True
    except FileTransferCancelled:
        _cleanup_remote_upload(client, base64_temp_path, data_temp_path)
        _close_transport(client)
        raise
    except Exception as exc:
        _cleanup_remote_upload(client, base64_temp_path, data_temp_path)
        _close_transport(client)
        raise FileTransferError(f"SSH shell upload failed: {exc}") from exc
    finally:
        if completed:
            _cleanup_remote_upload(client, base64_temp_path, data_temp_path, raise_on_failure=False)
        client.close()

    if size is not None and transferred != size:
        raise FileTransferError(f"Uploaded {transferred} bytes, expected {size} bytes.")
    return "shell", transferred


def download_file_via_ssh(
    config: ConnectRequest,
    remote_path: str,
    expected_host_key: HostKeyInfo,
) -> tuple[str, Iterator[bytes]]:
    connected = connect_ssh(
        config,
        lambda _level, _message, _details=None: None,
        expected_host_key=expected_host_key,
    )
    client = connected.client
    command = f"base64 < {shlex.quote(remote_path)}"
    stdin, stdout, stderr = client.exec_command(f"sh -c {shlex.quote(command)}")
    stdin.close()

    def iterator() -> Iterator[bytes]:
        buffered = b""
        try:
            while True:
                chunk = stdout.channel.recv(64 * 1024)
                if not chunk:
                    break
                buffered += b"".join(chunk.split())
                keep = len(buffered) % 4
                ready = buffered[:-keep] if keep else buffered
                buffered = buffered[-keep:] if keep else b""
                if ready:
                    yield base64.b64decode(ready)
            if buffered:
                yield base64.b64decode(buffered)
            exit_code = stdout.channel.recv_exit_status()
            error_text = stderr.read().decode("utf-8", errors="replace")
            if exit_code != 0:
                raise FileTransferError(
                    f"Remote download command failed with exit code {exit_code}: {error_text}"
                )
        except binascii.Error as exc:
            raise FileTransferError(f"Remote command returned invalid base64: {exc}") from exc
        finally:
            stdout.close()
            stderr.close()
            client.close()

    return "shell", iterator()


def _write_base64_temp_file(
    client: ShellClient,
    source: BinaryIO,
    remote_base64_path: str,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    block_size: int = UPLOAD_BLOCK_SIZE,
) -> int:
    transferred = 0
    pending = b""

    while True:
        if cancel_event and cancel_event.is_set():
            raise FileTransferCancelled("Upload cancelled by client.")
        data = source.read(block_size)
        if not data:
            break

        data = pending + data
        encodable_len = len(data) - (len(data) % 3)
        if encodable_len:
            raw_chunk = data[:encodable_len]
            _append_base64_to_remote_file(client, remote_base64_path, base64.b64encode(raw_chunk), block_size)
            transferred += len(raw_chunk)
            if progress:
                progress(transferred)
        pending = data[encodable_len:]

    if pending:
        _append_base64_to_remote_file(client, remote_base64_path, base64.b64encode(pending), block_size)
        transferred += len(pending)
        if progress:
            progress(transferred)

    return transferred


def _append_base64_to_remote_file(
    client: ShellClient,
    remote_base64_path: str,
    encoded_data: bytes,
    block_size: int = UPLOAD_BLOCK_SIZE,
) -> None:
    quoted_path = shlex.quote(remote_base64_path)
    command_prefix = "printf %s "
    command_suffix = f" >> {quoted_path}"
    max_payload_len = _max_base64_payload_length(command_prefix, command_suffix, block_size)
    encoded_text = encoded_data.decode("ascii")

    for offset in range(0, len(encoded_text), max_payload_len):
        payload = encoded_text[offset : offset + max_payload_len]
        _run_bounded_remote_command(
            client,
            f"{command_prefix}{shlex.quote(payload)}{command_suffix}",
            block_size,
        )


def _max_base64_payload_length(command_prefix: str, command_suffix: str, block_size: int) -> int:
    overhead = len(command_prefix.encode("utf-8")) + len(command_suffix.encode("utf-8"))
    available = block_size - overhead
    if available < 4:
        raise ValueError("Upload block size is too small for remote command overhead.")
    return available - (available % 4)


def _decode_and_move_command(base64_temp_path: str, data_temp_path: str, remote_path: str) -> str:
    quoted_base64 = shlex.quote(base64_temp_path)
    quoted_temp = shlex.quote(data_temp_path)
    quoted_remote = shlex.quote(remote_path)
    quoted_error = shlex.quote(f"{data_temp_path}.err")
    return "\n".join(
        [
            "set -e",
            f"rm -f {quoted_temp} {quoted_error}",
            f"if command base64 -d < {quoted_base64} > {quoted_temp} 2> {quoted_error}; then",
            "  :",
            f"elif command base64 -D < {quoted_base64} > {quoted_temp} 2> {quoted_error}; then",
            "  :",
            "else",
            f"  cat {quoted_error} >&2",
            "  exit 1",
            "fi",
            f"mv -f {quoted_temp} {quoted_remote}",
            f"rm -f {quoted_base64} {quoted_error}",
        ]
    )


def _run_bounded_remote_command(client: ShellClient, command: str, block_size: int) -> tuple[bytes, bytes]:
    command_len = len(command.encode("utf-8"))
    if command_len > block_size:
        raise FileTransferError(f"Upload command exceeded block_size={block_size}: {command_len}")
    return _run_remote_command(client, command)


def _run_remote_command(client: ShellClient, command: str) -> tuple[bytes, bytes]:
    stdin = stdout = stderr = None
    try:
        stdin, stdout, stderr = client.exec_command(command)
        if stdin is not None:
            stdin.close()
        output = stdout.read()
        error = stderr.read()
        exit_code = stdout.channel.recv_exit_status()
    except Exception as exc:
        raise FileTransferError(f"{exc}; command={_short_command(command)}") from exc
    finally:
        for stream in (stdin, stdout, stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    if exit_code != 0:
        message = error.decode("utf-8", errors="replace").strip()
        output_text = output.decode("utf-8", errors="replace").strip()
        if output_text:
            message = f"{message}\n{output_text}".strip()
        raise FileTransferError(
            message or f"Remote command failed with exit code {exit_code}: {_short_command(command)}"
        )
    return output, error


def _cleanup_remote_upload(
    client: ShellClient,
    base64_temp_path: str,
    data_temp_path: str,
    raise_on_failure: bool = False,
) -> None:
    command = "rm -f " + " ".join(
        shlex.quote(path)
        for path in (
            base64_temp_path,
            data_temp_path,
            f"{data_temp_path}.err",
        )
    )
    try:
        _run_remote_command(client, command)
    except Exception:
        if raise_on_failure:
            raise


def _short_command(command: str, limit: int = 300) -> str:
    compact = " ".join(command.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _close_transport(client) -> None:
    try:
        transport = client.get_transport()
        if transport is not None:
            transport.close()
    except Exception:
        pass
    try:
        client.close()
    except Exception:
        pass


def filename_for_download(remote_path: str) -> str:
    name = posixpath.basename(remote_path.rstrip("/")) or "download.bin"
    return os.path.basename(name)
