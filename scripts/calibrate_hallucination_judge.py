from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agent_quality_harness.core.config import Settings
from agent_quality_harness.judging import OpenAICompatibleHallucinationJudge

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def _run(document: dict[str, object]) -> dict[str, object]:
    settings = Settings()
    if not settings.judge_enabled or settings.judge_api_key is None:
        raise RuntimeError("set AQH_JUDGE_ENABLED and AQH_JUDGE_API_KEY for calibration")
    judge = OpenAICompatibleHallucinationJudge(
        base_url=settings.judge_base_url,
        model=settings.judge_model,
        api_key=settings.judge_api_key.get_secret_value(),
        timeout_seconds=settings.judge_timeout_seconds,
    )
    if document.get("schema") != "aqh.hallucination-calibration/v1":
        raise ValueError("unsupported calibration schema")
    known = correct = 0
    for case in document.get("cases", []):
        result = await judge.evaluate(
            case_id=str(case["id"]),
            specification={"required_claim_ids": [item["id"] for item in case["claims"]]},
            output={"claims": case["claims"], "evidence": case["evidence"]},
        )
        if result.status == "known":
            known += 1
            correct += int(result.verdict == case["expected"])
    total = len(document.get("cases", []))
    return {
        "schema": document["schema"],
        "version": document["version"],
        "total": total,
        "known": known,
        "unknown": total - known,
        "accuracy": correct / known if known else None,
        "model": settings.judge_model,
        "prompt_version": judge.prompt_version,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate the bounded hallucination Judge")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "datasets" / "hallucination-judge-calibration-v1.json",
    )
    args = parser.parse_args()
    document = json.loads(args.dataset.resolve().read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(_run(document)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
