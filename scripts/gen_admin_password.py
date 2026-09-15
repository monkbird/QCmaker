"""Generate a bootstrap PBKDF2 password hash without printing the password."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


if str(_project_root()) not in sys.path:
    sys.path.insert(0, str(_project_root()))

from backend.app.core.admin_security import PASSWORD_ITERATIONS, hash_password  # noqa: E402


def generate_admin_password_hash(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    """Return a policy-compliant hash suitable for ADMIN_BOOTSTRAP_PASSWORD_HASH."""

    return hash_password(password, iterations=iterations)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成 QCmaker 管理员 bootstrap PBKDF2 哈希")
    parser.add_argument("--iterations", type=int, default=PASSWORD_ITERATIONS, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    password = getpass.getpass("管理员密码（输入不回显）：")
    confirmation = getpass.getpass("再次输入管理员密码（输入不回显）：")
    if password != confirmation:
        parser.error("两次密码输入不一致")
    try:
        print(generate_admin_password_hash(password, iterations=args.iterations))
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
