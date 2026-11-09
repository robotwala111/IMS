"""
API v1 Router

Aggregates all API v1 routes.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    users,
    locations,
    categories,
    items,
    stock,
    transactions,
    transfers,
    assets,
    calibration,
    maintenance,
    attachments,
    dashboard,
    reports,
    notifications,
    audit,
    employee_records,
    employees,
    jobs,
    purchase_indents,
    archive,
    branding,
    generated_documents,
)

api_router = APIRouter()

# Auth routes (no prefix)
api_router.include_router(
    auth.router,
    prefix="/auth",
    tags=["Authentication"],
)

# User management
api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users"],
)

# Location management
api_router.include_router(
    locations.router,
    prefix="/locations",
    tags=["Locations"],
)

# Category management
api_router.include_router(
    categories.router,
    prefix="/categories",
    tags=["Categories"],
)

# Item management
api_router.include_router(
    items.router,
    prefix="/items",
    tags=["Items"],
)

# Stock management
api_router.include_router(
    stock.router,
    prefix="/stock",
    tags=["Stock"],
)

# Transactions
api_router.include_router(
    transactions.router,
    prefix="/transactions",
    tags=["Transactions"],
)

# Transfers
api_router.include_router(
    transfers.router,
    prefix="/transfers",
    tags=["Transfers"],
)

# Serialized assets
api_router.include_router(
    assets.router,
    prefix="/assets",
    tags=["Assets"],
)

# Calibration
api_router.include_router(
    calibration.router,
    prefix="/calibration",
    tags=["Calibration"],
)

# Maintenance
api_router.include_router(
    maintenance.router,
    prefix="/maintenance",
    tags=["Maintenance"],
)

# Attachments
api_router.include_router(
    attachments.router,
    prefix="/attachments",
    tags=["Attachments"],
)

# Dashboard
api_router.include_router(
    dashboard.router,
    prefix="/dashboard",
    tags=["Dashboard"],
)

# Reports
api_router.include_router(
    reports.router,
    prefix="/reports",
    tags=["Reports"],
)

# Notifications
api_router.include_router(
    notifications.router,
    prefix="/notifications",
    tags=["Notifications"],
)

# Audit logs
api_router.include_router(
    audit.router,
    prefix="/audit",
    tags=["Audit"],
)

# Employee digital records
api_router.include_router(
    employee_records.router,
    prefix="/employee-records",
    tags=["Employee Records"],
)

# Employees (non-login staff)
api_router.include_router(
    employees.router,
    prefix="/employees",
    tags=["Employees"],
)

# Jobs (Hold)
api_router.include_router(
    jobs.router,
    prefix="/jobs",
    tags=["Jobs"],
)

# Purchase Indents
api_router.include_router(
    purchase_indents.router,
    prefix="/purchase-indents",
    tags=["Purchase Indents"],
)

# Archive / Data Export
api_router.include_router(
    archive.router,
    tags=["Archive"],
)

api_router.include_router(
    generated_documents.router,
    prefix="/generated-documents",
    tags=["Generated Documents"],
)

api_router.include_router(
    branding.router,
    prefix="/branding",
    tags=["Branding"],
)
