from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from opentelemetry import trace
from sqlalchemy import func, select

from agent_quality_harness.api.schemas import (
    DatasetImport,
    EvalRunCreate,
    TargetCreate,
    VersionCreate,
)
from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import configure_tracing
from agent_quality_harness.domain.enums import TargetKind, TargetProtocol
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    Organization,
)
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.services import (
    create_eval_run,
    create_target,
    create_version,
    import_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILES = {
    "agrigraph": {
        "name": "AgriGraph Real Target",
        "dataset": PROJECT_ROOT / "datasets" / "real-agrigraph-generation-test-v2.json",
        "contract_profile": "agrigraph_v1",
        "default_endpoint": "http://127.0.0.1:8088",
        "default_auth_ref": "AQH_AGRIGRAPH_AUTH",
        "max_samples": 4,
        "timeout_seconds": 240,
    },
    "document-autoflow": {
        "name": "Document Autoflow Real Target",
        "dataset": PROJECT_ROOT / "datasets" / "real-document-autoflow-dev-v2.1.json",
        "contract_profile": "document_autoflow_v1",
        "default_endpoint": "http://127.0.0.1:8030",
        "default_auth_ref": "AQH_DOCUMENT_AUTOFLOW_AUTH",
        "max_samples": 1,
        "timeout_seconds": 600,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a candidate-only real-target characterization"
    )
    parser.add_argument("profile", choices=sorted(PROFILES))
    parser.add_argument("--endpoint")
    parser.add_argument("--auth-ref")
    parser.add_argument("--capabilities", type=Path)
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--case-limit", type=int)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


async def run(args: argparse.Namespace) -> dict[str, Any]:
    profile = PROFILES[args.profile]
    dataset_payload = DatasetImport.model_validate_json(
        await asyncio.to_thread(Path(profile["dataset"]).read_text, encoding="utf-8")
    )
    if args.case_limit:
        if args.case_limit < 1 or args.case_limit > len(dataset_payload.cases):
            raise ValueError("case limit is outside the frozen Dataset")
        limited = dataset_payload.model_dump(mode="json", by_alias=True)
        limited["name"] = f"{dataset_payload.name}-smoke-{args.case_limit}"
        limited["version"] = f"{dataset_payload.version}-smoke-{args.case_limit}"
        limited["cases"] = limited["cases"][: args.case_limit]
        limited["provenance"] = {
            **limited["provenance"],
            "characterization_subset": {
                "type": "ordered_prefix_smoke",
                "case_count": args.case_limit,
            },
        }
        dataset_payload = DatasetImport.model_validate(limited)
    capabilities: dict[str, Any] = {"contract_profile": profile["contract_profile"]}
    if args.capabilities:
        extra = json.loads(await asyncio.to_thread(args.capabilities.read_text, encoding="utf-8"))
        if not isinstance(extra, dict):
            raise ValueError("capabilities file must contain a JSON object")
        capabilities.update(extra)
    settings = get_settings()
    provider = configure_tracing(settings, settings.otel_worker_service_name)
    database = Database(settings.database_url)
    try:
        with database.session() as session:
            organization = session.scalar(select(Organization).order_by(Organization.id))
            if organization is None:
                raise RuntimeError("bootstrap an AQH organization before real characterization")
            target = session.scalar(
                select(EvaluationTarget).where(
                    EvaluationTarget.organization_id == organization.id,
                    EvaluationTarget.name == profile["name"],
                )
            )
            endpoint = args.endpoint or profile["default_endpoint"]
            auth_ref = args.auth_ref or profile["default_auth_ref"]
            if target is None:
                target = create_target(
                    session,
                    TargetCreate(
                        name=profile["name"],
                        target_kind=TargetKind.AGENT,
                        protocol=TargetProtocol.HTTP,
                        endpoint=endpoint,
                        auth_ref=auth_ref,
                        timeout_seconds=profile["timeout_seconds"],
                        capabilities=capabilities,
                    ),
                    organization.id,
                )
            else:
                target.endpoint = endpoint
                target.auth_ref = auth_ref
                target.timeout_seconds = profile["timeout_seconds"]
                target.capabilities = capabilities
                session.commit()
            provenance = dataset_payload.provenance
            version_name = (
                f"{str(provenance['source_commit'])[:12]}"
                f"{'-dirty' if provenance.get('source_dirty') else ''}"
            )
            version = session.scalar(
                select(AgentVersion).where(
                    AgentVersion.target_id == target.id,
                    AgentVersion.version == version_name,
                )
            )
            if version is None:
                version = create_version(
                    session,
                    target.id,
                    VersionCreate(
                        version=version_name,
                        model=provenance.get("selection", {}).get("model"),
                        metadata={
                            "source_commit": provenance["source_commit"],
                            "source_dirty": provenance["source_dirty"],
                            "source_tree_sha256": provenance["source_tree_sha256"],
                            "contract_profile": profile["contract_profile"],
                        },
                    ),
                    organization.id,
                )
            dataset = session.scalar(
                select(EvalDataset).where(
                    EvalDataset.organization_id == organization.id,
                    EvalDataset.name == dataset_payload.name,
                    EvalDataset.version == dataset_payload.version,
                )
            )
            if dataset is None:
                dataset, _ = import_dataset(session, dataset_payload, organization.id)
            elif dataset.provenance != dataset_payload.provenance:
                raise RuntimeError("existing Dataset provenance differs from the frozen file")
            run = create_eval_run(
                session,
                EvalRunCreate(
                    dataset_id=dataset.id,
                    candidate_version_id=version.id,
                    config={
                        "mode": "candidate_only_characterization",
                        "source_tree_sha256": provenance["source_tree_sha256"],
                    },
                ),
                organization.id,
            )
            run_id = run.id
        executor = InspectRunExecutor(
            database,
            InspectHarness(
                max_samples=args.max_samples or profile["max_samples"],
                log_dir=settings.inspect_log_dir / f"real-{args.profile}-{run_id}",
            ),
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
        )
        await executor.execute(run_id)
        provider.force_flush()
        with database.session() as session:
            run = session.get(EvalRun, run_id)
            if run is None:
                raise RuntimeError("characterization Run disappeared")
            result_count = int(
                session.scalar(select(func.count(CaseResult.id)).where(CaseResult.run_id == run_id))
                or 0
            )
            first_trace = session.scalar(
                select(CaseResult.trace_id)
                .where(CaseResult.run_id == run_id, CaseResult.trace_id.is_not(None))
                .order_by(CaseResult.id)
            )
            return {
                "profile": args.profile,
                "run_id": run_id,
                "status": run.status.value,
                "case_count": run.completed_case_count,
                "result_count": result_count,
                "trace_id": first_trace,
                "failure_reason": run.failure_reason,
            }
    finally:
        current_provider = trace.get_tracer_provider()
        force_flush = getattr(current_provider, "force_flush", None)
        if force_flush:
            force_flush()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
