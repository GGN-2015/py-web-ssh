from io import BytesIO

from webssh.files import (
    _decode_and_move_command,
    _max_base64_payload_length,
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
    def __init__(self) -> None:
        self.commands: list[str] = []

    def exec_command(self, command: str):
        self.commands.append(command)
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


def test_file_transfer_module_does_not_use_sftp_or_scp() -> None:
    import webssh.files as files

    source = files.__loader__.get_source(files.__name__)

    assert ".open_sftp(" not in source
    assert "SFTPClient" not in source
    assert "SCPClient" not in source
