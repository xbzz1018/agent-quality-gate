import argparse
import uuid
from pathlib import Path

from app.db.models import DocumentTemplate, Project
from app.db.session import build_session_factory
from sqlalchemy import select


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove one AQH-owned Document Autoflow fixture")
    parser.add_argument("project_id")
    parser.add_argument("template_name")
    parser.add_argument("--document-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.document_root.resolve()
    runtime = (root / "runtime").resolve()
    paths: list[Path] = []
    with build_session_factory()() as session:
        project = session.get(Project, uuid.UUID(args.project_id))
        if project is None or not project.name.startswith("AQH characterization "):
            raise RuntimeError("refusing to delete a non-AQH project")
        paths = [Path(item.storage_path) for item in project.documents]
        document_count = len(paths)
        session.delete(project)
        template = session.scalar(
            select(DocumentTemplate).where(DocumentTemplate.name == args.template_name)
        )
        if template is not None:
            session.delete(template)
        session.commit()
    removed_files = 0
    for path in paths:
        resolved = (path if path.is_absolute() else root / path).resolve()
        if not resolved.is_relative_to(runtime):
            raise RuntimeError(f"refusing to remove file outside runtime: {resolved}")
        if resolved.is_file():
            resolved.unlink()
            removed_files += 1
    print(f"removed_project={args.project_id} documents={document_count} files={removed_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
