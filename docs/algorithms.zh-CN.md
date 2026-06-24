# SSH 算法控制

[English](algorithms.md)

py-web-ssh 允许浏览器选择后续 SSH 连接中要禁用哪些 SSH 算法。实际协商仍由 Paramiko 完成；UI 只是收窄 Paramiko 支持的算法列表。

## 算法分组

`GET /api/algorithms` 会返回当前服务端 Paramiko 运行时支持的算法分组：

- `kex`：密钥交换算法。
- `ciphers`：加密算法。
- `digests`：MAC / 摘要算法。
- `key_types`：服务器 host key 算法。
- `pubkeys`：公钥签名算法。

前端 Algorithms 面板会显示这些分组。所有算法默认都是选中状态。用户取消勾选某一项时，浏览器会在 `POST /api/sessions` 时把这一项放入 `disabled_algorithms` 对象。

## 请求形状

`disabled_algorithms` 是一个以分组 id 为 key 的对象：

```json
{
  "disabled_algorithms": {
    "kex": ["diffie-hellman-group1-sha1"],
    "ciphers": ["3des-cbc"],
    "digests": [],
    "key_types": ["ssh-dss"],
    "pubkeys": ["ssh-rsa"]
  }
}
```

缺失的分组和空列表表示该分组不禁用任何算法。

## 校验

后端会在创建会话前校验 `disabled_algorithms`：

- 值必须是对象。
- 分组 id 必须是 `kex`、`ciphers`、`digests`、`key_types` 或 `pubkeys`。
- 每个被禁用的算法都必须被当前 Paramiko 运行时支持。
- 每个分组都必须至少保留一个可用算法。

不支持的分组或算法名会让 `POST /api/sessions` 返回 `422`。

## 运行时排序

py-web-ssh 会从三个来源构造每个分组最终启用的列表：

- `webssh.ssh_client.BROAD_ALGORITHM_ORDER` 中维护的宽兼容优先顺序；
- Paramiko 当前的首选算法顺序；
- Paramiko 报告的其他剩余算法。

构造时会在保持顺序的同时去重。浏览器禁用的算法会从最终列表中移除，随后这个列表会在 `start_client()` 前写入 Paramiko 的 `SecurityOptions`。

## 日志

每次 SSH 连接中，py-web-ssh 都会记录：

- 实际写入 Paramiko 的最终启用算法；
- 浏览器选择禁用的算法；
- 当前 Paramiko 运行时不支持的宽兼容列表算法。

这些日志可以在会话日志页面或 `GET /api/sessions/{uuid}/logs` 中查看。

## 说明

算法列表取决于已安装的 Paramiko 版本及其加密后端。升级 Paramiko 可能会改变 `GET /api/algorithms` 返回的选项。

Host key 确认与算法选择是两件事。py-web-ssh 仍会在终端中显示服务器 host key 指纹，并要求浏览器用户接受或拒绝后才继续认证。

