from webssh.app import DEFAULT_HOST, DEFAULT_PORT, build_arg_parser
from webssh.runtime_config import DEFAULT_SUBTITLE, DEFAULT_TITLE


def test_cli_defaults_listen_on_all_interfaces_port_8022_and_default_branding() -> None:
    args = build_arg_parser().parse_args([])

    assert DEFAULT_HOST == "0.0.0.0"
    assert DEFAULT_PORT == 8022
    assert args.host == "0.0.0.0"
    assert args.port == 8022
    assert DEFAULT_TITLE == "py-web-ssh"
    assert DEFAULT_SUBTITLE == "Web SSH Client"
    assert args.title is None
    assert args.subtitle is None


def test_cli_accepts_title_and_subtitle_arguments() -> None:
    args = build_arg_parser().parse_args(["--title", "Ops SSH", "--subtitle", "Production Access"])

    assert args.title == "Ops SSH"
    assert args.subtitle == "Production Access"
