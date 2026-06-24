from __future__ import annotations

import base64
import binascii
import os
import posixpath
import shlex
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from paramiko.ssh_exception import SSHException

from .models import ConnectRequest
from .ssh_client import HostKeyInfo, connect_ssh


class FileTransferError(RuntimeError):
    pass


class FileTransferCancelled(FileTransferError):
    pass


ProgressCallback = Callable[[int], None]
TransferLogCallback = Callable[[str, str, str | None], None]
REQUESTED_UPLOAD_COMMAND_BYTES = 1024 * 1024
MIN_UPLOAD_COMMAND_BYTES = 64
UPLOAD_BLOCK_SIZE = REQUESTED_UPLOAD_COMMAND_BYTES


@dataclass(frozen=True)
class UploadTarget:
    requested_path: str
    final_path: str
    remote_dir: str


class ShellClient(Protocol):
    def exec_command(self, command: str): ...


def upload_file_via_ssh(
    config: ConnectRequest,
    source: BinaryIO,
    remote_path: str,
    size: int | None,
    expected_host_key: HostKeyInfo,
    requested_command_size: int = REQUESTED_UPLOAD_COMMAND_BYTES,
    original_filename: str | None = None,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
    log: TransferLogCallback | None = None,
) -> tuple[str, int, str]:
    """Upload using only bounded SSH exec commands and POSIX-ish shell commands.

    This intentionally does not use SFTP or SCP. It follows the simple-ssh-copy
    style: append base64 fragments with short remote commands, decode into a
    temporary file, and move that temp file into place after the complete upload
    succeeds.
    """

    command_size = probe_upload_command_size(
        config,
        expected_host_key,
        log,
        requested_size=requested_command_size,
    )
    connected = _connect_transfer_client(config, expected_host_key)
    client = connected.client
    transferred = 0
    completed = False
    target = UploadTarget(remote_path, remote_path, posixpath.dirname(remote_path) or ".")
    base64_temp_path = data_temp_path = ""
    try:
        target = _resolve_upload_target(client, remote_path, original_filename, command_size)
        if log:
            log(
                "info",
                "Resolved remote upload target.",
                f"requested={target.requested_path}\nfinal={target.final_path}",
            )

        token = uuid.uuid4().hex
        base64_temp_path = posixpath.join(target.remote_dir, f".py-web-ssh-upload-{token}.b64")
        data_temp_path = posixpath.join(target.remote_dir, f".py-web-ssh-upload-{token}.tmp")

        _run_bounded_remote_command(client, f"mkdir -p {shlex.quote(target.remote_dir)}", command_size)
        _run_bounded_remote_command(client, f": > {shlex.quote(base64_temp_path)}", command_size)
        transferred = _write_base64_temp_file(
            client,
            source,
            base64_temp_path,
            cancel_event=cancel_event,
            progress=progress,
            block_size=command_size,
        )

        if cancel_event and cancel_event.is_set():
            raise FileTransferCancelled("Upload cancelled by client.")

        _run_bounded_remote_command(
            client,
            _decode_and_move_command(base64_temp_path, data_temp_path, target.final_path),
            command_size,
        )
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
    return "shell", transferred, target.final_path


def _connect_transfer_client(config: ConnectRequest, expected_host_key: HostKeyInfo):
    return connect_ssh(
        config,
        lambda _level, _message, _details=None: None,
        expected_host_key=expected_host_key,
    )


def probe_upload_command_size(
    config: ConnectRequest,
    expected_host_key: HostKeyInfo,
    log: TransferLogCallback | None = None,
    requested_size: int = REQUESTED_UPLOAD_COMMAND_BYTES,
    minimum_size: int = MIN_UPLOAD_COMMAND_BYTES,
) -> int:
    def probe(candidate_size: int) -> None:
        connected = _connect_transfer_client(config, expected_host_key)
        client = connected.client
        try:
            _run_bounded_remote_command(
                client,
                _make_block_size_probe_command(candidate_size),
                candidate_size,
            )
        finally:
            _close_transport(client)

    return _probe_upload_command_size(
        probe,
        requested_size=requested_size,
        minimum_size=minimum_size,
        log=log,
    )


def _probe_upload_command_size(
    probe: Callable[[int], None],
    requested_size: int = REQUESTED_UPLOAD_COMMAND_BYTES,
    minimum_size: int = MIN_UPLOAD_COMMAND_BYTES,
    log: TransferLogCallback | None = None,
) -> int:
    requested_size = max(1, requested_size)
    minimum_size = max(1, minimum_size)
    if log:
        log(
            "info",
            "Probing SSH upload command size.",
            f"requested={requested_size}\nminimum={minimum_size}",
        )

    try:
        probe(requested_size)
        selected = requested_size
    except Exception as exc:
        if not _is_upload_probe_size_failure(exc):
            raise
        _log_probe_failure(log, requested_size, exc)
        low = minimum_size
        high = requested_size - 1
        selected = 0
        while low <= high:
            candidate = (low + high) // 2
            try:
                probe(candidate)
            except Exception as candidate_exc:
                if not _is_upload_probe_size_failure(candidate_exc):
                    raise
                _log_probe_failure(log, candidate, candidate_exc)
                high = candidate - 1
            else:
                selected = candidate
                low = candidate + 1

        if selected < minimum_size:
            raise FileTransferError(
                f"SSH connection cannot carry upload commands smaller than {minimum_size} bytes"
            ) from exc

    if log:
        log(
            "info",
            f"SSH upload command-size probe selected {selected} bytes.",
            f"requested={requested_size}\nminimum={minimum_size}\nselected={selected}",
        )
    return selected


