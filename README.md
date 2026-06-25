# py-web-ssh

English | [中文](README.zh-CN.md)

A Python web SSH client built with FastAPI, Paramiko, and xterm.js.

## Screenshots

![py-web-ssh interface overview](https://raw.githubusercontent.com/GGN-2015/py-web-ssh/main/docs/assets/screenshots/interface-overview.png)

## Quick Start

Install from PyPI:

```bash
pip install py-web-ssh
```

Start the web SSH server:

```bash
py-web-ssh
```

Open <http://127.0.0.1:8022>.

Common startup options:

```bash
py-web-ssh --host 127.0.0.1 --auto-port --launch-browser
py-web-ssh --block-size 12KB
py-web-ssh --pin 123456
```

On Windows, the packaged one-file exe starts without arguments as if it was run with:

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

## Documentation

- [Usage Guide](docs/usage.md)
- [SSH Algorithm Controls](docs/algorithms.md)
- [API Reference](docs/api.md)
- [Windows One-File Exe Build](docs/windows-build.md)
