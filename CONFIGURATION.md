# Pseudo-model configuration and Open WebUI setup

YAML strategy names such as `bon/llama3.1` are **pseudo-model IDs**, not Ollama weights or Modelfiles. Open WebUI discovers them through `GET /v1/models` and submits chats to `/v1/chat/completions`. The proxy calls Ollama's OpenAI-compatible `/v1` API, not its native `/api/chat` endpoint.

See [architecture](ARCHITECTURE.md) for generation/selection flow and [Ollama's compatibility guide](https://docs.ollama.com/api/openai-compatibility) for upstream behavior.

## Configuration files and lifecycle

| File or setting | Role |
| --- | --- |
| `config/config.yaml` | Default provider and pseudo-model definitions. |
| `config/*.local.yaml` | Ignored location for private/operator-specific configuration. |
| `.env.example` | Optional exported-variable template; no real credentials. |
| `docker-compose.yml` | Proxy/WebUI ports, network addresses, environment forwarding, and WebUI persistence. |
| `bon serve --config <path>` | Selects a YAML file, resolving the path before starting the API. |
| `BON_CONFIG_PATH` | Selects a YAML file when no CLI `--config` is supplied. Defaults to `config/config.yaml` relative to the process working directory. |
| `OLLAMA_BASE_URL` | Overrides the example provider endpoint because its `base_url_env` names this variable. |

`--config` overrides `BON_CONFIG_PATH`. YAML loads once at startup; restart after edits. There is no live reload, automatic model pull, or implicit variable interpolation. `base_url_env` and `api_key_env` explicitly name environment overrides.

The Python process reads exported variables. To use `.env` on the host:

```bash
cp .env.example .env
# Edit .env before exporting it.
set -a
source .env
set +a
bon serve
```

Compose uses `.env` for substitution and loads `/app/config/config.yaml` from `./config`. Its fixed path overrides a host `BON_CONFIG_PATH`. Forward additional provider keys through the service environment; writing them to `.env` alone does not inject them.

## Providers

```yaml
providers:
  ollama:
    base_url: http://localhost:11434/v1
    base_url_env: OLLAMA_BASE_URL
    timeout_seconds: 120
    max_retries: 1
```

| Field | Meaning |
| --- | --- |
| `base_url` | Provider API base, including `/v1`; omit `/chat/completions`. |
| `base_url_env` | Optional environment variable whose nonempty value overrides the base URL. |
| `api_key_env` | Optional environment variable containing an upstream API credential. |
| `api_key` | Optional inline secret; prefer `api_key_env` in shareable configuration. An inline value takes precedence. |
| `timeout_seconds` | Provider HTTP timeout, default 120 seconds; also applies to its judge calls. |
| `max_retries` | Number of retries after the first attempt, default 2. The sample Ollama provider uses 1. |

Candidate/judge provider names must exist. Model availability is checked on request, not startup. HTTP and invalid-JSON failures retry with exponential backoff; invalid judge selections trigger fallback.

The proxy ignores incoming API keys. WebUI's placeholder key is separate from upstream provider credentials.

## Pseudo-models and model pools

The shipped configuration defines:

| Pseudo-model ID | Candidate calls | Judge |
| --- | --- | --- |
| `bon/llama3.1` | Three calls to `llama3.1:8b`. | `qwen2.5:14b` |
| `bon-pool/general` | One call each to `llama3.1:8b`, `qwen2.5:7b`, and `mistral:7b`. | `qwen2.5:14b` |

Pull the relevant models on the **Ollama server**, not into the proxy image:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5:14b
# Also needed for bon-pool/general:
ollama pull qwen2.5:7b
ollama pull mistral:7b
```

A complete strategy definition looks like:

```yaml
strategies:
  bon/custom:
    n: 3
    candidates:
      - provider: ollama
        model: llama3.1:8b
        weight: 1
    judge:
      provider: ollama
      model: qwen2.5:14b
      sampling:
        temperature: 0
    sampling:
      temperature: 0.7
      top_p: 0.95
      max_tokens: 512
```

| Field | Meaning |
| --- | --- |
| Strategy dictionary key | Client-visible ID returned by `/v1/models`; use exactly this ID in chat requests. |
| `n` | Positive total candidate count, default 3. |
| `candidates` | Nonempty list of upstream provider/model pairs. |
| Candidate `count` | Positive fixed number of slots reserved for that entry. |
| Candidate `weight` | Positive proportional weight for remaining slots when `count` is absent; defaults effectively to 1. |
| Candidate `sampling` | Per-candidate temperature, top-p, and max-token overrides. |
| Strategy `sampling` | Sampling settings applied to all candidates before candidate-specific overrides. |
| `judge.provider`, `judge.model` | Required judge configuration; judge sampling defaults to temperature 0. |
| `judge.prompt` | Optional replacement rubric, combined with the conversation and candidate responses. |
| `judge.sampling` | Judge temperature, top-p, and max-token settings. |

The default rubric favors supported claims, appropriate uncertainty, clarification, and warranted refusals. It discourages fabrication and unnecessary refusals. `judge.prompt` replaces it. See [selection behavior](ARCHITECTURE.md#request-flow) for fallback criteria and limits.

Allocate fixed counts first, then divide remaining slots by normalized weights: round down and distribute leftovers by largest fractional remainder. With `n: 5`, one fixed slot and weights 3:1 produce 1 fixed, 3 heavy, and 1 light candidate. Use `count` or `weight` per entry; `count` takes precedence. Configuration rejects counts above N and fixed-only lists that underfill N.

Sampling precedence is **request → strategy → candidate**; later values win. The proxy normalizes incoming `max_completion_tokens` to `max_tokens` first. Explicit seeds become `seed + candidate index`; otherwise seeds are random. Judge sampling is separate. Supported fields are `temperature`, `top_p`, and `max_tokens`; timeouts belong to providers.

Discovery lists configured strategies only. For a single-call strategy use `n: 1` and one candidate; configuration still requires a judge, but selection skips it when one usable response exists.

## Connect Open WebUI

In Open WebUI, open **Settings → Admin → Connections → Manage OpenAI API Connections**. Add an **OpenAI-compatible** connection using the URL below and a placeholder key if required; verify and save. Select `bon/llama3.1` or `bon-pool/general` in the model picker. See the upstream [connection guide](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/).

| Deployment | Open WebUI's proxy base URL | Required binding/network |
| --- | --- | --- |
| WebUI and proxy processes both on host | `http://127.0.0.1:8000/v1` | Default `bon serve` loopback binding. |
| Supplied Compose stack | `http://bon-llm:8000/v1` | Compose service DNS; proxy listens on the container interface. |
| WebUI in Docker, proxy on host | `http://host.docker.internal:8000/v1` | Start proxy with `bon serve --host 0.0.0.0`; on Linux add host-gateway mapping to WebUI. Restrict host access. |
| WebUI on another machine | `http://<proxy-host>:8000/v1` | A reachable proxy interface or private reverse proxy/tunnel. The proxy has no inbound authentication. |

The **WebUI backend** resolves this URL. Its container's `localhost` refers to itself; a host service must accept Docker-bridge connections, not just loopback.

Compose initializes WebUI with the proxy connection and disables direct Ollama integration, which would bypass selection. Existing WebUI installations may retain saved connections despite Compose edits: update them in the admin UI, preserving the data volume. See the [environment reference](https://docs.openwebui.com/reference/env-configuration/).

## Docker-to-Ollama networking

The supplied Compose stack contains the proxy and Open WebUI; it does not start Ollama. The default proxy-container endpoint is `http://host.docker.internal:11434/v1`, with Linux `host-gateway` mapping.

Host Ollama must listen on a Docker-reachable interface. For a manual server, use `OLLAMA_HOST=0.0.0.0:11434 ollama serve` with firewall access restricted to intended clients. For an existing app/service, configure its environment and restart it; avoid a second server. See [Ollama's guidance](https://docs.ollama.com/faq#how-do-i-configure-ollama-server).

For another machine or container, set `OLLAMA_BASE_URL` to that reachable provider URL including `/v1`. The host port bindings `127.0.0.1:8000` and `127.0.0.1:3000` control browser/host access; containers on the Compose network use their service ports directly.

```bash
docker compose up --build
# After YAML configuration edits:
docker compose restart bon-llm
# After Compose environment edits:
docker compose up -d
# Stop services while preserving WebUI data:
docker compose down
```

Open WebUI's `open-webui` volume contains its own application data and conversations. The proxy itself does not persist chat responses. Preserve that volume deliberately; `docker compose down -v` would remove it.

## Verify and troubleshoot

Check the upstream and downstream separately:

```bash
# Host Ollama defaults; adapt to your chosen endpoint:
curl -fsS http://localhost:11434/v1/models
# Proxy health and pseudo-model discovery:
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/v1/models
curl -fsS http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bon/llama3.1","messages":[{"role":"user","content":"Say hello in one sentence."}]}'
```

Health checks the API process; discovery checks loaded strategies; a completion checks live candidate/judge inference.

| Symptom | Check |
| --- | --- |
| WebUI shows raw Ollama models only | Add/enable the proxy's OpenAI connection and select a configured pseudo-model. |
| Model list request fails | Include `/v1`, omit `/chat/completions` from the connection base, and test from the WebUI backend's network. |
| HTTP 404 for chat model | Use a strategy ID, not the underlying provider's model tag. |
| HTTP 502 / no usable candidates | Verify provider URL, installed models, credentials, reachability, and provider timeouts. |
| Slow first reply or timeout | Candidates and judge may need model loading; choose models/counts fitting available memory and increase the provider timeout if appropriate. |
| No tokens appear immediately | Streaming waits for candidate generation and selection, then sends the completed winner. |
| YAML edits do not show up | Restart the proxy; the public edition has no live reload. |
| Saved WebUI connection ignores Compose edits | Update its persisted admin connection rather than removing conversation data. |

[ARCHITECTURE.md](ARCHITECTURE.md) maps these behaviors to the code. This is a chat-selection proxy; it does not expose model download/delete endpoints, embeddings, tool execution, or the Responses API.
