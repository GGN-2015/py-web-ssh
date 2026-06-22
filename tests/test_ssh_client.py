import paramiko

from webssh.ssh_client import HostKeyInfo


def test_ssh_client_does_not_use_agent_or_known_hosts() -> None:
    import webssh.ssh_client as ssh_client

    source = ssh_client.__loader__.get_source(ssh_client.__name__)

    assert "paramiko.Agent" not in source
    assert "known_hosts" not in source
    assert "HostKeys" not in source


def test_host_key_info_formats_fingerprints() -> None:
    key = paramiko.RSAKey.generate(1024)

    info = HostKeyInfo.from_key(key)

    assert info.key_type == "ssh-rsa"
    assert info.sha256_fingerprint.startswith("SHA256:")
    assert info.md5_fingerprint.startswith("MD5:")
    assert info.matches(key)
