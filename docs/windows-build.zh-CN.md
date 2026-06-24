# Windows 单文件 exe 打包

[English](windows-build.md)

`build.py` 使用 PyInstaller 把 py-web-ssh 打包成单个 Windows 控制台可执行文件。它不会改变 Python 包行为，只负责生成可分发的 exe。

## 要求

- 在 Windows 上运行。
- 从仓库根目录运行。
- 使用一个能够导入本项目及其运行时依赖的 Python 环境。

如果当前环境缺少 PyInstaller，`build.py` 会自动安装 `pyinstaller>=6.0`，除非传入 `--no-install`。

## 基本打包

```bash
python build.py
```

默认输出路径：

```text
dist\py-web-ssh.exe
```

打包后的服务端使用普通 py-web-ssh 命令行参数启动：

```bash
dist\py-web-ssh.exe --host 0.0.0.0 --port 8022
```

## 无参数 exe 启动行为

冻结后的 Windows exe 如果无参数启动，py-web-ssh 会把它视为：

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

也就是说，它会绑定本机地址，从 `8022` 开始向上试探可用端口，并在服务启动成功后打开系统默认浏览器。

如果启动 exe 时传入任何参数，则保持和 Python 包入口相同的行为。

## 参数

```bash
python build.py --name py-web-ssh
python build.py --dist-dir dist
python build.py --work-dir build
python build.py --no-install
python build.py --no-clean
python build.py --extra-arg=--debug=all
```

可用参数：

- `--name`：不带 `.exe` 的可执行文件名。
- `--dist-dir`：生成 exe 的目录，默认是 `dist`。
- `--work-dir`：临时构建文件目录，默认是 `build`。
- `--no-install`：缺少 PyInstaller 时直接失败，不自动安装。
- `--no-clean`：不向 PyInstaller 传入 `--clean`。
- `--extra-arg`：向 PyInstaller 透传额外参数，可以重复使用。

## 包含的文件

打包脚本会把 PyInstaller 指向 `webssh/app.py`，把 `webssh/static` 作为数据文件加入，并收集 `uvicorn`、`websockets`、`httptools` 和 `paramiko` 的子模块。

生成的 exe 是控制台程序，终端日志会继续显示在控制台窗口中。
