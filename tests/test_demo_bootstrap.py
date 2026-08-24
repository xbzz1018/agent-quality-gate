from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from agent_quality_harness.services import bootstrap_demo


def test_demo_bootstrap_updates_endpoint_for_current_runtime() -> None:
    target = SimpleNamespace(id=1, endpoint="http://127.0.0.1:8020/invoke")
    baseline = SimpleNamespace(id=2)
    candidate = SimpleNamespace(id=3)
    dataset = SimpleNamespace(id=4)
    policy = SimpleNamespace(id=5)
    pricing = SimpleNamespace(id=6)
    session = Mock()
    session.scalar.side_effect = [target, baseline, candidate, dataset, policy, pricing]

    result = bootstrap_demo(
        session,
        organization_id=99,
        dataset_path=Path("unused.json"),
        agent_endpoint="http://fake-agent:8020/invoke",
    )

    assert target.endpoint == "http://fake-agent:8020/invoke"
    assert result.created_resources == ["target_endpoint"]
    session.commit.assert_called_once_with()
    session.refresh.assert_called_once_with(target)
