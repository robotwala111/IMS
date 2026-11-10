"""Schemas module initialization."""

from app.schemas.common import (
    PaginationParams,
    PaginatedResponse,
    MessageResponse,
    ErrorResponse,
    ErrorDetail,
)
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    TokenRefreshRequest,
    TokenRefreshResponse,
    ChangePasswordRequest,
)
from app.schemas.user import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
)
from app.schemas.location import (
    LocationCreate,
    LocationUpdate,
    LocationResponse,
)
from app.schemas.category import (
    CategoryCreate,
    CategoryUpdate,
    CategoryResponse,
)
from app.schemas.item import (
    ItemCreate,
    ItemUpdate,
    ItemResponse,
    ItemAttributeCreate,
    ItemAttributeResponse,
)
from app.schemas.stock import (
    StockResponse,
    StockAdjustmentRequest,
    StockLotCreate,
    StockLotResponse,
)
from app.schemas.transaction import (
    TransactionCreate,
    TransactionResponse,
    ReceiptRequest,
    IssueRequest,
    ReturnRequest,
)
from app.schemas.transfer import (
    TransferCreate,
    TransferResponse,
    TransferItemCreate,
    TransferApprovalRequest,
)
from app.schemas.asset import (
    AssetCreate,
    AssetUpdate,
    AssetResponse,
    CalibrationRecordCreate,
    CalibrationRecordResponse,
    CalibrationRecordListResponse,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
)
from app.schemas.dashboard import (
    DashboardSummary,
    StockByLocation,
    StockByCategory,
    LowStockItem,
    RecentActivity,
    CalibrationAlert,
    TransferSummary,
    TrendData,
)
from app.schemas.reports import (
    ReportFormat,
    InventoryReport,
    TransactionReport,
    CalibrationReport,
    StockMovementReport,
    AssetReport,
)
from app.schemas.attachment import (
    AttachmentResponse,
    AttachmentListResponse,
)
from app.schemas.notification import (
    NotificationResponse,
    NotificationListResponse,
    NotificationMarkReadRequest,
)
from app.schemas.audit import (
    AuditLogResponse,
    AuditLogListResponse,
)
from app.schemas.job import (
    JobCreate,
    JobUpdate,
    JobCompleteRequest,
    JobResponse,
    JobListResponse,
)

__all__ = [
    # Common
    "PaginationParams",
    "PaginatedResponse",
    "MessageResponse",
    "ErrorResponse",
    "ErrorDetail",
    # Auth
    "LoginRequest",
    "LoginResponse",
    "TokenRefreshRequest",
    "TokenRefreshResponse",
    "ChangePasswordRequest",
    # User
    "UserCreate",
    "UserUpdate",
    "UserResponse",
    "UserListResponse",
    # Location
    "LocationCreate",
    "LocationUpdate",
    "LocationResponse",
    # Category
    "CategoryCreate",
    "CategoryUpdate",
    "CategoryResponse",
    # Item
    "ItemCreate",
    "ItemUpdate",
    "ItemResponse",
    "ItemAttributeCreate",
    "ItemAttributeResponse",
    # Stock
    "StockResponse",
    "StockAdjustmentRequest",
    "StockLotCreate",
    "StockLotResponse",
    # Transaction
    "TransactionCreate",
    "TransactionResponse",
    "ReceiptRequest",
    "IssueRequest",
    "ReturnRequest",
    # Transfer
    "TransferCreate",
    "TransferResponse",
    "TransferItemCreate",
    "TransferApprovalRequest",
    # Asset
    "AssetCreate",
    "AssetUpdate",
    "AssetResponse",
    "CalibrationRecordCreate",
    "CalibrationRecordResponse",
    "CalibrationRecordListResponse",
    "MaintenanceRecordCreate",
    "MaintenanceRecordResponse",
    # Dashboard
    "DashboardSummary",
    "StockByLocation",
    "StockByCategory",
    "LowStockItem",
    "RecentActivity",
    "CalibrationAlert",
    "TransferSummary",
    "TrendData",
    # Reports
    "ReportFormat",
    "InventoryReport",
    "TransactionReport",
    "CalibrationReport",
    "StockMovementReport",
    "AssetReport",
    # Attachment
    "AttachmentResponse",
    "AttachmentListResponse",
    # Notification
    "NotificationResponse",
    "NotificationListResponse",
    "NotificationMarkReadRequest",
    # Audit
    "AuditLogResponse",
    "AuditLogListResponse",
    # Job
    "JobCreate",
    "JobUpdate",
    "JobCompleteRequest",
    "JobResponse",
    "JobListResponse",
]
