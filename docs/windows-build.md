# Windows One-File Exe Build

[中文](windows-build.zh-CN.md)

`build.py` packages py-web-ssh into a single Windows console executable with PyInstaller. It does not change the Python package behavior; it only builds a distributable exe.

## Requirements

- Run on Windows.
- Run from the repository root.
- Use a Python environment that can import this project and its runtime dependencies.

If PyInstaller is missing, `build.py` installs `pyinstaller>=6.0` into the active environment unless `--no-install` is supplied.

## Basic Build

```bash
python build.py
```

The default output is:

```text
dist\py-web-ssh.exe
```

Run the packaged server with normal py-web-ssh CLI options:

```bash
dist\py-web-ssh.exe --host 0.0.0.0 --port 8022
```

## No-Argument Exe Startup

When the frozen Windows exe is started without arguments, py-web-ssh treats it as:

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

That means it binds locally, starts trying ports from `8022`, and opens the system default browser after the server starts.

If any argument is passed to the exe, it follows the same behavior as the Python package entry point.

## Options

```bash
python build.py --name py-web-ssh
python build.py --dist-dir dist
python build.py --work-dir build
python build.py --no-install
python build.py --no-clean
python build.py --extra-arg=--debug=all
```

Available options:

- `--name`: executable name without `.exe`.
- `--dist-dir`: directory for the generated exe. Defaults to `dist`.
- `--work-dir`: directory for temporary build files. Defaults to `build`.
- `--no-install`: fail if PyInstaller is missing instead of installing it.
- `--no-clean`: do not pass `--clean` to PyInstaller.
- `--extra-arg`: pass an additional argument to PyInstaller. Repeat as needed.

## Included Files

The build script points PyInstaller at `webssh/app.py`, adds `webssh/static` as bundled data, and collects submodules from `uvicorn`, `websockets`, `httptools`, and `paramiko`.

The generated exe is a console application. Terminal logs remain visible in the console window.
