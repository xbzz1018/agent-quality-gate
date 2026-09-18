from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rebuild a dedicated AQH Document project with the host MinerU runtime"
    )
    parser.add_argument("--document-root", type=Path, required=True)
    parser.add_argument("--project-id", type=uuid.UUID, required=True)
    args = parser.parse_args()

    root = args.document_root.resolve()
    sys.path.insert(0, str(root))
    from app.config import get_settings  # noqa: PLC0415
    from app.db.models import Document  # noqa: PLC0415
    from app.db.session import build_session_factory  # noqa: PLC0415
    from app.documents.factory import build_document_parser  # noqa: PLC0415
    from app.services.document_workflow import DocumentWorker  # noqa: PLC0415

    manifest = [
        json.loads(line)
        for line in (root / "evaluation" / "frozen_manifest_v2.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line
    ]
    dev_sources = {
        row["sha256"]: (root / row["file"]).resolve()
        for row in manifest
        if row.get("split") == "dev"
    }
    if len(dev_sources) != 24:
        raise ValueError("expected exactly 24 frozen Dev sources")
    for expected_hash, source in dev_sources.items():
        if not source.is_file() or _sha256(source) != expected_hash:
            raise ValueError(f"frozen source hash mismatch: {source.name}")

    factory = build_session_factory()
    parsed = 0
    failures: list[dict[str, str]] = []
    with factory() as session:
        documents = list(
            session.scalars(
                select(Document)
                .where(Document.project_id == args.project_id)
                .order_by(Document.created_at)
            )
        )
        if len(documents) != 24:
            raise ValueError("dedicated AQH project must contain exactly 24 documents")
        parser_impl = build_document_parser(get_settings())
        for document in documents:
            source = dev_sources.get(document.sha256)
            if source is None:
                raise ValueError(f"document SHA is outside the frozen Dev set: {document.id}")
            original_storage_path = document.storage_path
            document.storage_path = str(source)
            document.status = "queued"
            document.error_type = None
            document.error_detail = None
            session.commit()
            DocumentWorker(session, parser_impl).run_once(document.id)
            session.refresh(document)
            status = document.status
            error_type = document.error_type
            document.storage_path = original_storage_path
            session.commit()
            if status == "parsed":
                parsed += 1
            else:
                failures.append(
                    {
                        "document_id": str(document.id),
                        "error_type": error_type or "unknown",
                    }
                )

    print(
        json.dumps(
            {
                "project_id": str(args.project_id),
                "document_count": len(documents),
                "parsed": parsed,
                "failed": len(failures),
                "failures": failures,
            },
            sort_keys=True,
        )
    )
    return 0 if not failures and parsed == 24 else 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
