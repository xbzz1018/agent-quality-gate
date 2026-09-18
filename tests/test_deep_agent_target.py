import httpx

from agent_quality_harness.fake_deep_agent import create_deep_agent_target_app


async def test_deepagents_target_and_plain_control_share_http_contract() -> None:
    app = create_deep_agent_target_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://deep") as client:
        control = await client.post(
            "/invoke",
            json={
                "input": {"prompt": "deterministic request"},
                "context": {"target_version": "control"},
            },
        )
        candidate = await client.post(
            "/invoke",
            json={
                "input": {"prompt": "deterministic request"},
                "context": {"target_version": "deepagents"},
            },
        )

    assert control.status_code == 200
    assert control.json()["output"] == {
        "text": "deterministic request",
        "harness": "plain-control",
        "state_keys": [],
    }
    assert candidate.status_code == 200
    assert candidate.json()["output"]["text"] == "deterministic request"
    assert candidate.json()["output"]["harness"] == "deepagents-0.7.6"
    assert candidate.json()["output"]["state_keys"] == ["files", "messages"]
    assert candidate.json()["usage"] == {"input_tokens": 4, "output_tokens": 2}
