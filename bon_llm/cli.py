"""Command-line launcher for the best-of-N chat proxy."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Best-of-N multi-model chat proxy.")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the chat API.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--config", type=Path, help="YAML config; otherwise use BON_CONFIG_PATH or config/config.yaml.")
    args = parser.parse_args()
    if args.config is not None:
        os.environ["BON_CONFIG_PATH"] = str(args.config.resolve())
    uvicorn.run("bon_llm.api:app", host=args.host, port=args.port, reload=False)
