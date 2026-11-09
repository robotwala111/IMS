"""
User Service

Handles user management operations.
"""

from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.core.security import hash_password
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.models.location import Location
from app.services.base_service import BaseService


class UserService(BaseService[User]):
    """Service for user management."""
    
    @property
    def model(self):
        return User
    
    async def create(
        self,
        email: str,
        name: str,
        password: str,
        role: str = "location_manager",
        assigned_location_ids: Optional[List[str]] = None,
        phone: Optional[str] = None,
        department: Optional[str] = None,
        is_active: bool = True,
        **kwargs
    ) -> User:
        """
        Create a new user with proper password hashing and location assignment.
        
        Args:
            email: User email
            name: User full name
            password: Plain text password to be hashed
            role: User role (admin, manager, technician)
            assigned_location_ids: List of location IDs to assign to user
            phone: Optional phone number
            department: Optional department
            is_active: Whether user is active
            
        Returns:
            Created user
        """
        # Hash password
        password_hash = hash_password(password)
        
        # Create user instance
        user_id = self.generate_id()
        user = User(
            id=user_id,
            email=email.lower(),
            name=name,
            password_hash=password_hash,
            role=role,
            is_active=is_active,
            phone=phone,
            department=department,
        )
        
        # Add user to session first
        self.db.add(user)
        await self.db.flush()  # Flush to get the user into the session
        
        # Assign locations if provided
        # Initialize the relationship as empty to prevent lazy-load in async context
        set_committed_value(user, 'assigned_locations', [])
        if assigned_location_ids:
            result = await self.db.execute(
                select(Location).where(Location.id.in_(assigned_location_ids))
            )
            locations = list(result.scalars().all())
            user.assigned_locations = locations
        
        # Commit all changes
        await self.db.commit()
        
        # Reload user with relationships
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.assigned_locations))
            .where(User.id == user_id)
        )
        user = result.scalar_one()
        
        return user
    
    async def get_by_id(self, id: str) -> Optional[User]:
        """Get user with assigned locations."""
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.assigned_locations))
            .where(User.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        result = await self.db.execute(
            select(User)
            .options(selectinload(User.assigned_locations))
            .where(User.email == email.lower())
        )
        return result.scalar_one_or_none()
    
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        role: Optional[str] = None,
        location_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[User], int]:
        """
        List users with filtering.
        
        Returns:
            Tuple of (users, total_count)
        """
        query = select(User).options(selectinload(User.assigned_locations))
        
        # Apply filters
        if role:
            query = query.where(User.role == role)
        
        if is_active is not None:
            query = query.where(User.is_active == is_active)
        
        if location_id:
            query = query.where(
                User.assigned_locations.any(Location.id == location_id)
            )
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    User.name.ilike(search_pattern),
                    User.email.ilike(search_pattern),
                    User.department.ilike(search_pattern),
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(User, sort_by):
            order_column = getattr(User, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        users = list(result.scalars().unique().all())
        
        return users, total
    
    async def create_user(
        self,
        email: str,
        password: str,
        name: str,
        role: str = "location_manager",
        phone: Optional[str] = None,
        department: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> User:
        """
        Create a new user.
        
        Args:
            email: User email
            password: Plain text password
            name: Full name
            role: User role
            phone: Optional phone number
            department: Optional department
            location_ids: Optional list of location IDs to assign
            
        Returns:
            Created user
            
        Raises:
            BadRequestError: If email already exists
        """
        # Check email uniqueness
        existing = await self.get_by_email(email)
        if existing:
            raise BadRequestError(message="Email already registered")
        
        # Get locations
        locations = []
        if location_ids:
            result = await self.db.execute(
                select(Location).where(Location.id.in_(location_ids))
            )
            locations = list(result.scalars().all())
        
        # Create user
        user = User(
            id=self.generate_id(),
            email=email.lower(),
            password_hash=hash_password(password),
            name=name,
            role=role,
            phone=phone,
            department=department,
            is_active=True,
            assigned_locations=locations,
        )
        
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
    
    async def update_user(
        self,
        user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        role: Optional[str] = None,
        phone: Optional[str] = None,
        department: Optional[str] = None,
        is_active: Optional[bool] = None,
        location_ids: Optional[List[str]] = None,
    ) -> User:
        """
        Update a user.
        
        Returns:
            Updated user
            
        Raises:
            NotFoundError: If user not found
            BadRequestError: If email conflict
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise NotFoundError(resource="User", resource_id=user_id)
        
        # Check email uniqueness
        if email and email.lower() != user.email:
            existing = await self.get_by_email(email)
            if existing:
                raise BadRequestError(message="Email already registered")
            user.email = email.lower()
        
        # Update fields
        if name is not None:
            user.name = name
        if role is not None:
            user.role = role
        if phone is not None:
            user.phone = phone
        if department is not None:
            user.department = department
        if is_active is not None:
            user.is_active = is_active
        
        # Update locations
        if location_ids is not None:
            result = await self.db.execute(
                select(Location).where(Location.id.in_(location_ids))
            )
            user.assigned_locations = list(result.scalars().all())
        
        await self.db.commit()
        await self.db.refresh(user)
        
        return user
    
    async def delete_user(self, user_id: str) -> bool:
        """
        Soft delete a user by deactivating them.
        
        Returns:
            True if successful
            
        Raises:
            NotFoundError: If user not found
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise NotFoundError(resource="User", resource_id=user_id)
        
        user.is_active = False
        await self.db.commit()
        
        return True
    
    async def reset_password(
        self,
        user_id: str,
        new_password: str,
    ) -> bool:
        """
        Reset user password (admin function).
        
        Returns:
            True if successful
            
        Raises:
            NotFoundError: If user not found
        """
        user = await self.get_by_id(user_id)
        if not user:
            raise NotFoundError(resource="User", resource_id=user_id)
        
        user.password_hash = hash_password(new_password)
        await self.db.commit()
        
        return True
    
    async def reset_failed_attempts(self, user_id: str) -> bool:
        """
        Reset failed login attempts for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful
        """
        user = await self.get_by_id(user_id)
        if not user:
            return False
        
        user.failed_login_attempts = 0
        user.locked_until = None
        await self.db.commit()
        
        return True
    
    async def increment_failed_attempts(self, user_id: str) -> int:
        """
        Increment failed login attempts for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            New number of failed attempts
        """
        user = await self.get_by_id(user_id)
        if not user:
            return 0
        
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        await self.db.commit()
        
        return user.failed_login_attempts
    
    async def update_last_login(self, user_id: str) -> bool:
        """
        Update last login timestamp for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            True if successful
        """
        user = await self.get_by_id(user_id)
        if not user:
            return False
        
        user.last_login_at = datetime.utcnow().isoformat()
        await self.db.commit()
        
        return True

    async def lock_account(self, user_id: str, duration_minutes: int) -> bool:
        """
        Lock a user account for a specified duration.
        
        Args:
            user_id: User ID
            duration_minutes: Number of minutes to lock the account
            
        Returns:
            True if successful
        """
        from datetime import timedelta, timezone

        user = await self.get_by_id(user_id)
        if not user:
            return False

        lock_until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
        user.locked_until = lock_until.isoformat()
        await self.db.commit()

        return True

    async def update_password(self, user_id: str, password_hash: str) -> bool:
        """
        Update a user's password hash.
        
        Args:
            user_id: User ID
            password_hash: New bcrypt password hash
            
        Returns:
            True if successful
        """
        user = await self.get_by_id(user_id)
        if not user:
            return False

        user.password_hash = password_hash
        await self.db.commit()

        return True
