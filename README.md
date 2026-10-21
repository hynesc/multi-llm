# Multi-LLM: Best-of-N Response Selection

An OpenAI-compatible chat proxy that generates several candidate responses, asks a judge model to select one, and returns the winner. It supports repeated sampling from one model and pools of different models through configurable provider endpoints.

## Implementation and setup guides

[CONFIGURATION.md](CONFIGURATION.md) covers pseudo-model YAML, all effective fields, sampling precedence, Ollama model preparation, Open WebUI connection settings, Docker/host addresses, restart behavior, persistence, and troubleshooting. [ARCHITECTURE.md](ARCHITECTURE.md) maps the request flow to code.

## Features

- Concurrent candidate generation with fixed counts or proportional model weights.
- A configurable judge model and a deterministic fallback when judging fails.
- Partial-failure handling: one failed provider does not discard usable responses.
- OpenAI-style model discovery and chat completion endpoints for clients such as Open WebUI.
- YAML configuration and environment-based endpoints and credentials.
- Docker Compose integration and automated tests using fake providers.

## Quick start

Requires Python 3.11+ and a reachable Ollama instance. Clone the repository and install:

```bash
git clone https://github.com/hynesc/multi-llm.git
cd multi-llm
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Download the models used by the default strategy, then start the proxy:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5:14b
bon serve
```

The API listens on `http://127.0.0.1:8000`. The default strategy generates three candidates with `llama3.1:8b` and judges with `qwen2.5:14b`. Adjust the models in `config/config.yaml` to fit your hardware.

```bash
curl http://127.0.0.1:8000/v1/models
curl http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bon/llama3.1","messages":[{"role":"user","content":"Explain best-of-N selection in two sentences."}]}'
```

For Open WebUI running on the host, add an OpenAI-compatible connection with base URL `http://127.0.0.1:8000/v1`. The local proxy does not validate API keys; use a placeholder if the client requires one. Strategy names are pseudo-models published by the proxy, not models created or downloaded into Ollama. See the [deployment-specific connection table](CONFIGURATION.md#connect-open-webui) when WebUI runs in Docker or on another machine.

## Configuration

`config/config.yaml` defines providers, strategies, candidates, and judges. The defaults contain no private network addresses or credentials. Select another file with `bon serve --config config/custom.local.yaml` or the `BON_CONFIG_PATH` environment variable.

Override the Ollama endpoint without editing YAML:

```bash
export OLLAMA_BASE_URL=http://localhost:11434/v1
bon serve
```

Each strategy specifies `n`, a candidate list, sampling settings, and a judge. Candidate `count` values reserve fixed slots; positive `weight` values divide the remaining slots. The included `bon-pool/general` strategy uses three different models; also pull `qwen2.5:7b` and `mistral:7b` before using it.

Providers use OpenAI-compatible endpoints. For a provider requiring credentials, set `api_key_env` to the name of an exported environment variable and reference that provider in a strategy. The Python application reads exported variables rather than automatically loading `.env`; Docker Compose loads `.env` automatically. Keep private configuration in ignored `config/*.local.yaml` files.

The internal package is named `bon_llm`, and the launcher command is `bon serve`.

## Docker

Run Ollama on the host and download the configured models, then:

```bash
docker compose up --build
```

Open WebUI is available at `http://localhost:3000` and the proxy at `http://localhost:8000`. The container reaches host Ollama through `host.docker.internal`, including a Linux host-gateway mapping. Host Ollama must listen on an interface reachable from Docker; restrict access with the host firewall. Alternatively, set `OLLAMA_BASE_URL` to a reachable Ollama service URL.

Host ports bind to loopback. The Open WebUI image uses the upstream `main` tag; pin a tested version for repeatable deployments.

## Tests

```bash
python -m pytest -q
```

Tests cover candidate expansion, selection and fallback, configuration, provider URL handling, API requests, SSE responses, and partial or complete upstream failures. They require no model downloads or external credentials. GitHub Actions runs the suite on Python 3.11 and 3.12.

## Tradeoffs and scope

Best-of-N usually requires N candidate generations plus a judging call for each request. All candidates finish before selection. `stream: true` sends the completed winner as an SSE response after selection; it is not token-by-token generation.

The default judge rubric favors correctness, supported claims, and appropriate uncertainty, including clarification or refusal when warranted. A judge can still be biased or wrong. The fallback heuristic favors nonempty completed answers without penalizing refusal phrases or establishing correctness. This project demonstrates the selection mechanism; it makes no measured claim of improved answer quality.

The proxy is intended for trusted local use and has no inbound authentication, rate limiting, or global generation limit. Text chat is the supported workflow. Returned usage reflects only the selected upstream response, not total strategy cost. Configured cloud providers receive prompts and may incur charges.

See [CONFIGURATION.md](CONFIGURATION.md) for the complete setup and configuration reference, [ARCHITECTURE.md](ARCHITECTURE.md) for the request flow, and [PUBLISHING.md](PUBLISHING.md) for the initial repository push.
