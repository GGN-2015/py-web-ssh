# SSH Algorithm Controls

[中文](algorithms.zh-CN.md)

py-web-ssh lets the browser choose which SSH algorithms should be disabled for later SSH connections. The server still uses Paramiko for negotiation; the UI only narrows Paramiko's supported algorithm lists.

## Algorithm Groups

`GET /api/algorithms` returns the algorithm groups supported by the current server-side Paramiko runtime:

- `kex`: key exchange algorithms.
- `ciphers`: encryption ciphers.
- `digests`: MAC / digest algorithms.
- `key_types`: server host key algorithms.
- `pubkeys`: public key signature algorithms.

The frontend Algorithms panel displays these groups. Every algorithm is selected by default. When the user unchecks an item, the browser sends that item in the `disabled_algorithms` object during `POST /api/sessions`.

## Request Shape

`disabled_algorithms` is an object keyed by group id:

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

Missing groups and empty lists mean nothing is disabled for that group.

## Validation

The backend validates `disabled_algorithms` before creating a session:

- The value must be an object.
- Group ids must be one of `kex`, `ciphers`, `digests`, `key_types`, or `pubkeys`.
- Every disabled algorithm must be supported by the current Paramiko runtime.
- At least one algorithm must remain enabled in each group.

Unsupported groups or algorithm names return `422` from `POST /api/sessions`.

## Runtime Ordering

py-web-ssh builds each enabled list from three sources:

- a broad compatibility preference list kept in `webssh.ssh_client.BROAD_ALGORITHM_ORDER`;
- Paramiko's current preferred algorithm order;
- any remaining algorithms reported by Paramiko.

Duplicates are removed while preserving order. Algorithms disabled by the browser are removed from the final list, and the list is applied to Paramiko's `SecurityOptions` before `start_client()`.

## Logging

For each SSH connection, py-web-ssh logs:

- the final enabled algorithms applied to Paramiko;
- algorithms disabled by the browser selection;
- broad-list algorithms unavailable in the current Paramiko runtime.

These logs are visible through the session logs page and `GET /api/sessions/{uuid}/logs`.

## Notes

The algorithm list depends on the installed Paramiko version and its crypto backend. Upgrading Paramiko can change the options returned by `GET /api/algorithms`.

Host key confirmation is separate from algorithm selection. py-web-ssh still shows the server host key fingerprint in the terminal and requires the browser user to accept or reject it before authentication continues.

