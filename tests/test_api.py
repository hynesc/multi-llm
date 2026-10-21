from __future__ import annotations

from bon_llm.api import create_app


def test_app_registers_expected_routes() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/healthz" in paths
    assert "/v1/models" in paths
    assert "/v1/chat/completions" in paths
