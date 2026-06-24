from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENTRYPOINT = ROOT / "webssh" / "app.py"
STATIC_DIR = ROOT / "webssh" / "static"
DEFAULT_NAME = "py-web-ssh"
PYINSTALLER_REQUIREMENT = "pyinstaller>=6.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build py-web-ssh as a Windows one-file executable with PyInstaller.",
    )
    parser.add_argument("--name", default=DEFAULT_NAME, help="Executable name without .exe.")
    parser.add_argument("--dist-dir", default="dist", help="Directory for the generated exe.")
    parser.add_argument("--work-dir", default="build", help="Directory for temporary build files.")
    parser.add_argument(
        "--no-install",
        action="store_true",
        help="Fail instead of installing PyInstaller when it is missing.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not pass --clean to PyInstaller.",
    )
    parser.add_argument(
        "--extra-arg",
        action="append",
        default=[],
        help="Extra argument passed through to PyInstaller. Repeat as needed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    require_windows()
    require_project_files()
    ensure_pyinstaller(auto_install=not args.no_install)

    dist_dir = (ROOT / args.dist_dir).resolve()
    work_dir = (ROOT / args.work_dir).resolve()
    pyinstaller_work_dir = work_dir / "pyinstaller"
    entry_script = pyinstaller_work_dir / "py_web_ssh_entry.py"
    pyinstaller_work_dir.mkdir(parents=True, exist_ok=True)
    write_entry_script(entry_script)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--console",
        "--name",
        args.name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(pyinstaller_work_dir),
        "--specpath",
        str(pyinstaller_work_dir),
        "--paths",
        str(ROOT),
        "--add-data",
        f"{STATIC_DIR}{os.pathsep}webssh/static",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "websockets",
        "--collect-submodules",
        "httptools",
        "--collect-submodules",
        "paramiko",
    ]
    if not args.no_clean:
        command.append("--clean")
    command.extend(args.extra_arg)
    command.append(str(entry_script))

    print("Building one-file executable with PyInstaller...")
    run(command)

    exe_path = dist_dir / f"{args.name}.exe"
    if not exe_path.exists():
        raise SystemExit(f"Build finished, but {exe_path} was not created.")

    print(f"Built {exe_path}")
    print(f"Try it with: {exe_path} --host 0.0.0.0 --port 8022")
    return 0


def require_windows() -> None:
    if os.name != "nt":
        raise SystemExit("This build script is intended for Windows exe builds. Run it on Windows.")


def require_project_files() -> None:
    missing = [path for path in (ENTRYPOINT, STATIC_DIR) if not path.exists()]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise SystemExit(f"Required project files are missing: {joined}")


def ensure_pyinstaller(auto_install: bool) -> None:
    if module_available("PyInstaller"):
        return
    if not auto_install:
        raise SystemExit(
            "PyInstaller is not installed. Install it with "
            f"`{sys.executable} -m pip install {PYINSTALLER_REQUIREMENT}`."
        )
    print(f"PyInstaller is missing; installing {PYINSTALLER_REQUIREMENT}...")
    run([sys.executable, "-m", "pip", "install", PYINSTALLER_REQUIREMENT])
    if not module_available("PyInstaller"):
        raise SystemExit("PyInstaller installation completed, but the module is still unavailable.")


def module_available(module_name: str) -> bool:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def write_entry_script(path: Path) -> None:
    path.write_text(
        "from webssh.app import main\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )


def run(command: list[str]) -> None:
    printable = " ".join(shlex_quote(part) for part in command)
    print(f"> {printable}")
    subprocess.run(command, cwd=ROOT, check=True)


def shlex_quote(value: str) -> str:
    if not value or any(char.isspace() for char in value):
        return '"' + value.replace('"', '\\"') + '"'
    return value


if __name__ == "__main__":
    raise SystemExit(main())
