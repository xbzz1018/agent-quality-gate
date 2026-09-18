from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the local Document AQH evaluator")
    parser.add_argument("--document-root", type=Path, required=True)
    parser.add_argument("--username", default="aqh_evaluator")
    args = parser.parse_args()
    password = os.environ.get("DOCUMENT_AUTOFLOW_AQH_PASSWORD")
    if password is None or len(password) < 20:
        raise RuntimeError("DOCUMENT_AUTOFLOW_AQH_PASSWORD must contain at least 20 characters")

    sys.path.insert(0, str(args.document_root.resolve()))
    select = importlib.import_module("sqlalchemy").select
    User = importlib.import_module("app.db.models").User
    build_session_factory = importlib.import_module("app.db.session").build_session_factory
    hash_password = importlib.import_module("app.security").hash_password

    factory = build_session_factory()
    with factory() as session:
        user = session.scalar(select(User).where(User.username == args.username))
        if user is None:
            user = User(
                username=args.username,
                display_name="AQH Evaluator",
                role="admin",
                password_hash=hash_password(password),
            )
            session.add(user)
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            user.role = "admin"
        session.commit()
    print("Document Autoflow evaluator identity is ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
