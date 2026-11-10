"""
Authentication Endpoints

Handles login, logout, token refresh, and password management.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import CurrentUser, DB
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.logging import get_logger
from app.core.security import (
    hash_password,
    validate_password_strength,
    validate_refresh_token,
    verify_password,
)
from app.core.config import settings
from app.models.user import UserRole
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    PasswordResetRequest,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    TokenRefreshRequest,
    TokenRefreshResponse,
    UserBasicInfo,
)
from app.schemas.common import MessageResponse
from app.services.user_service import UserService
from app.services.audit_service import AuditService
from app.services.email_service import get_email_service
from app.services.auth_token_service import AuthTokenService

logger = get_logger(__name__)
router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(
    request: LoginRequest,
    db: DB,
) -> LoginResponse:
    """
    Authenticate user and return access/refresh tokens.
    """
    user_service = UserService(db)
    audit_service = AuditService(db)
    
    # Find user by email
    user = await user_service.get_by_email(request.email)
    
    if not user:
        await audit_service.log_action(
            action="login_failed",
            resource_type="auth",
            resource_id=None,
            user_id=None,
            old_value=None,
            new_value={"email": request.email, "reason": "user_not_found"},
            status="failure",
            error_message="Invalid credentials",
        )
        raise AuthenticationError(message="Invalid email or password")
    
    if user.locked_until:
        try:
            lock_time = datetime.fromisoformat(user.locked_until)
            if lock_time.tzinfo is None:
                lock_time = lock_time.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) < lock_time:
                await audit_service.log_action(
                    action="login_failed", resource_type="auth", resource_id=user.id,
                    user_id=user.id, new_value={"reason": "account_locked"},
                    status="failure", error_message="Account is temporarily locked",
                )
                raise AuthenticationError(
                    message="Account is temporarily locked. Please try again later."
                )
            await user_service.reset_failed_attempts(user.id)
        except ValueError:
            await user_service.reset_failed_attempts(user.id)
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        new_failed_count = await user_service.increment_failed_attempts(user.id)
        if new_failed_count >= settings.MAX_LOGIN_ATTEMPTS:
            await user_service.lock_account(user.id, settings.LOCKOUT_DURATION_MINUTES)
        
        await audit_service.log_action(
            action="login_failed",
            resource_type="auth",
            resource_id=user.id,
            user_id=user.id,
            old_value=None,
            new_value={"reason": "invalid_password", "attempt": new_failed_count},
            status="failure",
            error_message="Invalid credentials",
        )
        
        raise AuthenticationError(message="Invalid email or password")
    
    # Check if user is active
    if not user.is_active:
        await audit_service.log_action(
            action="login_failed", resource_type="auth", resource_id=user.id,
            user_id=user.id, new_value={"reason": "account_disabled"},
            status="failure", error_message="Account is disabled",
        )
        raise AuthenticationError(message="Account is disabled")
    
    # Reset failed attempts on successful login
    await user_service.reset_failed_attempts(user.id)
    
    # Capture previous login time before updating
    previous_login_at = user.last_login_at
    await user_service.update_last_login(user.id)
    
    # Generate tokens
    access_token, refresh_token = await AuthTokenService(db).create_session(user)
    
    # Log successful login
    await audit_service.log_action(
        action="login_success",
        resource_type="auth",
        resource_id=user.id,
        user_id=user.id,
        old_value=None,
        new_value=None,
    )
    
    # Get assigned location IDs
    location_ids = [loc.id for loc in user.assigned_locations]
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserBasicInfo(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            assigned_location_ids=location_ids,
            last_login_at=previous_login_at,
        ),
    )


@router.post("/demo-login", response_model=LoginResponse)
async def demo_login(db: DB) -> LoginResponse:
    """Start a restricted session for the configured demo account."""
    user = await UserService(db).get_by_email(settings.DEMO_USER_EMAIL)
    if not user or not user.is_active or user.role != UserRole.DEMO_USER:
        raise AuthenticationError(message="The demo account is unavailable")

    previous_login_at = user.last_login_at
    await UserService(db).update_last_login(user.id)
    access_token, refresh_token = await AuthTokenService(db).create_session(user)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserBasicInfo(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role,
            assigned_location_ids=[loc.id for loc in user.assigned_locations],
            last_login_at=previous_login_at,
        ),
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
async def refresh_token(
    request: TokenRefreshRequest,
    db: DB,
) -> TokenRefreshResponse:
    """
    Refresh access token using a valid refresh token.
    """
    # Validate refresh token
    payload = validate_refresh_token(request.refresh_token)
    user_id = payload.get("sub")
    
    # Get user
    user_service = UserService(db)
    user = await user_service.get_by_id(user_id)
    
    if not user or not user.is_active:
        raise AuthenticationError(message="Invalid refresh token")
    
    access_token, refresh_token = await AuthTokenService(db).rotate(
        request.refresh_token, user
    )
    
    return TokenRefreshResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: Request,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Logout current user and revoke the active session immediately.
    """
    await AuthTokenService(db).revoke_session(
        request.state.auth_session_id, current_user.id
    )
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="logout",
        resource_type="auth",
        resource_id=current_user.id,
        user_id=current_user.id,
        old_value=None,
        new_value=None,
    )
    
    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    request: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Change current user's password.
    """
    # Verify current password
    if not verify_password(request.current_password, current_user.password_hash):
        raise AuthenticationError(message="Current password is incorrect")
    
    # Check new password matches confirmation
    if request.new_password != request.confirm_password:
        raise ValidationError(message="New password and confirmation do not match")
    
    # Validate new password strength
    is_valid, error_msg = validate_password_strength(request.new_password)
    if not is_valid:
        raise ValidationError(message=error_msg)
    
    # Update password
    user_service = UserService(db)
    new_hash = hash_password(request.new_password)
    await user_service.update_password(current_user.id, new_hash)
    await AuthTokenService(db).revoke_all(current_user.id)
    
    # Log action
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="password_changed",
        resource_type="user",
        resource_id=current_user.id,
        user_id=current_user.id,
        old_value=None,
        new_value=None,
    )
    
    return MessageResponse(message="Password changed successfully")


@router.post("/register", response_model=MessageResponse)
async def register_user(
    request: RegisterRequest,
    current_user: CurrentUser,
    db: DB,
) -> MessageResponse:
    """
    Register a new user (Admin only).
    """
    # Only admins can register new users
    if current_user.role != UserRole.ADMIN:
        raise AuthenticationError(message="Only administrators can register new users")
    
    user_service = UserService(db)
    
    # Check if email already exists
    existing = await user_service.get_by_email(request.email)
    if existing:
        raise ValidationError(message="Email already registered")
    
    # Validate password strength
    is_valid, error_msg = validate_password_strength(request.password)
    if not is_valid:
        raise ValidationError(message=error_msg)

    if request.role == UserRole.LOCATION_MANAGER and not request.assigned_location_ids:
        raise ValidationError(message="Location Manager must be assigned to at least one location")
    
    # Create user
    user = await user_service.create(
        email=request.email,
        name=request.name,
        password=request.password,
        role=request.role,
        assigned_location_ids=request.assigned_location_ids,
        phone=request.phone,
        department=request.department,
    )
    
    # Log action
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="user_registered",
        resource_type="user",
        resource_id=user.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"email": user.email, "role": user.role.value},
    )
    
    return MessageResponse(
        message=f"User {request.email} registered successfully",
        data={"user_id": user.id},
    )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    request: ForgotPasswordRequest,
    db: DB,
) -> MessageResponse:
    """
    Handle forgot password request.
    
    Always returns success to prevent email enumeration.
    Sends a password reset email to the user's email address if account exists.
    """
    user_service = UserService(db)
    audit_service = AuditService(db)
    email_service = get_email_service()
    
    user = await user_service.get_by_email(request.email)
    
    if user:
        # Log the password reset request
        await audit_service.log_action(
            action="password_reset_requested",
            resource_type="auth",
            resource_id=user.id,
            user_id=user.id,
            old_value=None,
            new_value={"email": request.email},
        )
        
        reset_token = await AuthTokenService(db).issue_password_reset(user.id)
        reset_link = f"{settings.APP_URL}/?reset_token={reset_token}"
        
        # Send password reset email
        email_service.send_password_reset_email(
            to_email=user.email,
            user_name=user.name,
            reset_link=reset_link,
        )
        
        logger.info(f"Password reset email sent to: {request.email}")
    else:
        logger.info(f"Password reset requested for unknown email: {request.email}")
    
    # Always return success to prevent email enumeration
    return MessageResponse(
        message="If an account exists with that email, password reset instructions will be sent."
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(request: PasswordResetRequest, db: DB) -> MessageResponse:
    """Consume an expiring, single-use password reset token."""
    if request.new_password != request.confirm_password:
        raise ValidationError(message="New password and confirmation do not match")
    user = await AuthTokenService(db).consume_password_reset(
        request.token, request.new_password
    )
    await AuditService(db).log_action(
        action="password_reset_completed",
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
    )
    return MessageResponse(message="Password reset successfully. Please log in.")