def _log_probe_failure(
    log: TransferLogCallback | None,
    candidate_size: int,
    exc: BaseException,
) -> None:
    if log:
        log(
            "debug",
            f"SSH upload command-size probe failed at {candidate_size} bytes.",
            str(exc),
        )


def _make_block_size_probe_command(block_size: int) -> str:
    prefix = "true # "
    filler_len = block_size - len(prefix.encode("utf-8"))
    if filler_len < 0:
        raise ValueError("Upload command size is too small for probe overhead.")
    return prefix + ("x" * filler_len)


def _is_upload_probe_size_failure(exc: BaseException) -> bool:
    return _is_connection_reset_error(exc) or _is_upload_command_too_large_error(exc)


def _is_connection_reset_error(exc: BaseException) -> bool:
    if isinstance(exc, (EOFError, ConnectionResetError)):
        return True
    if isinstance(exc, SSHException) and str(exc).lower().rstrip(".") == "channel closed":
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (10054, 104):
        return True

    message = str(exc).lower()
    if any(
        text in message
        for text in (
            "socket is closed",
            "channel closed",
            "connection reset",
            "connection aborted",
            "broken pipe",
            "eof",
            "timed out",
        )
    ):
        return True

    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, BaseException) and _is_connection_reset_error(cause):
        return True
    context = getattr(exc, "__context__", None)
    if isinstance(context, BaseException) and _is_connection_reset_error(context):
        return True
    return any(
        _is_connection_reset_error(arg)
        for arg in getattr(exc, "args", ())
        if isinstance(arg, BaseException)
    )


def _is_upload_command_too_large_error(exc: BaseException) -> bool:
    return "argument list too long" in str(exc).lower()


def _resolve_upload_target(
    client: ShellClient,
    remote_path: str,
    original_filename: str | None,
    block_size: int,
) -> UploadTarget:
    status = _remote_path_status(client, remote_path, block_size)
    if status == "directory":
        remote_dir = remote_path.rstrip("/") or "/"
        final_path = posixpath.join(remote_dir, _safe_upload_filename(original_filename))
        return UploadTarget(requested_path=remote_path, final_path=final_path, remote_dir=remote_dir)

    final_path = _final_file_path(remote_path)
    remote_dir = posixpath.dirname(final_path) or "."
    return UploadTarget(requested_path=remote_path, final_path=final_path, remote_dir=remote_dir)


def _remote_path_status(client: ShellClient, remote_path: str, block_size: int) -> str:
    quoted_path = shlex.quote(remote_path)
    command = (
        f"if [ -d {quoted_path} ]; then printf %s directory; "
        f"elif [ -e {quoted_path} ]; then printf %s file; "
        "else printf %s missing; fi"
    )
    output, _ = _run_bounded_remote_command(client, command, block_size)
    status = output.decode("utf-8", errors="replace").strip()
    if status not in {"directory", "file", "missing"}:
        raise FileTransferError(f"Could not determine remote target type: {status!r}")
    return status


def _safe_upload_filename(original_filename: str | None) -> str:
    normalized = (original_filename or "").replace("\\", "/").strip()
    return posixpath.basename(normalized) or "upload.bin"


def _final_file_path(remote_path: str) -> str:
    stripped = remote_path.rstrip("/")
    return stripped or remote_path


def download_file_via_ssh(
    config: ConnectRequest,
    remote_path: str,
    expected_host_key: HostKeyInfo,
    cancel_event: threading.Event | None = None,
    progress: ProgressCallback | None = None,
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
        transferred = 0
        try:
            while True:
                if cancel_event and cancel_event.is_set():
                    raise FileTransferCancelled("Download cancelled by client.")
                chunk = stdout.channel.recv(64 * 1024)
                if not chunk:
                    break
                buffered += b"".join(chunk.split())
                keep = len(buffered) % 4
                ready = buffered[:-keep] if keep else buffered
                buffered = buffered[-keep:] if keep else b""
                if ready:
                    decoded = base64.b64decode(ready)
                    transferred += len(decoded)
                    if progress:
                        progress(transferred)
                    yield decoded
            if buffered:
                decoded = base64.b64decode(buffered)
                transferred += len(decoded)
                if progress:
                    progress(transferred)
                yield decoded
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


def remote_file_size_via_ssh(
    config: ConnectRequest,
    remote_path: str,
    expected_host_key: HostKeyInfo,
) -> int | None:
    connected = _connect_transfer_client(config, expected_host_key)
    client = connected.client
    try:
        output, _ = _run_remote_command(
            client,
            f"if [ -f {shlex.quote(remote_path)} ]; then wc -c < {shlex.quote(remote_path)}; else exit 2; fi",
        )
    finally:
        client.close()
    text = output.decode("utf-8", errors="replace").strip()
    try:
        return int(text)
    except ValueError:
        return None


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
    paths = [path for path in (base64_temp_path, data_temp_path, f"{data_temp_path}.err") if path]
    if not paths:
        return
    command = "rm -f " + " ".join(
        shlex.quote(path)
        for path in paths
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
