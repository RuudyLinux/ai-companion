"""
Bootstraps the first super_admin — there's no UI path to create one otherwise,
since the role-management page itself requires being a super_admin already.

Usage: venv\\Scripts\\python.exe scripts\\promote_admin.py you@example.com
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import SessionLocal
from models import User


def main():
    if len(sys.argv) != 2:
        print("Usage: promote_admin.py <email>")
        sys.exit(1)

    email = sys.argv[1]
    db = SessionLocal()
    user = db.query(User).filter(User.email == email).first()

    if not user:
        print(f"No user found with email {email}")
        sys.exit(1)

    user.role = "super_admin"
    db.commit()
    print(f"{email} is now super_admin")


if __name__ == "__main__":
    main()
