"""
Category Schemas

Pydantic models for category CRUD operations.
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CategoryTypeBase(BaseModel):
    """Base category type fields."""

    name: str = Field(..., min_length=2, max_length=100)
    key: Optional[str] = Field(None, min_length=2, max_length=50, pattern=r"^[a-z0-9_]+$")
    stock_behavior: str = Field("quantity", pattern=r"^(quantity|serialized)$")


class CategoryTypeCreate(CategoryTypeBase):
    """Category type creation schema."""

    is_active: bool = True


class CategoryTypeUpdate(BaseModel):
    """Category type update schema."""

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    stock_behavior: Optional[str] = Field(None, pattern=r"^(quantity|serialized)$")
    is_active: Optional[bool] = None


class CategoryTypeResponse(BaseModel):
    """Category type response schema."""

    id: str
    key: str
    name: str
    stock_behavior: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CategoryBase(BaseModel):
    """Base category fields."""
    
    name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    parent_id: Optional[str] = None
    category_type_id: Optional[str] = None
    stock_behavior: Optional[str] = Field(None, pattern=r"^(quantity|serialized)$")


class CategoryCreate(CategoryBase):
    """Category creation schema."""
    
    is_active: bool = True


class CategoryUpdate(BaseModel):
    """Category update schema (all fields optional)."""
    
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    parent_id: Optional[str] = None
    category_type_id: Optional[str] = None
    stock_behavior: Optional[str] = Field(None, pattern=r"^(quantity|serialized)$")
    is_active: Optional[bool] = None
    confirm_type_change: bool = False


class CategoryResponse(BaseModel):
    """Category response schema."""
    
    id: str
    name: str
    description: Optional[str]
    parent_id: Optional[str]
    category_type_id: Optional[str] = None
    category_type_name: Optional[str] = None
    category_type_key: Optional[str] = None
    stock_behavior: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    item_count: int = 0
    
    model_config = ConfigDict(from_attributes=True)


class CategoryListResponse(BaseModel):
    """Paginated category list response."""
    
    items: List[CategoryResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CategorySummary(BaseModel):
    """Brief category info for dropdowns."""
    
    id: str
    name: str
    category_type_id: Optional[str] = None
    category_type_name: Optional[str] = None
    category_type_key: Optional[str] = None
    stock_behavior: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)


class CategoryWithItemCount(CategoryResponse):
    """Category with item count."""
    
    item_count: int = 0
