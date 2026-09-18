from __future__ import annotations

import json
import os

import httpx


def main() -> int:
    base_url = os.environ.get("EMBEDDING_API_BASE", "").rstrip("/")
    api_key = os.environ.get("EMBEDDING_API_KEY")
    model = os.environ.get("EMBEDDING_MODEL", "qwen3.7-text-embedding")
    dimensions = int(os.environ.get("EMBEDDING_DIMENSIONS", "1024"))
    if not base_url or not api_key:
        raise RuntimeError("rotated Embedding base URL and key are required")
    response = httpx.post(
        f"{base_url}/embeddings",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "input": ["Agent Quality Harness embedding preflight"],
            "dimensions": dimensions,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != 1:
        raise RuntimeError("Embedding response did not contain exactly one vector")
    vector = data[0].get("embedding") if isinstance(data[0], dict) else None
    if not isinstance(vector, list) or len(vector) != dimensions:
        raise RuntimeError("Embedding vector length does not match the required dimensions")
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    print(
        json.dumps(
            {
                "status": "ok",
                "requested_model": model,
                "response_model": payload.get("model"),
                "dimensions": len(vector),
                "usage": usage,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
