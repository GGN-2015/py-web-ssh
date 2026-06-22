from io import BytesIO

from paramiko.ssh_exception import SSHException

from webssh.files import (
    FileTransferError,
    REQUESTED_UPLOAD_COMMAND_BYTES,
    _decode_and_move_command,
    _is_upload_probe_size_failure,
    _max_base64_payload_length,
    _probe_upload_command_size,
    _resolve_upload_target,
    _write_base64_temp_file,
)


class FakeChannel:
    def recv_exit_status(self) -> int:
        return 0


class FakeStream:
    def __init__(self, data: bytes = b"") -> None:
        self.channel = FakeChannel()
        self._data = data

    def read(self) -> bytes:
        return self._data

    def close(self) -> None:
        return None


class FakeClient:
    def __init__(self, status: str = "missing") -> None:
        self.commands: list[str] = []
        self.status = status

    def exec_command(self, command: str):
        self.commands.append(command)
        if "[ -d " in command:
            return FakeStream(), FakeStream(self.status.encode()), FakeStream()
        return FakeStream(), FakeStream(), FakeStream()


def test_upload_writes_base64_fragments_without_midstream_padding() -> None:
    client = FakeClient()
    progress: list[int] = []

    transferred = _write_base64_temp_file(
        client,
        BytesIO(b"hello world!"),
        "/tmp/file.b64",
        progress=progress.append,
        block_size=32,
    )

    payloads = [command.split(" ", 2)[2].split(" >> ", 1)[0].strip("'") for command in client.commands]

    assert transferred == 12
    assert "".join(payloads) == "aGVsbG8gd29ybGQh"
    assert all("=" not in payload for payload in payloads[:-1])
    assert progress[-1] == 12


def test_decode_command_decodes_temp_file_then_moves_into_place() -> None:
    command = _decode_and_move_command("/tmp/file.b64", "/tmp/file.tmp", "/tmp/final.txt")

    assert "base64 -d" in command
    assert "base64 -D" in command
    assert "mv -f" in command
    assert "/tmp/file.b64" in command
    assert "/tmp/file.tmp" in command
    assert "/tmp/final.txt" in command


def test_base64_payload_length_respects_command_boundary() -> None:
    size = _max_base64_payload_length("printf %s ", " >> /tmp/file.b64", 64)

    assert size % 4 == 0
    assert len("printf %s ".encode()) + size + len(" >> /tmp/file.b64".encode()) <= 64


def test_upload_target_directory_uses_original_filename() -> None:
    target = _resolve_upload_target(
        FakeClient(status="directory"),
        "/tmp/uploads",
        r"C:\Users\me\example.txt",
        512,
    )

    assert target.final_path == "/tmp/uploads/example.txt"
    assert target.remote_dir == "/tmp/uploads"


def test_upload_target_missing_or_file_uses_requested_path() -> None:
    missing = _resolve_upload_target(FakeClient(status="missing"), "/tmp/final.txt", "source.txt", 512)
    existing_file = _resolve_upload_target(FakeClient(status="file"), "/tmp/final.txt", "source.txt", 512)

    assert missing.final_path == "/tmp/final.txt"
    assert existing_file.final_path == "/tmp/final.txt"


def test_upload_command_probe_binary_searches_after_large_command_failure() -> None:
    attempts: list[int] = []

    def probe(size: int) -> None:
        attempts.append(size)
        if size > 300:
            raise RuntimeError("Argument list too long")

    selected = _probe_upload_command_size(probe, requested_size=1024, minimum_size=64)

    assert selected == 300
    assert attempts[0] == 1024
    assert 300 in attempts


def test_upload_command_probe_default_starts_at_one_mib() -> None:
    assert REQUESTED_UPLOAD_COMMAND_BYTES == 1024 * 1024


def test_upload_command_probe_accepts_connection_reset_failures() -> None:
    attempts: list[int] = []

    def probe(size: int) -> None:
        attempts.append(size)
        if size > 128:
            raise SSHException("Channel closed")

    selected = _probe_upload_command_size(probe, requested_size=512, minimum_size=64)

    assert selected == 128
    assert attempts[0] == 512


def test_upload_command_probe_rejects_when_even_minimum_fails() -> None:
    def probe(_size: int) -> None:
        raise EOFError("connection closed")

    try:
        _probe_upload_command_size(probe, requested_size=128, minimum_size=64)
    except FileTransferError as exc:
        assert "smaller than 64 bytes" in str(exc)
    else:
        raise AssertionError("Expected FileTransferError")


def test_upload_probe_failure_classifier_matches_simple_ssh_copy_cases() -> None:
    assert _is_upload_probe_size_failure(RuntimeError("Argument list too long"))
    assert _is_upload_probe_size_failure(EOFError("closed"))
    assert _is_upload_probe_size_failure(SSHException("Channel closed"))
    assert _is_upload_probe_size_failure(RuntimeError("Socket is closed"))


def test_file_transfer_module_does_not_use_sftp_or_scp() -> None:
    import webssh.files as files

    source = files.__loader__.get_source(files.__name__)

    assert ".open_sftp(" not in source
    assert "SFTPClient" not in source
    assert "SCPClient" not in source
