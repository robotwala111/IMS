"""
User Management Endpoints

CRUD operations for user management (Admin only for most operations).
"""

from typing import Optional, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select

from app.api.v1.dependencies import (
    CurrentUser,
    DB,
    PaginationParams,
    require_admin,
    require_admin_or_ho_manager,
    require_manager_or_admin,
    require_user_list_access,
)
from app.core.exceptions import NotFoundError, ConflictError, BadRequestError, AuthorizationError
from app.core.logging import get_logger
from app.models.user import User, UserRole, user_location_association
from app.models.location import Location
from app.models.transfer import Transfer, TransferStatus
from app.schemas.common import MessageResponse
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    UserProfileUpdate,
)
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.services.permanent_delete_service import PermanentDeleteService
from app.services.auth_token_service import AuthTokenService

logger = get_logger(__name__)
router = APIRouter()


ALL_LOCATION_ROLES = {UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER}
LOCATION_SCOPED_ROLES = {UserRole.LOCATION_MANAGER}
ACTIVE_TRANSFER_STATUSES = {
    TransferStatus.REQUESTED,
    TransferStatus.APPROVED,
    TransferStatus.IN_TRANSIT,
    TransferStatus.PARTIALLY_RECEIVED,
}


def validate_role_location_scope(role: UserRole, assigned_location_ids: Optional[List[str]]) -> None:
    """Enforce the three-role business rule for location access."""
    if role in LOCATION_SCOPED_ROLES and not assigned_location_ids:
        raise BadRequestError(message="Location Manager must be assigned to at least one location")


def enforce_user_management_scope(
    current_user: User,
    target_role: UserRole,
) -> None:
    """GM may manage Location Managers; Admin controls privileged roles."""
    if (
        current_user.role == UserRole.HEAD_OFFICE_MANAGER
        and target_role != UserRole.LOCATION_MANAGER
    ):
        raise AuthorizationError(
            message="General Managers can manage Location Manager accounts only"
        )


