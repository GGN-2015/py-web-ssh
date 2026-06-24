# 使用指南

[English](usage.md)

py-web-ssh 会启动一个 FastAPI 服务，并提供基于 xterm.js 的 SSH 终端。默认界面语言是英文，网页可以在英文和中文之间切换。

## 安装

安装已发布的包：

```bash
pip install py-web-ssh
```

如果要从仓库根目录进行可编辑开发安装：

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## 启动服务

```bash
py-web-ssh
```

默认监听地址是 `0.0.0.0:8022`。在同一台机器上打开 <http://127.0.0.1:8022>。

也可以直接运行 ASGI 应用：

```bash
uvicorn webssh.app:app --host 0.0.0.0 --port 8022
```

使用 `--launch-browser` 可以在服务端确认启动成功后调用系统默认浏览器打开 Web UI。浏览器只会打开一次；如果存在多个监听地址，py-web-ssh 会优先使用 `127.0.0.1` 作为浏览器 URL。

```bash
py-web-ssh --launch-browser
```

使用 `--auto-port` 时，程序会先尝试配置的 `--port`，如果端口被占用，就继续向上尝试，直到找到可以绑定的端口。

```bash
py-web-ssh --host 127.0.0.1 --port 8022 --auto-port --launch-browser
```

Windows 下冻结打包后的单文件 exe 如果无参数启动，会等同于使用：

```bash
py-web-ssh.exe --host 127.0.0.1 --auto-port --launch-browser
```

如果启动 exe 时传入任何参数，则保持和 Python 包相同的命令行行为。

## 登录方式

连接表单支持密码、浏览器上传私钥、私钥口令，以及使用服务端进程用户默认 `~/.ssh` 密钥。

如果没有填写密码、没有上传自定义私钥，也没有启用服务端本机密钥查找，py-web-ssh 会优先尝试 SSH none authentication。这支持那些不需要密码也不需要公钥即可登录的服务器。

每次交互 SSH 连接都会在终端中显示服务器 host key 指纹，并等待浏览器用户输入 `Y` 或 `N` 后才继续认证。程序不使用 `known_hosts` 校验。

## PIN 门禁

启动时传入 `--pin`，可以要求浏览器先输入 PIN，之后才允许访问 UI API、日志、文件接口和 WebSocket。

```bash
py-web-ssh --pin 123456
```

验证成功后，浏览器会保存一个带签名的加盐哈希 cookie。

## 品牌设置

```bash
py-web-ssh --title "Ops SSH" --subtitle "Production Access"
```

副标题区域会始终包含包版本 `(py-web-ssh vx.y.z)`。标题和副标题不会跟随 UI 语言变化。

## 服务端锁定

可以从服务端强制锁定连接参数：

```bash
py-web-ssh --lock-host server.example.com --lock-username deploy
py-web-ssh --lock-pwd "ssh-password"
py-web-ssh --lock-private-key C:\secrets\id_ed25519
```

`--lock-pwd` 和 `--lock-private-key` 只在服务端使用，不会通过 `GET /api/config` 返回给浏览器。`--lock-private-key` 指向服务端本机文件路径，不是浏览器上传的文件。

## 目标 Host 限制

```bash
py-web-ssh --ban-lan
py-web-ssh --ban-dns
py-web-ssh --ban-ipv6
py-web-ssh --ban-host secret.internal --ban-host "*.corp.local"
```

`--ban-lan` 会拦截 `192.168.1.10`、`127.0.0.1`、`::1`、`fc00::1`、`fe80::1` 这类私有或本地 IP 字面量。它不会解析域名，所以某个域名即使 DNS 指向局域网 IP，也不会被这个规则拦截。

`--ban-dns` 只允许 IP 地址字面量，域名会被拒绝。

`--ban-ipv6` 拒绝 IPv6 地址字面量。IPv4 字面量和域名仍会被允许，除非被其他规则拦截。

`--ban-host` 可以重复传入。匹配只在后端执行，大小写不敏感，支持 `*` 通配符；`*` 可以匹配 host 中的任意字符，包括点，也可以匹配零个字符。目标命中禁止模式时，API 会返回域名解析失败，而不会暴露封禁规则。

## 会话与重连

创建会话会返回一个随机 SSH 会话 UUID。如果 WebSocket 断开，浏览器可以用同一个 UUID 重连。服务端会保存 SSH 输出流，浏览器也会定期发送 xterm serialize 快照；重连时会先恢复最新快照，再补放服务端保存的后续输出。

同一个 UUID 的所有浏览器连接都断开后，如果 5 分钟内无人重连，服务端会主动断开 SSH 并清理内存缓存。

日志页面 `/sessions/{uuid}/logs` 会显示连接、认证、错误和文件传输日志。

## Files 面板

文件传输不使用 SFTP 或 SCP。每次传输都会按相同连接配置创建独立 SSH 连接，校验服务器 host key 仍然等于用户在交互终端确认过的 key，然后通过有长度限制的远端 shell 命令移动数据。

上传会把 base64 分块追加到远端临时文件，解码成临时数据文件，再移动到最终路径。下载会通过独立 SSH 命令把文件内容流式返回。

上传前会探测目标路径。如果目标是远端目录，就使用浏览器上传文件的原始文件名放入该目录；如果目标不存在或是普通文件，则按指定路径覆盖。

上传命令大小探测默认从 1 MiB 开始。Files 面板允许用户用 `MB`、`KB` 或 `B` 单位输入任意正整数。前端会把小于 `64 B` 的值强制改为 `64 B`；后端也会执行 `64 B` 的最小值限制。如果初始探测因为命令过长或连接关闭失败，py-web-ssh 会二分向下探测，并把最终选择的大小写入日志。

## CWD Sync

Files 面板包含一个只读的当前工作目录文本框，以及默认勾选的 `CWD Sync` 复选框。启用时，py-web-ssh 会在登录后安装隐藏的 shell 侧监控，并在终端输出发给浏览器之前过滤掉私有 OSC 汇报。远端 shell 在 `cd`、`pushd`、`popd` 等目录变化后回到提示符时，这个字段会更新。

取消勾选 `CWD Sync` 后，后端停止汇报 CWD 更新，只读文本框会被清空。重新勾选后，文本框仍保持为空，直到下一次观察到目录变化。

CWD Sync 启用时，上传功能使用的默认路径会跟随同步到的当前工作目录变化。

## 静态资源

前端默认从 jsDelivr 加载 xterm.js、fit addon 和 serialize addon。离线内网部署时，请把这些资源 vendoring 到 `webssh/static/`，并更新 `webssh/static/index.html` 里的 CDN URL。

## 安全提示

py-web-ssh 默认面向可信内网或本机使用。私钥和口令只保存在进程内存中，不写入日志。SSH agent 认证已禁用。如果要暴露到公网，请额外加入 HTTPS、更强登录认证、CSRF/来源限制、审计和会话回收策略。

