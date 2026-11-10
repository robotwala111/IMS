"""
Category Management Endpoints

CRUD operations for item categories.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_admin,
    require_admin_or_ho_manager,
)
from app.core.exceptions import NotFoundError, ConflictError, BadRequestError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.category import (
    CategoryTypeCreate,
    CategoryTypeUpdate,
    CategoryTypeResponse,
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
    CategoryListResponse,
    CategorySummary,
    CategoryWithItemCount,
)
from app.services.category_service import CategoryService
from app.services.audit_service import AuditService
from app.services.permanent_delete_service import PermanentDeleteService

logger = get_logger(__name__)
router = APIRouter()


@router.get("/types", response_model=List[CategoryTypeResponse])
async def list_category_types(
    current_user: CurrentUser,
    db: DB,
    active_only: bool = Query(False),
) -> List[CategoryTypeResponse]:
    """
    List configured category types.
    """
    category_service = CategoryService(db)
    types = await category_service.list_category_types(active_only=active_only)
    return [CategoryTypeResponse.model_validate(type_) for type_ in types]


@router.post("/types", response_model=CategoryTypeResponse, status_code=201)
async def create_category_type(
    request: CategoryTypeCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> CategoryTypeResponse:
    """
    Create a new category type (Manager or Admin).
    """
    category_service = CategoryService(db)
    category_type = await category_service.create_category_type(**request.model_dump())
    return CategoryTypeResponse.model_validate(category_type)


@router.patch("/types/{type_id}", response_model=CategoryTypeResponse)
async def update_category_type(
    type_id: str,
    request: CategoryTypeUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> CategoryTypeResponse:
    """
    Update a category type (Manager or Admin).
    """
    category_service = CategoryService(db)
    category_type = await category_service.get_category_type_by_id(type_id)
    if not category_type:
        raise NotFoundError(resource="Category Type", resource_id=type_id)

    update_data = request.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None and hasattr(category_type, key):
            setattr(category_type, key, value)

    await db.commit()
    await db.refresh(category_type)
    return CategoryTypeResponse.model_validate(category_type)


@router.get("", response_model=CategoryListResponse)
async def list_categories(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    is_active: Optional[bool] = Query(None),
    category_type_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> CategoryListResponse:
    """
    List all categories with item counts.
    """
    category_service = CategoryService(db)
    
    # Get categories with counts
    categories_with_counts = await category_service.get_categories_with_counts()
    
    # Apply search filter if provided
    if search:
        search_pattern = search.lower()
        categories_with_counts = [
            cat for cat in categories_with_counts
            if search_pattern in cat['name'].lower() 
            or (cat.get('description') and search_pattern in cat['description'].lower())
        ]
    
    # Apply active filter if provided
    if is_active is not None:
        categories_with_counts = [
            cat for cat in categories_with_counts
            if cat['is_active'] == is_active
        ]

    if category_type_id:
        categories_with_counts = [
            cat for cat in categories_with_counts
            if cat.get('category_type_id') == category_type_id
        ]
    
    # Apply sorting
    sort_by = pagination.get("sort_by", "name")
    sort_order = pagination.get("sort_order", "asc")
    
    reverse = sort_order.lower() == "desc"
    if sort_by in categories_with_counts[0] if categories_with_counts else {}:
        categories_with_counts.sort(
            key=lambda x: x.get(sort_by, ""),
            reverse=reverse
        )
    
    # Get total count
    total = len(categories_with_counts)
    
    # Apply pagination
    page = pagination.get("page", 1)
    page_size = pagination.get("page_size", 20)
    offset = (page - 1) * page_size
    paginated_categories = categories_with_counts[offset:offset + page_size]
    
    pages = (total + page_size - 1) // page_size
    
    return CategoryListResponse(
        items=[CategoryResponse.model_validate(cat) for cat in paginated_categories],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/summary", response_model=List[CategorySummary])
async def get_category_summary(
    current_user: CurrentUser,
    db: DB,
) -> List[CategorySummary]:
    """
    Get a brief list of categories for dropdowns.
    """
    category_service = CategoryService(db)
    categories = await category_service.get_active_categories()
    
    return [CategorySummary.model_validate(cat) for cat in categories]


@router.get("/with-counts", response_model=List[CategoryWithItemCount])
async def get_categories_with_item_counts(
    current_user: CurrentUser,
    db: DB,
) -> List[CategoryWithItemCount]:
    """
    Get categories with item counts.
    """
    category_service = CategoryService(db)
    categories = await category_service.get_categories_with_counts()
    
    return categories


@router.get("/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    current_user: CurrentUser,
    db: DB,
) -> CategoryResponse:
    """
    Get a specific category by ID.
    """
    category_service = CategoryService(db)
    category = await category_service.get_by_id(category_id)
    
    if not category:
        raise NotFoundError(resource="Category", resource_id=category_id)
    
    return CategoryResponse.model_validate(category)


@router.post("", response_model=CategoryResponse, status_code=201)
async def create_category(
    request: CategoryCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> CategoryResponse:
    """
    Create a new category (Manager or Admin).
    """
    category_service = CategoryService(db)
    audit_service = AuditService(db)
    
    # Check for existing name
    existing = await category_service.get_by_name(request.name)
    if existing:
        raise ConflictError(message=f"Category '{request.name}' already exists")
    
    request_data = request.model_dump()
    if request.category_type_id:
        category_type = await category_service.get_category_type_by_id(request.category_type_id)
        if not category_type:
            raise NotFoundError(resource="Category Type", resource_id=request.category_type_id)
        if not category_type.is_active:
            raise BadRequestError(message="Selected category type is inactive")
        request_data["stock_behavior"] = request.stock_behavior or category_type.stock_behavior
    else:
        request_data["stock_behavior"] = request.stock_behavior or "quantity"

    # Create category
    category = await category_service.create(**request_data)
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="category",
        resource_id=category.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"name": category.name},
    )
    
    category = await category_service.get_by_id(category.id)
    return CategoryResponse.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: str,
    request: CategoryUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> CategoryResponse:
    """
    Update a category (Manager or Admin).
    """
    category_service = CategoryService(db)
    audit_service = AuditService(db)
    
    # Get existing category
    category = await category_service.get_by_id(category_id)
    if not category:
        raise NotFoundError(resource="Category", resource_id=category_id)
    
    old_value = {
        "name": category.name,
        "is_active": category.is_active,
        "stock_behavior": category.stock_behavior,
    }
    
    # Check name uniqueness if changing
    if request.name and request.name != category.name:
        existing = await category_service.get_by_name(request.name)
        if existing:
            raise ConflictError(message=f"Category '{request.name}' already exists")
    
    update_data = request.model_dump(exclude_unset=True)
    confirm_type_change = bool(update_data.pop("confirm_type_change", False))
    category_type_id = update_data.get("category_type_id")
    if category_type_id:
        category_type = await category_service.get_category_type_by_id(category_type_id)
        if not category_type:
            raise NotFoundError(resource="Category Type", resource_id=category_type_id)
        if not category_type.is_active:
            raise BadRequestError(message="Selected category type is inactive")
        update_data["stock_behavior"] = update_data.get("stock_behavior") or category_type.stock_behavior
    stock_behavior = update_data.get("stock_behavior")

    if stock_behavior and stock_behavior != (category.stock_behavior or "quantity"):
        item_count = await category_service.get_item_count(category_id)
        if item_count > 0 and not confirm_type_change:
            raise ConflictError(
                message=(
                    f"This category has {item_count} item(s). Confirm the stock handling change "
                    "after reviewing existing stock and serial number rules."
                )
            )

    # Update category
    if update_data:
        category = await category_service.update(category_id, **update_data)
    
    # Audit log
    new_value = {
        "name": category.name,
        "is_active": category.is_active,
        "stock_behavior": category.stock_behavior,
    }
    await audit_service.log_action(
        action="update",
        resource_type="category",
        resource_id=category.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )
    
    category = await category_service.get_by_id(category.id)
    return CategoryResponse.model_validate(category)


@router.delete("/{category_id}", response_model=MessageResponse)
async def delete_category(
    category_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> MessageResponse:
    """
    Delete (deactivate) a category (Admin or General Manager).
    """
    category_service = CategoryService(db)
    audit_service = AuditService(db)
    
    category = await category_service.get_by_id(category_id)
    if not category:
        raise NotFoundError(resource="Category", resource_id=category_id)
    
    # Check if category has items
    item_count = await category_service.get_item_count(category_id)
    if item_count > 0:
        raise ConflictError(
            message=f"Cannot delete category with {item_count} items. Reassign items first."
        )
    
    # Soft delete
    await category_service.update(category_id, is_active=False)
    
    # Audit log
    await audit_service.log_action(
        action="delete",
        resource_type="category",
        resource_id=category.id,
        user_id=current_user.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
    )
    
    return MessageResponse(message=f"Category '{category.name}' has been deactivated")


@router.delete("/{category_id}/permanent", response_model=MessageResponse)
async def permanently_delete_category(
    category_id: str,
    current_user: CurrentUser,
    db: DB,
    force: bool = Query(False),
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unreferenced category (Admin only)."""
    name = await PermanentDeleteService(db).delete(
        "category", category_id, current_user, force_category_items=force
    )
    return MessageResponse(message=f"Category {name} permanently deleted")
