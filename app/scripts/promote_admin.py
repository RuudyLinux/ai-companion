"""
Bootstraps the first super_admin — there's no UI path to create one otherwise,
since the role-management page itself requires being a super_admin already.
The change is recorded in the audit log with no actor (system action).

Usage: python scripts/promote_admin.py you@example.com
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func  # noqa: E402

from auth import revoke_all_sessions  # noqa: E402
from core import audit  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import User  # noqa: E402


def main():
    if len(sys.argv) != 2:
        print("Usage: promote_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1].strip().lower()
    db = SessionLocal()
    user = db.query(User).filter(func.lower(User.email) == email).first()

    if not user:
        print(f"No user found with email {email}")
        sys.exit(1)

    before = user.role
    user.role = "super_admin"
    revoke_all_sessions(db, user.id)
    audit.record(
        db,
        actor=None,
        action="user.role_change",
        target_type="user",
        target_id=user.id,
        before={"role": before},
        after={"role": "super_admin", "via": "scripts/promote_admin.py"},
    )
    db.commit()
    print(f"{email} is now super_admin (sign in again to pick up the new role)")


if __name__ == "__main__":
    main()
