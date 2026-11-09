"""
Authentication Service

Handles user authentication, token management, and password operations.
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import (
    verify_password,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    validate_password_strength,
)
from app.core.config import settings
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
)
from app.models.user import User
from app.services.base_service import BaseService


class AuthService(BaseService[User]):
    """Service for authentication operations."""
    
    @property
    def model(self):
        return User
    
    async def authenticate(
        self,
        email: str,
        password: str,
    ) -> Tuple[User, str, str]:
        """
        Authenticate user and return tokens.
        
        Args:
            email: User email
            password: Plain text password
            
        Returns:
            Tuple of (user, access_token, refresh_token)
            
        Raises:
            AuthenticationError: If credentials are invalid
        """
        # Get user with locations
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.assigned_locations))
            .where(User.email == email.lower())
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise AuthenticationError(message="Invalid email or password")
        
        if not user.is_active:
            raise AuthenticationError(message="Account is deactivated")
        
        if not verify_password(password, user.password_hash):
            raise AuthenticationError(message="Invalid email or password")
        
        # Update last login
        user.last_login_at = datetime.utcnow()
        await self.db.commit()
        
        # Generate tokens
        access_token = create_access_token(
            user_id=user.id,
            role=user.role,
        )
        refresh_token = create_refresh_token(user_id=user.id)
        
        return user, access_token, refresh_token
    
    async def refresh_access_token(
        self,
        refresh_token: str,
    ) -> Tuple[str, str]:
        """
        Generate new tokens from refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            Tuple of (new_access_token, new_refresh_token)
            
        Raises:
            AuthenticationError: If refresh token is invalid
        """
        payload = decode_token(refresh_token)
        
        if payload.get("type") != "refresh":
            raise AuthenticationError(message="Invalid refresh token")
        
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError(message="Invalid refresh token")
        
        # Get user
        user = await self.get_by_id(user_id)
        if not user:
            raise AuthenticationError(message="User not found")
        
        if not user.is_active:
            raise AuthenticationError(message="Account is deactivated")
        
        # Generate new tokens
        access_token = create_access_token(
            user_id=user.id,
            role=user.role,
        )
        new_refresh_token = create_refresh_token(user_id=user.id)
        
        return access_token, new_refresh_token
    
    async def change_password(
        self,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> bool:
        """
        Change user password.
        
        Args:
            user_id: User ID
            current_password: Current plain text password
            new_password: New plain text password
            
        Returns:
            True if successful
            
        Raises:
            AuthenticationError: If current password is wrong
            BadRequestError: If new password doesn't meet requirements
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise AuthenticationError(message="User not found")
        
        if not verify_password(current_password, user.password_hash):
            raise AuthenticationError(message="Current password is incorrect")
        
        # Validate new password strength (full policy check)
        is_valid, error_msg = validate_password_strength(new_password)
        if not is_valid:
            raise BadRequestError(message=error_msg)
        
        # Update password
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        
        return True
    
    async def get_current_user(
        self,
        token: str,
    ) -> User:
        """
        Get current user from access token.
        
        Args:
            token: Access token
            
        Returns:
            User instance
            
        Raises:
            AuthenticationError: If token is invalid or user not found
        """
        payload = decode_token(token)
        
        if payload.get("type") != "access":
            raise AuthenticationError(message="Invalid access token")
        
        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError(message="Invalid access token")
        
        # Get user with locations
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.assigned_locations))
            .where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise AuthenticationError(message="User not found")
        
        if not user.is_active:
            raise AuthenticationError(message="Account is deactivated")
        
        return user
    
    async def register_user(
        self,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        role: str = "technician",
    ) -> User:
        """
        Register a new user.
        
        Args:
            email: User email
            password: Plain text password
            first_name: First name
            last_name: Last name
            role: User role (default: technician)
            
        Returns:
            Created user
            
        Raises:
            BadRequestError: If email already exists
        """
        # Check if email exists
        result = await self.db.execute(
            select(User).where(User.email == email.lower())
        )
        if result.scalar_one_or_none():
            raise BadRequestError(message="Email already registered")
        
        # Create user
        user = User(
            id=self.generate_id(),
            email=email.lower(),
            password_hash=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            role=role,
            is_active=True,
        )
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
