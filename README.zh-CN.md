# py-web-ssh

[English](README.md) | 中文

一个基于 FastAPI、Paramiko 和 xterm.js 的 Python Web SSH 客户端。

## 快速开始

从 PyPI 安装：

```bash
pip install py-web-ssh
```

启动 Web SSH 服务：

```bash
py-web-ssh
```

打开 <http://127.0.0.1:8022>。

常用启动参数：

```bash
py-web-ssh --host 127.0.0.1 --auto-port --launch-browser
py-web-ssh --pin 123456
```

Windows 打包后的单文件 exe 在无参数启动时，等同于使用：

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

## 文档

- [使用指南](docs/usage.zh-CN.md)
- [SSH 算法控制](docs/algorithms.zh-CN.md)
- [API 参考](docs/api.zh-CN.md)
- [Windows 单文件 exe 打包](docs/windows-build.zh-CN.md)

