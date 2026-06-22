from __future__ import annotations

import base64
import binascii
import os
import posixpath
import shlex
import uuid
from collections.abc import Iterator
from typing import BinaryIO

import paramiko


class FileTransferError(RuntimeError):
    pass


def upload_file(
    client: paramiko.SSHClient,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
) -> tuple[str, int]:
    try:
        return _upload_sftp(client, source, remote_path, size)
    except Exception as sftp_exc:
        source.seek(0)
        try:
            return _upload_shell(client, source, remote_path, size)
        except Exception as shell_exc:
            raise FileTransferError(
                f"SFTP upload failed: {sftp_exc}\nShell fallback upload failed: {shell_exc}"
            ) from shell_exc


def download_file(client: paramiko.SSHClient, remote_path: str) -> tuple[str, Iterator[bytes]]:
    try:
        return "sftp", _download_sftp(client, remote_path)
    except Exception as sftp_exc:
        try:
            return "shell", _download_shell(client, remote_path)
        except Exception as shell_exc:
            raise FileTransferError(
                f"SFTP download failed: {sftp_exc}\nShell fallback download failed: {shell_exc}"
            ) from shell_exc


def _upload_sftp(
    client: paramiko.SSHClient,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
) -> tuple[str, int]:
    transferred = 0

    def callback(sent: int, _total: int) -> None:
        nonlocal transferred
        transferred = max(transferred, sent)

    with client.open_sftp() as sftp:
        parent = posixpath.dirname(remote_path)
        if parent and parent != ".":
            _sftp_mkdirs(sftp, parent)
        sftp.putfo(source, remote_path, file_size=size or 0, callback=callback)

    if transferred == 0 and size is not None:
        transferred = size
    elif transferred == 0:
        transferred = _remote_size(client, remote_path)
    return "sftp", transferred


def _sftp_mkdirs(sftp: paramiko.SFTPClient, path: str) -> None:
    if path in ("", "/"):
        return
    parts = [part for part in path.split("/") if part]
    current = "/" if path.startswith("/") else ""
    for part in parts:
        current = posixpath.join(current, part) if current else part
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def _upload_shell(
    client: paramiko.SSHClient,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
) -> tuple[str, int]:
    remote_dir = posixpath.dirname(remote_path) or "."
    temp_path = posixpath.join(remote_dir, f".py-web-ssh-upload-{uuid.uuid4().hex}.tmp")
    command = (
        "set -e; "
        f"mkdir -p -- {shlex.quote(remote_dir)}; "
        f"({_base64_decode_command()}) > {shlex.quote(temp_path)}; "
        f"mv -- {shlex.quote(temp_path)} {shlex.quote(remote_path)}"
    )
    stdin, stdout, stderr = client.exec_command(f"sh -c {shlex.quote(command)}")
    transferred = 0
    try:
        while True:
            chunk = source.read(48 * 1024)
            if not chunk:
                break
            transferred += len(chunk)
            stdin.write(base64.b64encode(chunk).decode("ascii"))
            stdin.write("\n")
        stdin.channel.shutdown_write()
        exit_code = stdout.channel.recv_exit_status()
        error_text = stderr.read().decode("utf-8", errors="replace")
    finally:
        stdin.close()
        stdout.close()
        stderr.close()
    if exit_code != 0:
        raise FileTransferError(f"Remote upload command failed with exit code {exit_code}: {error_text}")
    if size is not None and transferred != size:
        raise FileTransferError(f"Uploaded {transferred} bytes, expected {size} bytes.")
    return "shell", transferred


def _download_sftp(client: paramiko.SSHClient, remote_path: str) -> Iterator[bytes]:
    sftp = client.open_sftp()
    remote_file = sftp.open(remote_path, "rb")

    def iterator() -> Iterator[bytes]:
        try:
            while True:
                chunk = remote_file.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            remote_file.close()
            sftp.close()

    return iterator()


def _download_shell(client: paramiko.SSHClient, remote_path: str) -> Iterator[bytes]:
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

    return iterator()


def _base64_decode_command() -> str:
    return "base64 -d 2>/dev/null || base64 -D"


def _remote_size(client: paramiko.SSHClient, remote_path: str) -> int:
    with client.open_sftp() as sftp:
        return int(sftp.stat(remote_path).st_size or 0)


def filename_for_download(remote_path: str) -> str:
    name = posixpath.basename(remote_path.rstrip("/")) or "download.bin"
    return os.path.basename(name)
