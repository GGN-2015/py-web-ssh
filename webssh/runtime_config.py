from __future__ import annotations

import argparse
import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from . import __version__
from .files import MIN_UPLOAD_COMMAND_BYTES, REQUESTED_UPLOAD_COMMAND_BYTES
from .models import ConnectRequest

DEFAULT_TITLE = "py-web-ssh"
DEFAULT_SUBTITLE = "Web SSH Client"
BLOCK_SIZE_MIN_WARNING = (
    "Minimum upload file block size should be 64B; "
    "the input value is too small, so it is forced to 64B."
)
BLOCK_SIZE_PATTERN = re.compile(r"^\s*(\d+)\s*([A-Za-z]{0,2})\s*$")
BLOCK_SIZE_UNITS = {
    "": 1,
    "B": 1,
    "KB": 1024,
    "MB": 1024**2,
    "GB": 1024**3,
    "TB": 1024**4,
}
LAN_IP_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


@dataclass(frozen=True)
class RuntimeConfig:
    title: str = DEFAULT_TITLE
    subtitle: str = DEFAULT_SUBTITLE
    lock_host: str | None = None
    lock_username: str | None = None
    lock_password: str | None = None
    lock_private_key_path: Path | None = None
    ban_lan: bool = False
    ban_dns: bool = False
    ban_ipv6: bool = False
    ban_hosts: tuple[str, ...] = ()
    upload_block_size_bytes: int = REQUESTED_UPLOAD_COMMAND_BYTES

    @property
    def lock_password_enabled(self) -> bool:
        return self.lock_password is not None

    @property
    def lock_private_key_enabled(self) -> bool:
        return self.lock_private_key_path is not None

    def public_payload(self) -> dict[str, object]:
        return {
            "branding": {
                "title": self.title,
                "subtitle": self.subtitle,
                "version": __version__,
            },
            "locks": {
                "host": {"enabled": self.lock_host is not None, "value": self.lock_host},
                "username": {"enabled": self.lock_username is not None, "value": self.lock_username},
                "password": {"enabled": self.lock_password_enabled},
                "private_key": {"enabled": self.lock_private_key_enabled},
            },
            "security": {
                "ban_lan": self.ban_lan,
                "ban_dns": self.ban_dns,
                "ban_ipv6": self.ban_ipv6,
            },
            "upload": {
                "block_size_bytes": self.upload_block_size_bytes,
            },
        }

    def apply_to_connect_request(self, incoming: ConnectRequest) -> ConnectRequest:
        data = incoming.model_dump()

        if self.lock_host is not None:
            requested = str(data.get("host") or "").strip()
            if requested and requested != self.lock_host:
                raise HTTPException(status_code=403, detail="Host is locked by the server.")
            data["host"] = self.lock_host

        if self.lock_username is not None:
            requested = str(data.get("username") or "").strip()
            if requested and requested != self.lock_username:
                raise HTTPException(status_code=403, detail="Username is locked by the server.")
            data["username"] = self.lock_username

        target_host = str(data.get("host") or "")
        if _is_banned_host(target_host, self.ban_hosts):
            raise HTTPException(status_code=502, detail="DNS resolution failed.")

        target_address = _parse_ip_literal(target_host)
        if self.ban_dns and target_address is None:
            raise HTTPException(status_code=403, detail="DNS hostnames are blocked by the server.")

        if self.ban_ipv6 and isinstance(target_address, ipaddress.IPv6Address):
            raise HTTPException(status_code=403, detail="IPv6 targets are blocked by the server.")

        if self.ban_lan and _is_lan_ip_address(target_address):
            raise HTTPException(status_code=403, detail="LAN IP targets are blocked by the server.")

        if self.lock_password is not None:
            data["password"] = self.lock_password

        if self.lock_private_key_path is not None:
            data["private_key"] = _read_locked_private_key(self.lock_private_key_path)

        return ConnectRequest.model_validate(data)


runtime_config = RuntimeConfig()


def configure_runtime_locks(
    *,
    title: str | None = None,
    subtitle: str | None = None,
    lock_host: str | None = None,
    lock_username: str | None = None,
    lock_password: str | None = None,
    lock_private_key: str | None = None,
    ban_lan: bool = False,
    ban_dns: bool = False,
    ban_ipv6: bool = False,
    ban_hosts: list[str] | tuple[str, ...] | None = None,
    upload_block_size_bytes: int | None = None,
) -> None:
    global runtime_config
    key_path = Path(lock_private_key).expanduser().resolve() if lock_private_key else None
    if key_path is not None:
        _read_locked_private_key(key_path)
    runtime_config = RuntimeConfig(
        title=_blank_to_default(title, DEFAULT_TITLE),
        subtitle=_blank_to_default(subtitle, DEFAULT_SUBTITLE),
        lock_host=_blank_to_none(lock_host),
        lock_username=_blank_to_none(lock_username),
        lock_password=lock_password if lock_password is not None else None,
        lock_private_key_path=key_path,
        ban_lan=ban_lan,
        ban_dns=ban_dns,
        ban_ipv6=ban_ipv6,
        ban_hosts=_normalize_ban_hosts(ban_hosts),
        upload_block_size_bytes=_normalize_upload_block_size(upload_block_size_bytes),
    )


