from webssh.app import DEFAULT_HOST, DEFAULT_PORT, build_arg_parser


def test_cli_defaults_listen_on_all_interfaces_port_8022() -> None:
    args = build_arg_parser().parse_args([])

    assert DEFAULT_HOST == "0.0.0.0"
    assert DEFAULT_PORT == 8022
    assert args.host == "0.0.0.0"
    assert args.port == 8022
