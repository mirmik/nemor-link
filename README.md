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

`nemor-link` provides a default server, token, and model. Applications use that
default until they override individual values through their own connection
flags. Connecting an application to another server starts an independent scope
and does not carry credentials to the new host. Server identity and capability
metadata remain shared. State is stored atomically in a machine-managed file
under the platform configuration directory.

The standalone commands provide the same operations:

```console
nemor-link connect 192.168.0.90
nemor-link set-token TOKEN
nemor-link set-model very-good-model
nemor-link status

# Run any OpenAI-compatible application through the trusted connection
nemor-link run -- qwen

# Optional application override
nemor-link --app commit set-model another-model
nemor-link --app commit disconnect  # return to the default
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

## Run an application

`run` starts a temporary relay on `127.0.0.1`, exports `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL` to the child process, and forwards OpenAI
API requests through the selected trusted connection. The upstream token and
TLS fingerprint remain inside `nemor-link`.

```console
nemor-link run -- qwen
nemor-link --app qwen run -- qwen --approval-mode auto-edit
```

The relay stops when the child exits, and `nemor-link` returns the child's exit
code.
