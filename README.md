# inference-link

Trusted, application-scoped connections to self-hosted AI services.

`inference-link` is a small client-side connection layer for tools that share a
private LLM, speech-to-text, or text-to-speech server. It lets a user verify a
server once, keeps tokens and model choices separate between applications, and
can expose the trusted connection as a temporary OpenAI-compatible localhost
endpoint.

The project does not run models and is not a provider-neutral AI SDK. It owns
connection onboarding, server identity, local state, and lightweight sync
clients for a documented HTTP contract.

## Install

```console
python -m pip install inference-link
```

Python 3.9 or newer is required.

## Why use it?

- **Trust on first use.** HTTPS servers may use a self-signed certificate. On
  first contact, the user verifies its SHA-256 fingerprint; later connections
  are pinned to that certificate.
- **Application scopes.** Each integrating tool can inherit the default
  connection or keep its own server, token, and model selection.
- **No hand-written connection file.** Onboarding and model selection are
  exposed as CLI actions that applications can embed.
- **OpenAI-compatible bridge.** Existing programs can run through a temporary
  authenticated relay on `127.0.0.1` without receiving the upstream token.
- **Small synchronous clients.** Python callers can use built-in LLM, STT, and
  TTS clients, including backend health checks and failover for profile-based
  configurations.

## Connect from the command line

A bare address means HTTPS on port 8090:

```console
inference-link connect 192.168.0.90
inference-link set-token TOKEN       # only when the server requires authentication
inference-link list-models
inference-link set-model my-model
inference-link status
```

The first HTTPS connection prints the server certificate fingerprint and asks
for confirmation. Verify that fingerprint through a separate trusted channel
before accepting it.

Plain HTTP must be requested explicitly:

```console
inference-link connect http://127.0.0.1:8090
```

HTTP has no authenticated server identity, so the command displays a warning.

## Run an OpenAI-compatible application

`run` starts a relay on a random loopback port and exports `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL` to the child process:

```console
inference-link run -- my-openai-cli
inference-link --app code-review run -- my-openai-cli --model-from-env
```

The relay accepts only its generated bearer token, forwards requests to the
trusted upstream connection, and stops when the child exits. The child sees
the relay token, not the upstream token.

## Embed connection actions in another CLI

Applications can expose the same onboarding flow under their own command:

```python
import argparse
import inference_link as nl

parser = argparse.ArgumentParser()
nl.add_connection_arguments(parser)
args = parser.parse_args()

if nl.handle_connection_action(args, command="my-tool"):
    raise SystemExit(0)

with nl.llm(tool="my-tool") as client:
    response = client.chat([
        {"role": "user", "content": "Hello"},
    ])
    print(response["choices"][0]["message"]["content"])
```

The application inherits the default connection until the user connects that
application to another server or changes one of its settings.

## Python clients

The connection-state API provides synchronous clients:

```python
import inference_link as nl

with nl.llm(tool="my-tool") as client:
    response = client.chat([{"role": "user", "content": "Hello"}])

with nl.stt(tool="voice-input") as client:
    transcript = client.transcribe(open("audio.raw", "rb").read())

with nl.tts(tool="voice-output") as client:
    audio = client.synthesize("Hello")
```

Existing profile configurations remain available through the `name=` and
`config=` arguments. Profiles can contain an ordered backend list and are the
API to use when client-side health probing and failover are required.

## Migrating from `nemor-link`

The distribution, import package, and primary executable were renamed in
version 0.2.0:

```text
nemor-link   -> inference-link
nemor_link   -> inference_link
```

The old executable and Python import remain as deprecated compatibility
aliases. Existing connection state under `~/.config/nemor-link/state.json` is
read when the new state file does not exist; the next state-changing command
writes to `~/.config/inference-link/state.json`. Legacy profile configuration
at `~/.config/llm.json` is also used as a fallback for the new
`~/.config/inference-link/profiles.json` path.

## Server contract

The current clients expect a server with these endpoints:

- `GET /v1/capabilities` for public connection capabilities; older servers may
  expose only `GET /health`;
- `GET /v1/models` for model selection;
- `POST /v1/chat/completions` for OpenAI-compatible chat completions;
- `POST /stt` for raw audio transcription;
- `POST /tts/generate` for speech synthesis.

Authentication uses `Authorization: Bearer ...`. A server may additionally
advertise whether authentication is required through its capabilities
response. STT runtimes and prompts currently use dedicated request headers.

STT `initial_prompt` uses the following version-1 header contract:

- printable ASCII is sent unchanged as `X-Initial-Prompt` for compatibility;
- other Unicode text is UTF-8 encoded, then standard-Base64 encoded, and sent
  as `X-Initial-Prompt-Encoded: v1:<base64>`;
- a request containing both prompt headers, an unknown version, invalid Base64,
  or invalid UTF-8 is malformed and should receive a 400 response.

Servers can use the bundled strict decoder before passing the result to their
speech runtime:

```python
from inference_link import InitialPromptEncodingError, decode_initial_prompt

try:
    initial_prompt = decode_initial_prompt(request.headers)
except InitialPromptEncodingError:
    return {"error": "invalid initial prompt"}, 400
```

## Security model

- HTTPS identity uses trust on first use, not a public certificate authority.
  The first fingerprint confirmation is therefore security-sensitive.
- A changed certificate is rejected until the user explicitly reconnects and
  trusts the new identity.
- Connection state is stored atomically under the platform configuration
  directory (`~/.config/inference-link/state.json` on typical Linux systems).
  On POSIX, newly written state files use mode `0600` and their directory is
  created with mode `0700`.
- Tokens are stored in that state file; they are not placed in an operating
  system keychain. Avoid passing long-lived tokens on a shared machine where
  process arguments or shell history are observable.
- Explicit HTTP connections provide transport but no server authentication or
  confidentiality.

## Current limitations

- The API is synchronous.
- The server HTTP contract above is currently required; arbitrary model
  runtimes are not discovered or started by the client.

## License

MIT. See [LICENSE](LICENSE).
