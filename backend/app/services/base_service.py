"""
Base Service

Abstract base class for all services with common functionality.
"""

from abc import ABC, abstractmethod
from typing import TypeVar, Generic, Optional, List, Tuple, Any
from uuid import uuid4

from sqlalchemy import select, func, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseService(ABC, Generic[T]):
    """
    Base service class providing common CRUD operations.
    """
    
    def __init__(self, db: AsyncSession):
        """Initialize service with database session."""
        self.db = db
    
    @property
    @abstractmethod
    def model(self) -> type:
        """Return the SQLAlchemy model class."""
        pass
    
    def generate_id(self) -> str:
        """Generate a new UUID string."""
        return str(uuid4())
    
    async def get_by_id(self, id: str) -> Optional[T]:
        """Get a record by ID."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()
    
    async def exists(self, id: str) -> bool:
        """Check if a record exists by ID."""
        result = await self.db.execute(
            select(func.count(self.model.id)).where(self.model.id == id)
        )
        return result.scalar_one() > 0
    
    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        filters: Optional[dict] = None,
    ) -> Tuple[List[T], int]:
        """
        Get paginated list of records.
        
        Returns:
            Tuple of (items, total_count)
        """
        query = select(self.model)
        
        # Apply filters
        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(self.model, key):
                    query = query.where(getattr(self.model, key) == value)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(self.model, sort_by):
            order_column = getattr(self.model, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(desc(order_column))
            else:
                query = query.order_by(asc(order_column))
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        items = list(result.scalars().all())
        
        return items, total
    
    async def create(self, **kwargs) -> T:
        """Create a new record."""
        if "id" not in kwargs:
            kwargs["id"] = self.generate_id()
        
        instance = self.model(**kwargs)
        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance
    
    async def update(self, id: str, **kwargs) -> Optional[T]:
        """Update an existing record."""
        instance = await self.get_by_id(id)
        if not instance:
            return None
        
        for key, value in kwargs.items():
            if value is not None and hasattr(instance, key):
                setattr(instance, key, value)
        
        await self.db.commit()
        await self.db.refresh(instance)
        return instance
    
    async def delete(self, id: str) -> bool:
        """Delete a record by ID."""
        instance = await self.get_by_id(id)
        if not instance:
            return False
        
        await self.db.delete(instance)
        await self.db.commit()
        return True
    
    async def soft_delete(self, id: str) -> bool:
        """Soft delete a record by setting is_active to False."""
        instance = await self.get_by_id(id)
        if not instance:
            return False
        
        if hasattr(instance, "is_active"):
            instance.is_active = False
            await self.db.commit()
            return True
        
        return False
