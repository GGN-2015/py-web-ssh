from __future__ import annotations

import base64
import binascii
import os
import posixpath
import shlex
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import BinaryIO

from .models import ConnectRequest
from .ssh_client import HostKeyInfo, connect_ssh


class FileTransferError(RuntimeError):
    pass


class FileTransferCancelled(FileTransferError):
    pass


ProgressCallback = Callable[[int], None]


def upload_file_via_ssh(
    config: ConnectRequest,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
    expected_host_key: HostKeyInfo,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[str, int]:
    """Upload using only an SSH exec channel and POSIX-ish shell commands.

    This intentionally does not use SFTP or SCP. It follows the simple-ssh-copy
    style: stream base64 into a remote shell, decode into a temporary file, and
    atomically move the temp file into place after the complete upload succeeds.
    """

    connected = connect_ssh(
        config,
        lambda _level, _message, _details=None: None,
        expected_host_key=expected_host_key,
    )
    client = connected.client
    remote_dir = posixpath.dirname(remote_path) or "."
    temp_path = posixpath.join(remote_dir, f".py-web-ssh-upload-{uuid.uuid4().hex}.tmp")
    command = _upload_command(remote_dir, temp_path, remote_path)
    stdin = stdout = stderr = None
    transferred = 0
    try:
        stdin, stdout, stderr = client.exec_command(f"sh -c {shlex.quote(command)}")
        while True:
            if cancel_event and cancel_event.is_set():
                raise FileTransferCancelled("Upload cancelled by client.")
            chunk = source.read(48 * 1024)
            if not chunk:
                break
            transferred += len(chunk)
            stdin.write(base64.b64encode(chunk).decode("ascii"))
            stdin.write("\n")
            stdin.flush()
            if progress:
                progress(transferred)

        if cancel_event and cancel_event.is_set():
            raise FileTransferCancelled("Upload cancelled by client.")

        stdin.channel.shutdown_write()
        exit_code = stdout.channel.recv_exit_status()
        error_text = stderr.read().decode("utf-8", errors="replace")
    except FileTransferCancelled:
        _close_transport(client)
        raise
    except Exception as exc:
        _close_transport(client)
        raise FileTransferError(f"SSH shell upload failed: {exc}") from exc
    finally:
        for stream in (stdin, stdout, stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        client.close()

    if exit_code != 0:
        raise FileTransferError(f"Remote upload command failed with exit code {exit_code}: {error_text}")
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


def _upload_command(remote_dir: str, temp_path: str, remote_path: str) -> str:
    quoted_temp = shlex.quote(temp_path)
    return "\n".join(
        [
            "set -e",
            f"mkdir -p -- {shlex.quote(remote_dir)}",
            f"tmp={quoted_temp}",
            "cleanup() { rm -f -- \"$tmp\"; }",
            "trap cleanup EXIT HUP INT TERM",
            f"if printf '' | base64 -d >/dev/null 2>&1; then base64 -d > {quoted_temp}; "
            f"else base64 -D > {quoted_temp}; fi",
            f"mv -- {quoted_temp} {shlex.quote(remote_path)}",
            "trap - EXIT",
        ]
    )


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
