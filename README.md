# Multi-LLM: Best-of-N Response Selection

An OpenAI-compatible chat proxy that generates candidate responses, asks a judge model to choose one, and returns the winner. YAML strategies appear as pseudo-models in clients such as Open WebUI.

## Features

- Concurrent sampling from one model or a pool with fixed counts and proportional weights.
- Configurable providers, sampling, and judging; partial-failure handling and deterministic fallback.
- A default judge rubric that favors supported claims and appropriate uncertainty.
- Docker Compose integration with Open WebUI.

## Quick start

Requires Python 3.11+ and a reachable Ollama server. Run from the cloned repository:

```bash
git clone https://github.com/hynesc/multi-llm.git
cd multi-llm
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
ollama pull llama3.1:8b
ollama pull qwen2.5:14b
bon serve
```

The proxy listens on `http://127.0.0.1:8000`. The default `bon/llama3.1` strategy generates three candidates and judges with `qwen2.5:14b`. Adjust models in `config/config.yaml` to fit your hardware.

```bash
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bon/llama3.1","messages":[{"role":"user","content":"Explain best-of-N selection in two sentences."}]}'
```

For WebUI on the host, add an OpenAI-compatible connection at `http://127.0.0.1:8000/v1`, using a placeholder key if required. For container or remote deployments, use the [connection table](CONFIGURATION.md#connect-open-webui).

## Docker

With the configured models available on a Docker-reachable Ollama server:

```bash
docker compose up --build
```

WebUI opens at `http://localhost:3000`. The stack starts the proxy and WebUI; Ollama runs separately. Follow [Docker networking](CONFIGURATION.md#docker-to-ollama-networking) for host bindings and endpoint overrides.

## Documentation

| Guide | Contents |
| --- | --- |
| [Configuration](CONFIGURATION.md) | Pseudo-model YAML, credentials, model downloads, WebUI, networking, and troubleshooting. |
| [Architecture](ARCHITECTURE.md) | Request flow, selection/fallback, API behavior, and persistence. |

## Limits

Text chat only, intended for trusted local use: no inbound authentication, rate limiting, or global generation limit. Each request usually needs N generations plus judging; streaming starts after selection. Returned token usage covers only the winner.

Judging and fallback can be wrong; no measured quality improvement is claimed. Cloud providers receive prompts and may incur charges. Pin a tested Open WebUI image version; the example uses `main`.

## Tests

```bash
python -m pytest -q
```

Tests use fake providers and require no model downloads or credentials. GitHub Actions tests Python 3.11/3.12 and builds the wheel.
