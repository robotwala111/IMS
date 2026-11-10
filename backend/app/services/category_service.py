"""
Category Service

Handles category management operations.
"""

from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.category import Category, CategoryType
from app.models.item import Item
from app.services.base_service import BaseService


class CategoryService(BaseService[Category]):
    """Service for category management."""
    
    @property
    def model(self):
        return Category

    async def get_by_id(self, id: str) -> Optional[Category]:
        """Get category with type loaded."""
        result = await self.db.execute(
            select(Category)
            .options(selectinload(Category.category_type))
            .where(Category.id == id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_name(self, name: str) -> Optional[Category]:
        """Get category by name."""
        result = await self.db.execute(
            select(Category).where(Category.name == name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def make_type_key(name: str) -> str:
        """Create a stable lowercase key from a display name."""
        return "_".join(name.strip().lower().replace("-", " ").split())

    async def list_category_types(self, active_only: bool = False) -> List[CategoryType]:
        """Get configured category types."""
        query = select(CategoryType).order_by(CategoryType.name)
        if active_only:
            query = query.where(CategoryType.is_active == True)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_category_type_by_id(self, type_id: str) -> Optional[CategoryType]:
        """Get category type by ID."""
        result = await self.db.execute(
            select(CategoryType).where(CategoryType.id == type_id)
        )
        return result.scalar_one_or_none()

    async def get_category_type_by_key(self, key: str) -> Optional[CategoryType]:
        """Get category type by key."""
        result = await self.db.execute(
            select(CategoryType).where(CategoryType.key == key)
        )
        return result.scalar_one_or_none()

    async def create_category_type(
        self,
        name: str,
        key: Optional[str] = None,
        stock_behavior: str = "quantity",
        is_active: bool = True,
    ) -> CategoryType:
        """Create a configurable category type."""
        type_key = key or self.make_type_key(name)
        existing = await self.get_category_type_by_key(type_key)
        if existing:
            raise BadRequestError(message=f"Category type '{name}' already exists")

        category_type = CategoryType(
            id=self.generate_id(),
            key=type_key,
            name=name,
            stock_behavior=stock_behavior,
            is_active=is_active,
        )
        self.db.add(category_type)
        await self.db.commit()
        await self.db.refresh(category_type)
        return category_type

    async def get_or_create_category_type_for_category(
        self,
        name: str,
        stock_behavior: str = "quantity",
        existing_type_id: Optional[str] = None,
    ) -> CategoryType:
        """Keep the internal type record aligned with the visible category."""
        type_key = self.make_type_key(name)

        if existing_type_id:
            category_type = await self.get_category_type_by_id(existing_type_id)
            if category_type:
                category_type.name = name
                category_type.key = type_key
                category_type.stock_behavior = stock_behavior
                category_type.is_active = True
                await self.db.commit()
                await self.db.refresh(category_type)
                return category_type

        existing = await self.get_category_type_by_key(type_key)
        if existing:
            existing.stock_behavior = stock_behavior
            existing.is_active = True
            await self.db.commit()
            await self.db.refresh(existing)
            return existing

        return await self.create_category_type(
            name=name,
            key=type_key,
            stock_behavior=stock_behavior,
            is_active=True,
        )
    
    async def get_active_categories(self) -> List[Category]:
        """Get all active categories for dropdowns."""
        result = await self.db.execute(
            select(Category)
            .options(selectinload(Category.category_type))
            .where(Category.is_active == True)
            .order_by(Category.name)
        )
        return list(result.scalars().all())
    
    async def list_categories(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
        parent_id: Optional[str] = None,
        root_only: bool = False,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[List[Category], int]:
        """
        List categories with filtering.
        
        Args:
            page: Page number
            page_size: Items per page
            sort_by: Sort field
            sort_order: Sort direction
            parent_id: Filter by parent category
            root_only: Only return root categories (no parent)
            is_active: Filter by active status
            search: Search in name, description
            
        Returns:
            Tuple of (categories, total_count)
        """
        query = select(Category).options(selectinload(Category.category_type))
        
        # Apply filters
        if root_only:
            query = query.where(Category.parent_id.is_(None))
        elif parent_id:
            query = query.where(Category.parent_id == parent_id)
        
        if is_active is not None:
            query = query.where(Category.is_active == is_active)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Category.name.ilike(search_pattern),
                    Category.description.ilike(search_pattern),
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Category, sort_by):
            order_column = getattr(Category, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        categories = list(result.scalars().unique().all())
        
        return categories, total
    
    async def get_category_tree(self) -> List[Category]:
        """
        Get full category tree (root categories with nested children).
        
        Returns:
            List of root categories
        """
        result = await self.db.execute(
            select(Category)
            .where(Category.parent_id.is_(None))
            .where(Category.is_active == True)
            .order_by(Category.name)
        )
        return list(result.scalars().unique().all())
    
    async def get_categories_with_counts(self) -> List[Dict[str, Any]]:
        """
        Get all categories with their item counts.
        
        Returns:
            List of category dictionaries with item_count field
        """
        # Get all categories
        categories_result = await self.db.execute(
            select(Category).options(selectinload(Category.category_type)).order_by(Category.name)
        )
        categories = list(categories_result.scalars().all())
        
        # Count items per category
        count_result = await self.db.execute(
            select(Category.id, func.count(Item.id).label('item_count'))
            .outerjoin(Item, Category.id == Item.category_id)
            .group_by(Category.id)
        )
        
        count_map = {row[0]: row[1] for row in count_result.all()}
        
        # Build response with counts
        result = []
        for cat in categories:
            cat_dict = {
                'id': cat.id,
                'name': cat.name,
                'description': cat.description,
                'parent_id': cat.parent_id,
                'category_type_id': cat.category_type_id,
                'category_type_name': cat.category_type.name if cat.category_type else None,
                'category_type_key': cat.category_type.key if cat.category_type else None,
                'stock_behavior': cat.stock_behavior or (cat.category_type.stock_behavior if cat.category_type else None),
                'is_active': cat.is_active,
                'created_at': cat.created_at,
                'updated_at': cat.updated_at,
                'item_count': count_map.get(cat.id, 0),
            }
            result.append(cat_dict)
        
        return result
    async def create_category(
        self,
        name: str,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        is_active: bool = True,
    ) -> Category:
        """
        Create a new category.
        
        Returns:
            Created category
            
        Raises:
            BadRequestError: If name already exists
            NotFoundError: If parent category not found
        """
        # Check name uniqueness
        existing = await self.get_by_name(name)
        if existing:
            raise BadRequestError(message=f"Category '{name}' already exists")
        
        # Validate parent
        if parent_id:
            parent = await self.get_by_id(parent_id)
            if not parent:
                raise NotFoundError(resource="Parent Category", resource_id=parent_id)
        
        category = Category(
            id=self.generate_id(),
            name=name,
            description=description,
            parent_id=parent_id,
            is_active=is_active,
        )
        
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)
        
        return category
    
    async def update_category(
        self,
        category_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Category:
        """
        Update a category.
        
        Returns:
            Updated category
            
        Raises:
            NotFoundError: If category not found
            BadRequestError: If circular reference detected
        """
        category = await self.get_by_id(category_id)
        if not category:
            raise NotFoundError(resource="Category", resource_id=category_id)
        
        # Validate parent (prevent circular reference)
        if parent_id is not None:
            if parent_id == category_id:
                raise BadRequestError(message="Category cannot be its own parent")
            if parent_id:
                parent = await self.get_by_id(parent_id)
                if not parent:
                    raise NotFoundError(resource="Parent Category", resource_id=parent_id)
            category.parent_id = parent_id
        
        # Update fields
        if name is not None:
            category.name = name
        if description is not None:
            category.description = description
        if is_active is not None:
            category.is_active = is_active
        
        await self.db.commit()
        await self.db.refresh(category)
        
        return category
    
    async def delete_category(self, category_id: str) -> bool:
        """
        Soft delete a category.
        
        Returns:
            True if successful
            
        Raises:
            NotFoundError: If category not found
        """
        category = await self.get_by_id(category_id)
        if not category:
            raise NotFoundError(resource="Category", resource_id=category_id)
        
        category.is_active = False
        await self.db.commit()
        
        return True

    async def get_item_count(self, category_id: str) -> int:
        """Count items assigned to a category."""
        result = await self.db.execute(
            select(func.count(Item.id)).where(Item.category_id == category_id)
        )
        return result.scalar_one()
