"""Create a browser account after the database has been migrated to Phase 8."""

from __future__ import annotations

import argparse
import getpass
import sys

from manim_workbench_api.auth.errors import AuthError
from manim_workbench_api.auth.service import AuthService
from manim_workbench_api.database import create_database_engine


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Manim Workbench browser user")
    parser.add_argument("email")
    arguments = parser.parse_args()
    password = getpass.getpass("Initial password: ")
    confirmation = getpass.getpass("Confirm initial password: ")
    if password != confirmation:
        print("Passwords did not match.", file=sys.stderr)
        return 2
    if len(password) < 14:
        print("Initial password must be at least 14 characters.", file=sys.stderr)
        return 2
    try:
        principal = AuthService(create_database_engine()).create_user(arguments.email, password)
    except AuthError as error:
        print(error.message, file=sys.stderr)
        return 2
    print(f"Created {principal.email}; password change is required at first login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