async def enforce_manager_continuity(
    db,
    user: User,
    next_role: UserRole,
    next_is_active: bool,
    next_location_ids: List[str],
) -> None:
    """Keep active locations staffed and active transfers assigned."""
    if user.role != UserRole.LOCATION_MANAGER or not user.is_active:
        return

    current_location_ids = {location.id for location in user.assigned_locations}
    retained_ids = (
        set(next_location_ids)
        if next_role == UserRole.LOCATION_MANAGER and next_is_active
        else set()
    )
    removed_ids = current_location_ids - retained_ids
    if not removed_ids:
        return

    active_location_ids = set((await db.execute(
        select(Location.id).where(
            Location.id.in_(removed_ids),
            Location.is_active.is_(True),
        )
    )).scalars().all())

    for location_id in active_location_ids:
        other_manager_count = (await db.execute(
            select(func.count(User.id))
            .select_from(User)
            .join(
                user_location_association,
                User.id == user_location_association.c.user_id,
            )
            .where(
                user_location_association.c.location_id == location_id,
                User.id != user.id,
                User.role == UserRole.LOCATION_MANAGER,
                User.is_active.is_(True),
            )
        )).scalar_one()
        if other_manager_count == 0:
            raise ConflictError(
                message="Cannot remove or deactivate the only active Location Manager "
                "for an active location. Assign another active manager first."
            )

    pending_transfer = (await db.execute(
        select(Transfer.id).where(
            Transfer.status.in_(ACTIVE_TRANSFER_STATUSES),
            or_(
                and_(
                    Transfer.assigned_to_id == user.id,
                    Transfer.from_location_id.in_(removed_ids),
                ),
                and_(
                    Transfer.destination_responsible_id == user.id,
                    Transfer.to_location_id.in_(removed_ids),
                ),
                and_(
                    Transfer.requested_by_id == user.id,
                    Transfer.to_location_id.in_(removed_ids),
                ),
            ),
        ).limit(1)
    )).scalar_one_or_none()
    if pending_transfer:
        raise ConflictError(
            message="Cannot remove this manager from the location while they own an "
            "active transfer. Reassign or complete the transfer first."
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: CurrentUser,
) -> UserResponse:
    """
    Get current user's profile.
    """
    return UserResponse.from_orm_with_locations(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_current_user_profile(
    request: UserProfileUpdate,
    current_user: CurrentUser,
    db: DB,
) -> UserResponse:
    """
    Update current user's profile (limited fields).
    """
    user_service = UserService(db)
    
    update_data = request.model_dump(exclude_unset=True)
    if update_data:
        user = await user_service.update(current_user.id, **update_data)
    else:
        user = current_user
    
    user = await user_service.get_by_id(user.id)
    return UserResponse.from_orm_with_locations(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    role: Optional[UserRole] = Query(None),
    is_active: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    _: None = Depends(require_user_list_access),
) -> UserListResponse:
    """
    List all users (Admin only).
    """
    user_service = UserService(db)
    
    if current_user.role == UserRole.DEMO_USER:
        role = UserRole.DEMO_USER
    elif current_user.role == UserRole.HEAD_OFFICE_MANAGER and role not in (
        None,
        UserRole.LOCATION_MANAGER,
    ):
        raise AuthorizationError(
            message="General Managers can view Location Manager accounts only"
        )

    users, total = await user_service.list_users(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"],
        sort_order=pagination["sort_order"],
        role=(
            UserRole.DEMO_USER
            if current_user.role == UserRole.DEMO_USER
            else UserRole.LOCATION_MANAGER
            if current_user.role == UserRole.HEAD_OFFICE_MANAGER
            else role
        ),
        is_active=is_active,
        search=search,
    )
    
    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]
    
    return UserListResponse(
        items=[UserResponse.from_orm_with_locations(u) for u in users],
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


@router.get("/by-location")
async def get_users_by_location(
    location_id: str,
    current_user: CurrentUser,
    db: DB,
) -> list:
    """
    Get active users assigned to a specific location.
    Used for transfer 'Assign To' dropdown.
    """
    location = (
        await db.execute(
            select(Location).where(
                Location.id == location_id,
                Location.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if not location:
        raise NotFoundError(resource="Active Location", resource_id=location_id)

    # Transfer requesters may select any active company location as a source,
    # so expose only the active Location Managers assigned to that location.
    query = (
        select(User)
        .outerjoin(user_location_association, User.id == user_location_association.c.user_id)
        .where(User.is_active == True)
    )
    query = query.where(
        user_location_association.c.location_id == location_id,
        User.role == UserRole.LOCATION_MANAGER,
    )
    result = await db.execute(query.order_by(User.name))
    users = result.scalars().unique().all()
    return [
        {"id": u.id, "name": u.name, "role": u.role}
        for u in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> UserResponse:
    """
    Get a specific user by ID (Admin only).
    """
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user:
        raise NotFoundError(resource="User", resource_id=user_id)
    enforce_user_management_scope(current_user, user.role)
    if current_user.role == UserRole.LOCATION_MANAGER:
        if user.role != UserRole.LOCATION_MANAGER:
            raise AuthorizationError(message="Location Managers can deactivate Location Manager accounts only")
        caller_locations = {location.id for location in current_user.assigned_locations}
        target_locations = {location.id for location in user.assigned_locations}
        if not target_locations or not target_locations.issubset(caller_locations):
            raise AuthorizationError(message="User is outside your assigned location scope")
    
    return UserResponse.from_orm_with_locations(user)


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    request: UserCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> UserResponse:
    """
    Create a new user (Admin only).
    """
    user_service = UserService(db)
    audit_service = AuditService(db)
    enforce_user_management_scope(current_user, request.role)
    
    # Check for existing email
    existing = await user_service.get_by_email(request.email)
    if existing:
        raise ConflictError(message=f"User with email {request.email} already exists")
    
    # Validate password strength
    from app.core.security import validate_password_strength
    is_valid, pw_error = validate_password_strength(request.password)
    if not is_valid:
        raise BadRequestError(message=f"Password too weak: {pw_error}")

    validate_role_location_scope(request.role, request.assigned_location_ids)
    
    # Create user
    user = await user_service.create(
        email=request.email,
        name=request.name,
        password=request.password,
        role=request.role,
        assigned_location_ids=request.assigned_location_ids,
        phone=request.phone,
        department=request.department,
        is_active=request.is_active,
    )
    
    # Audit log
    await audit_service.log_action(
        action="create",
        resource_type="user",
        resource_id=user.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"email": user.email, "role": user.role.value},
    )
    
    user = await user_service.get_by_id(user.id)
    return UserResponse.from_orm_with_locations(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    request: UserUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin_or_ho_manager),
) -> UserResponse:
    """
    Update a user (Admin only).
    """
    user_service = UserService(db)
    audit_service = AuditService(db)
    
    # Get existing user
    user = await user_service.get_by_id(user_id)
    if not user:
        raise NotFoundError(resource="User", resource_id=user_id)
    enforce_user_management_scope(current_user, user.role)
    
    old_value = {
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "is_active": user.is_active,
    }
    
    # Check email uniqueness if changing
    if request.email and request.email != user.email:
        existing = await user_service.get_by_email(request.email)
        if existing:
            raise ConflictError(message=f"User with email {request.email} already exists")
    
    # Update user
    update_data = request.model_dump(exclude_unset=True)
    
    # Extract location_ids for separate handling (not a model column)
    location_ids = update_data.pop('assigned_location_ids', None)
    next_role = update_data.get("role") or user.role
    enforce_user_management_scope(current_user, next_role)
    next_location_ids = (
        location_ids
        if location_ids is not None
        else [loc.id for loc in user.assigned_locations]
    )
    validate_role_location_scope(next_role, next_location_ids)
    await enforce_manager_continuity(
        db,
        user,
        next_role,
        update_data.get("is_active", user.is_active),
        next_location_ids,
    )
    
    # Handle password separately
    password = update_data.pop('password', None)
    if password:
        from app.core.security import hash_password, validate_password_strength
        is_valid, pw_error = validate_password_strength(password)
        if not is_valid:
            raise BadRequestError(message=f"Password too weak: {pw_error}")
        update_data['password_hash'] = hash_password(password)
    
    if update_data:
        user = await user_service.update(user_id, **update_data)
        if password or update_data.get("is_active") is False:
            await AuthTokenService(db).revoke_all(user_id)
    
    # Update assigned locations if provided
    if location_ids is not None:
        from sqlalchemy import select as sa_select
        from app.models.location import Location
        result = await db.execute(
            sa_select(Location).where(Location.id.in_(location_ids))
        )
        user.assigned_locations = list(result.scalars().all())
        await db.commit()
        await db.refresh(user)
    
    # Audit log
    new_value = {
        "email": user.email,
        "name": user.name,
        "role": user.role.value,
        "is_active": user.is_active,
    }
    await audit_service.log_action(
        action="update",
        resource_type="user",
        resource_id=user.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=new_value,
    )
    
    user = await user_service.get_by_id(user.id)
    return UserResponse.from_orm_with_locations(user)


@router.delete("/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> MessageResponse:
    """
    Delete (deactivate) a user (Admin only).
    
    Note: Users are soft-deleted by setting is_active=False.
    """
    if user_id == current_user.id:
        raise ConflictError(message="Cannot delete your own account")
    
    user_service = UserService(db)
    audit_service = AuditService(db)
    
    user = await user_service.get_by_id(user_id)
    if not user:
        raise NotFoundError(resource="User", resource_id=user_id)
    enforce_user_management_scope(current_user, user.role)
    await enforce_manager_continuity(db, user, user.role, False, [])
    
    # Soft delete
    await user_service.update(user_id, is_active=False)
    await AuthTokenService(db).revoke_all(user_id)
    
    # Audit log
    await audit_service.log_action(
        action="delete",
        resource_type="user",
        resource_id=user.id,
        user_id=current_user.id,
        old_value={"is_active": True},
        new_value={"is_active": False},
    )
    
    return MessageResponse(message=f"User {user.email} has been deactivated")


@router.delete("/{user_id}/permanent", response_model=MessageResponse)
async def permanently_delete_user(
    user_id: str,
    current_user: CurrentUser,
    db: DB,
    force: bool = Query(False),
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Permanently delete an unreferenced user account (Admin only)."""
    if user_id == current_user.id:
        raise ConflictError(message="Cannot permanently delete your own account")
    service = PermanentDeleteService(db)
    user = await service.get("user", user_id)
    if user.role == UserRole.ADMIN and user.is_active:
        active_admin_count = len((await db.execute(
            select(User.id).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
        )).scalars().all())
        if active_admin_count <= 1:
            raise ConflictError(message="Cannot permanently delete the last active Admin")
    await enforce_manager_continuity(db, user, user.role, False, [])
    name = await service.delete(
        "user", user_id, current_user, force_user_dependencies=force
    )
    return MessageResponse(message=f"User {name} permanently deleted")
