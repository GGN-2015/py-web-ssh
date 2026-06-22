# py-web-ssh

一个基于 Python/FastAPI/Paramiko 的 Web SSH 客户端。前端使用 xterm.js 渲染真实终端控制序列，后端通过 WebSocket 转发 SSH 交互数据，并为每个网页客户端分配随机 UUID，支持同 UUID 断线重连、终端快照恢复、日志查看和文件上传下载。

## 功能

- SSH 交互终端：Paramiko 后端 `invoke_shell`，xterm.js 前端实时交互。
- 登录方式：密码、浏览器上传私钥、私钥口令、服务端本机默认 `~/.ssh` 密钥、免口令/none auth。
- Host key 确认：不使用 `known_hosts` 校验；每次交互 SSH 连接都会在 xterm.js 终端里显示服务器 host key 指纹，并要求用户输入 `Y` 或 `N` 后才继续认证。
- Legacy 兼容：启动时按当前 Paramiko 运行时能力尽量启用旧 KEX/Cipher/MAC/HostKey/Pubkey 算法，并在日志中列出不可用算法。
- UUID 会话：创建会话后返回 UUID，WebSocket 断开后可用同 UUID 重连。
- 会话回收：同一个 UUID 如果所有浏览器连接都断开并且 5 分钟内无人重连，服务端会主动断开 SSH 并清理内存缓存。
- 终端恢复：服务端保存 SSH 输出流，浏览器定期回传 xterm serialize 快照；重连时先恢复快照，再补放快照之后的输出。
- 日志页面：`/sessions/{uuid}/logs` 展示完整连接、认证、错误和文件传输日志。
- 文件传输：参考 `simple-ssh-copy` 思路，不使用 SFTP/SCP；每次传输都按连接配置新建独立 SSH 连接，使用远端 `base64` shell 命令上传/下载。上传先写远端临时文件，完成后再 `mv` 到最终路径，并支持进度显示和取消。文件传输连接会校验服务器 host key 必须等于用户在交互终端里确认过的 host key。
- 可选 PIN 门禁：服务端传入 `--pin` 后，网页启动时必须先输入正确 PIN；验证成功后浏览器会保存加盐哈希 cookie，后端会保护 HTTP API、日志页面、文件接口和 WebSocket。
- 启动锁定策略：支持 `--lock-host`、`--lock-username`、`--lock-pwd`、`--lock-private-key`，可从服务端强制绑定目标主机、用户名、密码和服务端侧私钥文件。前端会锁定或隐藏对应控件，后端仍会校验并覆盖敏感字段。
- 中英双语：默认英文，网页和日志页都支持中英切换；语言选择会长期保存到 `py_web_ssh_lang` cookie。
- 浏览器客户端 session：首次访问时服务端会分配独立的浏览器 session UUID，并写入 HttpOnly cookie；它与 SSH 会话 UUID 分离。
- 左侧控制面板：连接、会话、文件三个栏目改为互斥折叠面板，一次最多展开一个，也可以全部折叠。

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

## 启动

```bash
py-web-ssh
```

或者：

```bash
uvicorn webssh.app:app --host 0.0.0.0 --port 8022
```

打开 <http://127.0.0.1:8022>。

启用 PIN：

```bash
py-web-ssh --pin 123456
```

锁定连接目标或凭据：

```bash
py-web-ssh --lock-host server.example.com --lock-username deploy
py-web-ssh --lock-pwd 'ssh-password'
py-web-ssh --lock-private-key C:\secrets\id_ed25519
```

`--lock-pwd` 和 `--lock-private-key` 的值只在服务端使用，不会通过配置接口发送给浏览器。`--lock-private-key` 指向的是服务端本机文件路径，不是浏览器上传的文件。

前端默认从 jsDelivr 加载 xterm.js、fit addon 和 serialize addon。离线内网部署时，请把这些静态资源 vendoring 到 `webssh/static/` 并替换 `index.html` 里的 CDN 地址。

## API 概览

- `GET /api/config` 查看非敏感的服务端公开配置和锁定状态。
- `POST /api/sessions` 创建 SSH 会话。
- `GET /api/sessions/{uuid}` 查看会话状态。
- `GET /api/sessions/{uuid}/logs` 获取完整日志 JSON。
- `DELETE /api/sessions/{uuid}` 主动断开 SSH。
- `WS /ws/sessions/{uuid}` 终端输入、输出、resize、快照和断开控制。
- `POST /api/sessions/{uuid}/files/upload` 上传文件，multipart 字段：`remote_path`、`file`。
- `GET /api/sessions/{uuid}/files/download?remote_path=/path/file` 下载远端文件。

## 安全提示

这个项目默认面向可信内网或本机使用。私钥和口令只保存在进程内存中，不写入日志；SSH agent 已禁用，`known_hosts` 校验已移除，用户必须在 xterm.js 终端里确认服务器 host key 指纹后才会继续认证。如果要暴露到公网，请务必加 HTTPS、登录认证、CSRF/来源限制、审计和会话回收策略。
