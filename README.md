# nemor-link

Trusted, shared connection state for Nemor command-line tools.

No configuration file needs to be written by hand. Any integrated utility can
perform onboarding:

```console
commit --connect 192.168.0.90
commit --list-models
commit --set-model very-good-model
commit
```

A bare address means HTTPS on the default `llm-proxy` API port, 8090. On first
contact, the utility prints the server certificate's SHA-256 fingerprint and
asks the user to verify and trust it. Later requests are pinned to that
fingerprint. Plain HTTP is available only when explicitly requested, for
example `http://127.0.0.1:8090`, and produces a warning because it has no server
identity.

The selected server, fingerprint, token, and model are stored atomically in a
machine-managed state file under the platform configuration directory. The
file is created with user-only permissions where supported.

The standalone commands provide the same operations:

```console
nemor-link connect 192.168.0.90
nemor-link status
nemor-link list-models
nemor-link set-model very-good-model
nemor-link set-token TOKEN
nemor-link disconnect
```

## Python API

The default constructors use shared connection state:

```python
import nemor_link as nl

client = nl.llm(tool="commit")
response = client.chat([{"role": "user", "content": "hello"}])
```

Applications with an existing generated profile configuration, including
`voice-input`, remain supported by passing `config=` or `name=` explicitly.
Profiles are a compatibility API and are not part of the new end-user flow.
