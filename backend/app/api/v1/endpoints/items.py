"""
Item Management Endpoints

CRUD operations for inventory items.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_admin,
    require_manager_or_admin,
)
from app.core.exceptions import NotFoundError, ConflictError, AuthorizationError, BadRequestError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.item import (
    ItemCreate,
    ItemUpdate,
    ItemResponse,
    ItemListResponse,
    ItemSummary,
    ItemAttributeCreate,
    ItemAttributeResponse,
    ItemSearchParams,
)
from app.services.item_service import ItemService
from app.services.audit_service import AuditService
from app.services.stock_service import StockService
from app.services.category_service import CategoryService
from app.services.permanent_delete_service import PermanentDeleteService

logger = get_logger(__name__)
router = APIRouter()
SERIALIZED_PRODUCT_TYPES = {"equipment", "instrument"}


def inventory_type_key(value: Optional[str]) -> str:
    """Normalize visible type/category names into inventory type keys."""
    key = "_".join((value or "").strip().lower().replace("-", " ").split())
    aliases = {
        "equipments": "equipment",
        "instruments": "instrument",
        "consumables": "consumable",
        "accessories": "accessory",
    }
    return aliases.get(key, key)


@router.get("", response_model=ItemListResponse)
async def list_items(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    category_id: Optional[str] = Query(None),
    is_serialized: Optional[bool] = Query(None),
    is_lot_tracked: Optional[bool] = Query(None),
    requires_calibration: Optional[bool] = Query(None),
    hazardous: Optional[bool] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
) -> ItemListResponse:
    """
    List all items with filtering.
    """
    item_service = ItemService(db)
    category_service = CategoryService(db)
    
    search_params = ItemSearchParams(
        search=search,
        category_id=category_id,
        is_serialized=is_serialized,
        is_lot_tracked=is_lot_tracked,
        requires_calibration=requires_calibration,
        hazardous=hazardous,
        is_active=is_active,
    )
    
    items, total = await item_service.list_items(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        category_id=category_id,
        is_serialized=is_serialized,
        is_active=is_active,
        search=search,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return ItemListResponse(
        items=[ItemResponse.model_validate(item) for item in items],
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/summary", response_model=List[ItemSummary])
async def get_item_summary(
    current_user: CurrentUser,
    db: DB,
    category_id: Optional[str] = Query(None),
) -> List[ItemSummary]:
    """
    Get a brief list of items for dropdowns.
    """
    item_service = ItemService(db)
    items = await item_service.get_active_items(category_id=category_id)
    
    return [ItemSummary.model_validate(item) for item in items]


@router.get("/duplicate-suggestions", response_model=List[ItemResponse])
async def get_duplicate_suggestions(
    current_user: CurrentUser,
    db: DB,
    name: str = Query(..., min_length=2),
    manufacturer: Optional[str] = Query(None),
    model: Optional[str] = Query(None),
    exclude_item_id: Optional[str] = Query(None),
) -> List[ItemResponse]:
    """Warn clients about probable duplicate item-master records."""
    matches = await ItemService(db).find_probable_duplicates(
        name=name,
        manufacturer=manufacturer,
        model=model,
        exclude_item_id=exclude_item_id,
    )
    return [ItemResponse.model_validate(item) for item in matches]


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: str,
    current_user: CurrentUser,
    db: DB,
) -> ItemResponse:
    """
    Get a specific item by ID.
    """
    item_service = ItemService(db)
    item = await item_service.get_by_id(item_id)
    
    if not item:
        raise NotFoundError(resource="Item", resource_id=item_id)
    
    return ItemResponse.model_validate(item)


@router.get("/sku/{sku}", response_model=ItemResponse)
async def get_item_by_sku(
    sku: str,
    current_user: CurrentUser,
    db: DB,
) -> ItemResponse:
    """
    Get a specific item by SKU.
    """
    item_service = ItemService(db)
    item = await item_service.get_by_sku(sku)
    
    if not item:
        raise NotFoundError(resource="Item", resource_id=sku)
    
    return ItemResponse.model_validate(item)


@router.post("", response_model=ItemResponse, status_code=201)
async def create_item(
    request: ItemCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> ItemResponse:
    """
    Create a new item (Manager or Admin).
    """
    item_service = ItemService(db)
    audit_service = AuditService(db)
    stock_service = StockService(db)
    category_service = CategoryService(db)
    
    # Check for existing SKU
    normalized_sku = request.sku.strip().upper() if request.sku else None
    existing = await item_service.get_by_sku(normalized_sku)
    if normalized_sku and existing:
        raise ConflictError(message=f"Item with SKU {request.sku} already exists")
    
    # Extract initial stock fields before creating item
    initial_location_id = request.initial_location_id
    initial_quantity = request.initial_quantity
    initial_reorder_point = request.initial_reorder_point or 0
    category = await category_service.get_by_id(request.category_id)
    if not category:
        raise NotFoundError(resource="Category", resource_id=request.category_id)

    stock_behavior = category.stock_behavior or "quantity"
    category_type_key = inventory_type_key(category.category_type_key or category.name)
    item_payload = request.model_dump(exclude={'initial_location_id', 'initial_quantity', 'initial_reorder_point'})
    item_payload["sku"] = normalized_sku

    if category_type_key:
        item_payload["asset_type"] = category_type_key

    if stock_behavior == "serialized":
        if category_type_key not in SERIALIZED_PRODUCT_TYPES:
            raise BadRequestError(
                message="Products can only use Equipment or Instrument categories."
            )
        item_payload["is_serialized"] = True
        initial_quantity = 1 if initial_location_id else None
        if request.initial_quantity not in (None, 0, 1):
            raise BadRequestError(
                message="Equipment and instruments are serialized; stock quantity must be one per serial number."
            )
    else:
        item_payload["is_serialized"] = False

    if initial_quantity is not None and initial_quantity > 0 and not initial_location_id:
        raise BadRequestError(message="Initial location is required when initial quantity is greater than zero")
    
    # Check location access for initial stock placement
    if initial_location_id and not current_user.has_location_access(initial_location_id):
        raise AuthorizationError(message="You do not have access to this location")
    
    # Create item (exclude stock fields from model dump)
    item = await item_service.create(**item_payload)
    
    # Create initial stock row when a location is provided, even when opening quantity is zero.
    if initial_location_id and initial_quantity is not None:
        await stock_service.create(
            item_id=item.id,
            location_id=initial_location_id,
            quantity_on_hand=initial_quantity,
            quantity_reserved=0,
            reorder_point=initial_reorder_point,
            reorder_quantity=0,
        )
    
    # Reload with relationships to avoid lazy loading issues
    item = await item_service.get_by_id(item.id)
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="item",
        resource_id=item.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"sku": item.sku, "name": item.name, "location_id": initial_location_id, "quantity": initial_quantity},
    )
    
    item = await item_service.get_by_id(item.id)
    return ItemResponse.model_validate(item)


@router.patch("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: str,
    request: ItemUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> ItemResponse:
    """
    Update an item (Manager or Admin).
    """
    item_service = ItemService(db)
    category_service = CategoryService(db)
    audit_service = AuditService(db)
    
    # Get existing item
    item = await item_service.get_by_id(item_id)
    if not item:
        raise NotFoundError(resource="Item", resource_id=item_id)
    
    old_value = {"sku": item.sku, "name": item.name, "is_active": item.is_active}
    
    # Update item
    update_data = request.model_dump(exclude_unset=True)
    sku_was_provided = "sku" in update_data
    if sku_was_provided:
        raw_sku = update_data.pop("sku")
        normalized_sku = raw_sku.strip().upper() if raw_sku else None
        if normalized_sku and normalized_sku != item.sku:
            existing = await item_service.get_by_sku(normalized_sku)
            if existing:
                raise ConflictError(message=f"Item with SKU {raw_sku} already exists")
        item.sku = normalized_sku
    new_category_id = update_data.get("category_id")
    if new_category_id:
        category = await category_service.get_by_id(new_category_id)
        if not category:
            raise NotFoundError(resource="Category", resource_id=new_category_id)
        category_type_key = inventory_type_key(category.category_type_key or category.name)
        if category_type_key:
            update_data["asset_type"] = category_type_key
        if category.stock_behavior == "serialized":
            if category_type_key not in SERIALIZED_PRODUCT_TYPES:
                raise BadRequestError(
                    message="Products can only use Equipment or Instrument categories."
                )
            update_data["is_serialized"] = True
        else:
            if item.is_serialized:
                raise BadRequestError(
                    message="Serialized products cannot be moved to quantity-based categories. Create a Stock Levels item instead."
                )
            update_data["is_serialized"] = False

    protected_definition_changed = any((
        new_category_id is not None and new_category_id != item.category_id,
        "is_serialized" in update_data and update_data["is_serialized"] != item.is_serialized,
        "is_lot_tracked" in update_data and update_data["is_lot_tracked"] != item.is_lot_tracked,
        "unit_of_measure" in update_data
        and (update_data["unit_of_measure"] or "").strip().upper()
        != item.unit_of_measure.strip().upper(),
    ))
    if protected_definition_changed and await item_service.has_business_history(item_id):
        raise ConflictError(
            message="Cannot change category, tracking behavior, or unit of measure after inventory history exists. Create a new product revision instead."
        )

    if update_data:
        await item_service.update(item_id, **update_data)
    elif sku_was_provided:
        await db.commit()
    
    # Reload with relationships to avoid lazy loading issues
    item = await item_service.get_by_id(item_id)
    
    # Audit log
    new_value = {"sku": item.sku, "name": item.name, "is_active": item.is_active}
    await audit_service.log_action(
        action="update",
        resource_type="item",
        resource_id=item.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )
    
    item = await item_service.get_by_id(item.id)
    return ItemResponse.model_validate(item)


@router.delete("/{item_id}", response_model=MessageResponse)
async def delete_item(
    item_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Deactivate a product (General Manager or Admin).
    """
    item_service = ItemService(db)
    audit_service = AuditService(db)
    
    item = await item_service.get_by_id(item_id)
    if not item:
        raise NotFoundError(resource="Item", resource_id=item_id)

    blockers = await item_service.get_deactivation_blockers(item_id)
    if blockers:
        raise ConflictError(
            message="Cannot deactivate product with " + ", ".join(blockers) + "."
        )
    
    await item_service.update(item_id, is_active=False)
    
    # Audit log
    await audit_service.log_action(
        action="deactivate",
        resource_type="item",
        resource_id=item.id,
        user_id=current_user.id,
        old_value={"is_active": item.is_active},
        new_value={"is_active": False},
    )
    
    return MessageResponse(message=f"Item {item.sku or item.name} has been deactivated")


