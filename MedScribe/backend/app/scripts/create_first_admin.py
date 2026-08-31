"""
One-time bootstrap script: creates the very first admin account.
Run manually, once, per environment:
    python -m app.scripts.create_first_admin

This is NOT an API endpoint deliberately -- there must be no way to
create an admin account over HTTP without already being an admin,
otherwise that's an authentication bypass. This script is the one
sanctioned exception, run directly on the server/dev machine.
"""
import asyncio
import getpass

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.enums import UserRole
from app.models.user import User


async def main() -> None:
    print("=== MedSTT: Create First Admin Account ===")
    username = input("Admin username: ").strip()
    email = input("Admin email: ").strip()
    full_name = input("Admin full name: ").strip()
    password = getpass.getpass("Admin password (min 12 chars, upper/lower/digit): ")

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(User).where(User.username == username))
        if existing.scalar_one_or_none() is not None:
            print(f"ERROR: user '{username}' already exists.")
            return

        admin = User(
            username=username,
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            role=UserRole.ADMIN,
            must_change_password=False,  # this IS their real chosen password
        )
        db.add(admin)
        await db.commit()
        print(f"Admin account '{username}' created successfully.")


if __name__ == "__main__":
    asyncio.run(main())