import httpx

from agent_quality_harness.policy import (
    OpaClient,
    canonical_policy_sha256,
    validate_package_namespace,
)

REGO = """package aqh.org_7.release.v_1

decision := {"decision": "warn", "reasons": [{
  "rule_id": "cost_limit",
  "severity": "warn",
  "actual": {"growth": 0.3},
  "threshold": {"growth": 0.2}
}]}
"""


def test_policy_namespace_and_hash_are_deterministic() -> None:
    validate_package_namespace(REGO, "aqh.org_7.release.v_1", 7)
    first = canonical_policy_sha256(
        rego=REGO,
        data={"b": 2, "a": 1},
        package_path="aqh.org_7.release.v_1",
        entrypoint="decision",
    )
    second = canonical_policy_sha256(
        rego=REGO,
        data={"a": 1, "b": 2},
        package_path="aqh.org_7.release.v_1",
        entrypoint="decision",
    )
    assert first == second


def test_opa_validation_and_evaluation_preserve_decision_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "decision_id": "decision-123",
                    "result": {
                        "decision": "warn",
                        "reasons": [
                            {
                                "rule_id": "cost_limit",
                                "severity": "warn",
                                "actual": {"growth": 0.3},
                                "threshold": {"growth": 0.2},
                            }
                        ],
                    },
                },
            )
        return httpx.Response(200, json={})

    client = OpaClient("http://opa", transport=httpx.MockTransport(handler))

    assert client.validate(policy_id="policy-1", rego=REGO) == []
    result = client.evaluate(
        policy_id="policy-1",
        rego=REGO,
        data={},
        data_path="aqh_policy_data/org_7/bundle_1",
        package_path="aqh.org_7.release.v_1",
        entrypoint="decision",
        input_data={"metrics": {"candidate": {"success_rate": 1}}},
    )

    assert result.decision == "warn"
    assert result.decision_id == "decision-123"
    assert result.reasons[0]["source"] == "opa"
    assert result.error is None


def test_opa_undefined_and_unavailable_fail_closed() -> None:
    undefined = OpaClient(
        "http://opa",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    result = undefined.evaluate(
        policy_id="policy-1",
        rego=REGO,
        data={},
        data_path="aqh_policy_data/org_7/bundle_1",
        package_path="aqh.org_7.release.v_1",
        entrypoint="decision",
        input_data={"metrics": {}},
    )
    assert result.decision == "block"
    assert result.reasons[0]["rule_id"] == "policy_engine_error"

    def disconnected(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    unavailable = OpaClient("http://opa", transport=httpx.MockTransport(disconnected))
    errors = unavailable.validate(policy_id="policy-1", rego=REGO)
    assert errors == [{"code": "policy_engine_error", "message": "OPA connection failed"}]