@router.delete("/{item_id}/permanent", response_model=MessageResponse)
async def permanently_delete_item(
    item_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unreferenced product (Admin only)."""
    name = await PermanentDeleteService(db).delete("item", item_id, current_user)
    return MessageResponse(message=f"Product {name} permanently deleted")


# Item Attributes

@router.get("/{item_id}/attributes", response_model=List[ItemAttributeResponse])
async def get_item_attributes(
    item_id: str,
    current_user: CurrentUser,
    db: DB,
) -> List[ItemAttributeResponse]:
    """
    Get all attributes for an item.
    """
    item_service = ItemService(db)
    
    item = await item_service.get_by_id(item_id)
    if not item:
        raise NotFoundError(resource="Item", resource_id=item_id)
    
    return [ItemAttributeResponse.model_validate(attr) for attr in item.attributes]


@router.post("/{item_id}/attributes", response_model=ItemAttributeResponse, status_code=201)
async def add_item_attribute(
    item_id: str,
    request: ItemAttributeCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> ItemAttributeResponse:
    """
    Add an attribute to an item (Manager or Admin).
    """
    item_service = ItemService(db)
    audit_service = AuditService(db)
    
    item = await item_service.get_by_id(item_id)
    if not item:
        raise NotFoundError(resource="Item", resource_id=item_id)
    
    attribute = await item_service.add_attribute(
        item_id=item_id,
        attribute_name=request.attribute_name,
        attribute_value=request.attribute_value,
    )
    
    # Audit log
    await audit_service.log_action(
        action="add_attribute",
        resource_type="item",
        resource_id=item.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"attribute_name": request.attribute_name, "attribute_value": request.attribute_value},
    )
    
    return ItemAttributeResponse.model_validate(attribute)


@router.delete("/{item_id}/attributes/{attribute_id}", response_model=MessageResponse)
async def delete_item_attribute(
    item_id: str,
    attribute_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Delete an item attribute (Manager or Admin).
    """
    item_service = ItemService(db)
    audit_service = AuditService(db)
    
    success = await item_service.remove_attribute(item_id, attribute_id)
    if not success:
        raise NotFoundError(resource="Item Attribute", resource_id=attribute_id)
    
    # Audit log
    await audit_service.log_action(
        action="remove_attribute",
        resource_type="item",
        resource_id=item_id,
        user_id=current_user.id,
        old_value={"attribute_id": attribute_id},
        new_value=None,
    )
    
    return MessageResponse(message="Attribute removed successfully")