def add_runtime_lock_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--title",
        default=None,
        metavar="TITLE",
        help="Set the web UI title. Defaults to py-web-ssh.",
    )
    parser.add_argument(
        "--subtitle",
        default=None,
        metavar="SUBTITLE",
        help="Set the web UI subtitle. Defaults to Web SSH Client.",
    )
    parser.add_argument(
        "--lock-host",
        default=None,
        metavar="HOST",
        help="Only allow SSH connections to this host or domain.",
    )
    parser.add_argument(
        "--lock-username",
        default=None,
        metavar="USERNAME",
        help="Only allow SSH connections with this username.",
    )
    parser.add_argument(
        "--lock-pwd",
        default=None,
        metavar="PASSWORD",
        help="Bind this SSH password server-side. It is never sent to the browser.",
    )
    parser.add_argument(
        "--lock-private-key",
        default=None,
        metavar="KEY_FILE",
        help="Bind this server-side SSH private key file. It is never sent to the browser.",
    )
    parser.add_argument(
        "--ban-lan",
        action="store_true",
        help=(
            "Reject SSH targets entered as private/local LAN IP literals. "
            "Hostnames are not resolved for this check."
        ),
    )
    parser.add_argument(
        "--ban-dns",
        action="store_true",
        help="Reject SSH targets entered as hostnames; only IP address literals are allowed.",
    )
    parser.add_argument(
        "--ban-ipv6",
        action="store_true",
        help="Reject SSH targets entered as IPv6 address literals.",
    )
    parser.add_argument(
        "--ban-host",
        action="append",
        default=[],
        metavar="HOST_PATTERN",
        help=(
            "Reject SSH targets matching this backend-only host pattern. "
            "Repeat to add more patterns. Use * as a wildcard."
        ),
    )
    parser.add_argument(
        "--block-size",
        type=parse_block_size_argument,
        default=None,
        metavar="SIZE",
        help=(
            "Set the initial upload probe block size. "
            "Examples: 1MB, 12KB, 1024B, 2048, 1GB, 1TB."
        ),
    )


def parse_block_size_argument(value: str) -> int:
    match = BLOCK_SIZE_PATTERN.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError(
            "block size must be a non-negative integer with optional B, KB, MB, GB, or TB unit."
        )
    number_text, unit_text = match.groups()
    unit = unit_text.upper()
    multiplier = BLOCK_SIZE_UNITS.get(unit)
    if multiplier is None:
        raise argparse.ArgumentTypeError(
            "block size unit must be one of B, KB, MB, GB, or TB."
        )
    return int(number_text) * multiplier


def _read_locked_private_key(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read locked private key file {path}: {exc}") from exc


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _blank_to_default(value: str | None, default: str) -> str:
    if value is None:
        return default
    value = value.strip()
    return value or default


def _normalize_upload_block_size(value: int | None) -> int:
    if value is None:
        return REQUESTED_UPLOAD_COMMAND_BYTES
    return max(value, MIN_UPLOAD_COMMAND_BYTES)


def _is_lan_ip_literal(host: str) -> bool:
    return _is_lan_ip_address(_parse_ip_literal(host))


def _parse_ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    value = host.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _is_lan_ip_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | None,
) -> bool:
    if address is None:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _is_lan_ip_address(address.ipv4_mapped)
    return any(address in network for network in LAN_IP_NETWORKS)


def _normalize_ban_hosts(values: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    return tuple(value.strip() for value in values if value and value.strip())


def _is_banned_host(host: str, patterns: tuple[str, ...]) -> bool:
    normalized_host = _normalize_host_for_match(host)
    return any(_host_pattern_matches(normalized_host, pattern) for pattern in patterns)


def _host_pattern_matches(normalized_host: str, pattern: str) -> bool:
    normalized_pattern = _normalize_host_for_match(pattern)
    if not normalized_pattern:
        return False
    regex = "^" + ".*".join(re.escape(part) for part in normalized_pattern.split("*")) + "$"
    return re.fullmatch(regex, normalized_host) is not None


def _normalize_host_for_match(host: str) -> str:
    value = host.strip().lower()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    return value
