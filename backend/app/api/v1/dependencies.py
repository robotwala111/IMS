"""
API Dependencies

Provides dependency injection for authentication, authorization, and common resources.
"""

from typing import Annotated, List, Optional

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import validate_access_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.services.user_service import UserService
from app.services.auth_token_service import AuthTokenService

logger = get_logger(__name__)
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(bearer_scheme),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Dependency to get the current authenticated user from JWT token.
    
    Raises:
        AuthenticationError: If token is invalid or user not found
    """
    if not credentials:
        raise AuthenticationError(message="Authorization header missing")

    if credentials.scheme.lower() != "bearer":
        raise AuthenticationError(message="Invalid authorization header format")

    # Validate token
    payload = validate_access_token(credentials.credentials)
    user_id = payload.get("sub")
    session_id = payload.get("sid")
    
    if not user_id or not session_id:
        raise AuthenticationError(message="Invalid token payload")
    
    # Get user from database
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user:
        raise AuthenticationError(message="User not found")
    
    if not user.is_active:
        raise AuthenticationError(message="User account is disabled")

    if not await AuthTokenService(db).is_session_active(session_id, user.id):
        raise AuthenticationError(message="Session has expired or was revoked")

    if user.role == UserRole.DEMO_USER:
        path = request.url.path
        api_prefix = settings.API_V1_PREFIX.rstrip("/")
        if path.startswith(api_prefix):
            path = path[len(api_prefix):] or "/"
        method = request.method.upper()
        read_prefixes = (
            "/dashboard",
            "/assets",
            "/categories",
            "/items",
            "/maintenance",
            "/calibration",
            "/branding",
        )
        allowed = method == "GET" and any(
            path == prefix or path.startswith(prefix + "/")
            for prefix in read_prefixes
        )
        allowed = allowed or (
            method == "GET" and path == "/transfers/equipment-overview"
        )
        allowed = allowed or (
            method == "GET" and path in {"/users", "/users/me"}
        )
        allowed = allowed or (
            method == "POST" and path in {"/auth/logout", "/auth/refresh"}
        )
        if not allowed:
            raise AuthorizationError(
                message="Demo accounts can only view Dashboard, Products, Compliance, and User Management"
            )
    
    # Store user in request state for audit logging
    request.state.current_user = user
    request.state.auth_session_id = session_id
    
    return user


# Type alias for current user dependency
CurrentUser = Annotated[User, Depends(get_current_user)]


class RoleChecker:
    """Dependency class for role-based access control."""
    
    def __init__(self, allowed_roles: List[UserRole]) -> None:
        self.allowed_roles = allowed_roles
    
    def __call__(self, user: CurrentUser) -> User:
        if user.role not in self.allowed_roles:
            raise AuthorizationError(
                message=f"Role '{user.role.value}' is not authorized for this action",
                details={"required_roles": [r.value for r in self.allowed_roles]},
            )
        return user


# Pre-configured role checkers
require_admin = RoleChecker([UserRole.ADMIN])
require_admin_or_ho_manager = RoleChecker([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER])
require_manager_or_admin = RoleChecker([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER, UserRole.LOCATION_MANAGER])
require_any_role = RoleChecker([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER, UserRole.LOCATION_MANAGER])
require_user_list_access = RoleChecker([
    UserRole.ADMIN,
    UserRole.HEAD_OFFICE_MANAGER,
    UserRole.DEMO_USER,
])


class LocationAccessChecker:
    """Dependency to check user has access to a specific location."""
    
    def __init__(self, location_id_param: str = "location_id") -> None:
        self.location_id_param = location_id_param
    
    async def __call__(
        self,
        request: Request,
        user: CurrentUser,
    ) -> User:
        # Admins and head office managers have access to all locations
        if user.has_all_location_access:
            return user
        
        # Get location_id from path or query params
        location_id = request.path_params.get(self.location_id_param)
        if not location_id:
            location_id = request.query_params.get(self.location_id_param)
        
        if location_id and not user.has_location_access(location_id):
            raise AuthorizationError(
                message="You do not have access to this location",
                details={"location_id": location_id},
            )
        
        return user


# Database session dependency alias
DB = Annotated[AsyncSession, Depends(get_db)]


def get_pagination_params(
    page: int = 1,
    page_size: int = 20,
    sort_by: Optional[str] = "name",
    sort_order: str = "asc",
) -> dict:
    """Get pagination parameters as a dictionary."""
    return {
        "page": max(1, page),
        "page_size": min(max(1, page_size), 100),
        "sort_by": sort_by or "name",
        "sort_order": sort_order if sort_order in ("asc", "desc") else "asc",
        "offset": (max(1, page) - 1) * min(max(1, page_size), 100),
    }


PaginationParams = Annotated[dict, Depends(get_pagination_params)]


def authorized_location_ids(user: User) -> Optional[List[str]]:
    """Return None for company-wide users, otherwise the user's allowed IDs."""
    if user.has_all_location_access:
        return None
    return [location.id for location in user.assigned_locations]


def require_location_access(user: User, location_id: Optional[str]) -> None:
    """Reject access unless the user can access the supplied location."""
    if user.has_all_location_access:
        return
    if not location_id or not user.has_location_access(location_id):
        raise AuthorizationError(
            message="You do not have access to this location",
            details={"location_id": location_id},
        )
