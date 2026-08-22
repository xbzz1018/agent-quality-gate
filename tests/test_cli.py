import argparse
import json

from agent_quality_harness.cli import gate_command, gate_exit_code


def test_gate_cli_exit_codes() -> None:
    assert gate_exit_code("ship") == 0
    assert gate_exit_code("warn") == 0
    assert gate_exit_code("block") != 0
    assert gate_exit_code("failed") != 0


def test_gate_cli_warn_prints_github_annotation(tmp_path, capsys) -> None:
    report = tmp_path / "gate.json"
    report.write_text(
        json.dumps(
            {
                "decision": "warn",
                "reasons": [
                    {
                        "severity": "warn",
                        "rule_id": "latency_growth",
                        "threshold": 0.2,
                        "actual": 0.21,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(report=report, run_id=None, api_url="")

    assert gate_command(args) == 0
    assert "::warning::" in capsys.readouterr().out
