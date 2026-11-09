"""
Custom Exception Classes

Provides structured exceptions for consistent error handling across the application.
"""

from typing import Any, Dict, Optional


class AppException(Exception):
    """Base exception class for application errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "APP_ERROR",
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.message = message
        self.error_code = error_code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppException):
    """Raised when authentication fails."""
    
    def __init__(
        self,
        message: str = "Authentication failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="AUTHENTICATION_ERROR",
            status_code=401,
            details=details,
        )


class AuthorizationError(AppException):
    """Raised when user lacks permission for an action."""
    
    def __init__(
        self,
        message: str = "You do not have permission to perform this action",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="AUTHORIZATION_ERROR",
            status_code=403,
            details=details,
        )


class NotFoundError(AppException):
    """Raised when a requested resource is not found."""
    
    def __init__(
        self,
        resource: str = "Resource",
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = f"{resource} not found"
        if resource_id:
            message = f"{resource} with ID '{resource_id}' not found"
        super().__init__(
            message=message,
            error_code="NOT_FOUND",
            status_code=404,
            details=details,
        )


class ConflictError(AppException):
    """Raised when a conflict occurs (e.g., duplicate entry)."""
    
    def __init__(
        self,
        message: str = "Resource conflict",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="CONFLICT",
            status_code=409,
            details=details,
        )


class BadRequestError(AppException):
    """Raised when request is malformed or invalid."""
    
    def __init__(
        self,
        message: str = "Bad request",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="BAD_REQUEST",
            status_code=400,
            details=details,
        )


class ValidationError(AppException):
    """Raised when input validation fails."""
    
    def __init__(
        self,
        message: str = "Validation error",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )


class BusinessRuleError(AppException):
    """Raised when a business rule is violated."""
    
    def __init__(
        self,
        message: str,
        rule_code: str = "BUSINESS_RULE_VIOLATION",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code=rule_code,
            status_code=400,
            details=details,
        )


class RateLimitError(AppException):
    """Raised when rate limit is exceeded."""
    
    def __init__(
        self,
        message: str = "Rate limit exceeded. Please try again later.",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=details,
        )


class StorageError(AppException):
    """Raised when file storage operations fail."""
    
    def __init__(
        self,
        message: str = "Storage operation failed",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=message,
            error_code="STORAGE_ERROR",
            status_code=500,
            details=details,
        )


class CalibrationExpiredError(BusinessRuleError):
    """Raised when attempting to issue an instrument with expired calibration."""
    
    def __init__(
        self,
        asset_serial: str,
        due_date: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = (
            f"Cannot issue instrument '{asset_serial}': calibration expired on {due_date}. "
            "Admin override required."
        )
        super().__init__(
            message=message,
            rule_code="CALIBRATION_EXPIRED",
            details={"serial_number": asset_serial, "due_date": due_date, **(details or {})},
        )


class ExpiredLotError(BusinessRuleError):
    """Raised when attempting to issue from an expired lot."""
    
    def __init__(
        self,
        lot_number: str,
        expiry_date: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = f"Cannot issue from lot '{lot_number}': expired on {expiry_date}"
        super().__init__(
            message=message,
            rule_code="LOT_EXPIRED",
            details={"lot_number": lot_number, "expiry_date": expiry_date, **(details or {})},
        )


class InsufficientStockError(BusinessRuleError):
    """Raised when there is not enough stock for an operation."""
    
    def __init__(
        self,
        item_name: str,
        requested: int,
        available: int,
        location: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        message = (
            f"Insufficient stock for '{item_name}' at {location}: "
            f"requested {requested}, available {available}"
        )
        super().__init__(
            message=message,
            rule_code="INSUFFICIENT_STOCK",
            details={
                "item": item_name,
                "requested": requested,
                "available": available,
                "location": location,
                **(details or {}),
            },
        )
