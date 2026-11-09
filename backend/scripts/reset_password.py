"""
Reset Password Script

Allows resetting a user's password by email address.
Usage: python reset_password.py <email> <new_password>

Example:
  python reset_password.py mkumar.amiro@gmail.com MyNewPassword123!
"""

import asyncio
import sys
from sqlalchemy import select

from app.core.security import hash_password
from app.core.logging import get_logger
from app.db.session import async_session_factory, init_db
from app.models.user import User

logger = get_logger(__name__)


async def reset_password(email: str, new_password: str) -> None:
    """Reset a user's password."""
    
    # Initialize database
    await init_db()
    
    async with async_session_factory() as db:
        # Find user by email
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        
        if not user:
            logger.error(f"User not found: {email}")
            return
        
        # Update password
        user.password_hash = hash_password(new_password)
        await db.commit()
        
        logger.info(f"✓ Password reset successfully for: {email}")
        logger.info(f"  Email: {user.email}")
        logger.info(f"  Name: {user.name}")
        logger.info(f"  Role: {user.role}")


async def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: python reset_password.py <email> <new_password>")
        print()
        print("Examples:")
        print("  python reset_password.py mkumar.amiro@gmail.com MyNewPassword123!")
        print("  python reset_password.py user@example.com SecurePass456!")
        sys.exit(1)
    
    email = sys.argv[1]
    new_password = sys.argv[2]
    
    # Validate password length
    if len(new_password) < 8:
        print("Error: Password must be at least 8 characters long")
        sys.exit(1)
    
    print(f"\n🔑 Resetting password for: {email}")
    print(f"   New password: {'*' * len(new_password)}")
    print()
    
    await reset_password(email, new_password)


if __name__ == "__main__":
    asyncio.run(main())
