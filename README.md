# nemor-link

Trusted, application-scoped connection state for Nemor command-line tools.

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

Each application has its own selected server, token, and model. Server identity
and capability metadata are shared, but `nemor-link` has no global preferred
host, credentials, or model. State is stored atomically in a machine-managed
file under the platform configuration directory. The file is created with
user-only permissions where supported.

The standalone commands provide the same operations:

```console
nemor-link --app commit connect 192.168.0.90
nemor-link --app commit status
nemor-link --app commit list-models
nemor-link --app commit set-model very-good-model
nemor-link --app commit set-token TOKEN
nemor-link --app commit disconnect
```

## Python API

Pass an application name to use its connection state:

```python
import nemor_link as nl

client = nl.llm(tool="commit")
response = client.chat([{"role": "user", "content": "hello"}])
```

Applications with an existing generated profile configuration, including
`voice-input`, remain supported by passing `config=` or `name=` explicitly.
Profiles are a compatibility API and are not part of the new end-user flow.
