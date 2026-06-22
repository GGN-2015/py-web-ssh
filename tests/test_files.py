from webssh.files import _upload_command


def test_upload_command_writes_temp_file_then_moves_into_place() -> None:
    command = _upload_command("/tmp/target dir", "/tmp/target dir/.upload.tmp", "/tmp/target dir/final.txt")

    assert "base64 -d" in command
    assert "base64 -D" in command
    assert "trap cleanup EXIT HUP INT TERM" in command
    assert "mv --" in command
    assert ".upload.tmp" in command
    assert "final.txt" in command


def test_file_transfer_module_does_not_use_sftp_or_scp() -> None:
    import webssh.files as files

    source = files.__loader__.get_source(files.__name__)

    assert ".open_sftp(" not in source
    assert "SFTPClient" not in source
    assert "SCPClient" not in source
