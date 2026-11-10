"""
Unlock Account Script

Removes the temporary lock on a user account.
Usage: python unlock_account.py <email>

Example:
  python unlock_account.py mkumar.amiro@gmail.com
"""

import asyncio
import sys
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.session import async_session_factory, init_db
from app.models.user import User

logger = get_logger(__name__)


async def unlock_account(email: str) -> None:
    """Unlock a user account."""
    
    # Initialize database
    await init_db()
    
    async with async_session_factory() as db:
        # Find user by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            logger.error(f"User not found: {email}")
            return
        
        # Clear lock
        user.locked_until = None
        user.failed_login_attempts = 0
        await db.commit()
        
        logger.info(f"✓ Account unlocked successfully: {email}")
        logger.info(f"  Email: {user.email}")
        logger.info(f"  Name: {user.name}")
        logger.info(f"  Role: {user.role}")


async def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: python unlock_account.py <email>")
        print()
        print("Example:")
        print("  python unlock_account.py mkumar.amiro@gmail.com")
        sys.exit(1)
    
    email = sys.argv[1]
    
    print(f"\n🔓 Unlocking account: {email}")
    print()
    
    await unlock_account(email)


if __name__ == "__main__":
    asyncio.run(main())
