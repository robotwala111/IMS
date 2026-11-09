"""
Jobs Endpoints

Job (Hold) management – create, list, complete, validate.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.dependencies import CurrentUser, DB, PaginationParams, require_admin, require_manager_or_admin, require_any_role
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.schemas.common import MessageResponse
from app.schemas.job import (
    JobCreate,
    JobUpdate,
    JobCompleteRequest,
    JobResponse,
    JobListResponse,
)
from app.services.job_service import JobService
from app.services.audit_service import AuditService

logger = get_logger(__name__)
router = APIRouter()


# ──────────────────────────────────────────────────────────────
# LIST
# ──────────────────────────────────────────────────────────────

@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_user: CurrentUser,
    db: DB,
    pagination: PaginationParams,
    status: Optional[str] = Query(None),
    customer: Optional[str] = Query(None),
    method: Optional[str] = Query(None),
    location_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> JobListResponse:
    """List jobs with optional filters."""
    job_service = JobService(db)

    # RBAC: non-admin users only see jobs in their assigned locations
    location_ids = None
    if not current_user.has_all_location_access:
        location_ids = [loc.id for loc in current_user.assigned_locations]

    jobs, total = await job_service.list_jobs(
        page=pagination["page"],
        page_size=pagination["page_size"],
        sort_by=pagination["sort_by"] or "created_at",
        sort_order=pagination["sort_order"] or "desc",
        status=status,
        customer=customer,
        method=method,
        location_id=location_id,
        location_ids=location_ids,
        search=search,
    )

    pages = (total + pagination["page_size"] - 1) // pagination["page_size"]

    return JobListResponse(
        items=jobs,
        total=total,
        page=pagination["page"],
        page_size=pagination["page_size"],
        pages=pages,
    )


# ──────────────────────────────────────────────────────────────
# GET BY ID
# ──────────────────────────────────────────────────────────────

@router.get("/can-issue")
async def check_can_issue(
    current_user: CurrentUser,
    db: DB,
    person_name: Optional[str] = Query(None),
    assigned_to_id: Optional[str] = Query(None),
) -> dict:
    """Check if a new job can be issued for the person."""
    job_service = JobService(db)
    allowed = await job_service.can_issue_new_job(person_name, assigned_to_id)
    return {"can_issue": allowed}


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    current_user: CurrentUser,
    db: DB,
) -> JobResponse:
    """Get a job by ID."""
    job_service = JobService(db)
    job = await job_service.get_by_id(job_id)
    if not job:
        raise NotFoundError(resource="Job", resource_id=job_id)
    # Location access check
    if not current_user.has_location_access(job.location_id):
        raise NotFoundError(resource="Job", resource_id=job_id)
    return job


# ──────────────────────────────────────────────────────────────
# CREATE
# ──────────────────────────────────────────────────────────────

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    request: JobCreate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_any_role),
) -> JobResponse:
    """Create a new job (hold)."""
    # Location access check
    if request.location_id and not current_user.has_location_access(request.location_id):
        raise AuthorizationError(message="You do not have access to this location")
    job_service = JobService(db)
    audit_service = AuditService(db)

    job = await job_service.create_job(
        job_date=request.job_date,
        customer=request.customer,
        job_name=request.job_name,
        method=request.method,
        quantity=request.quantity,
        coverage=request.coverage,
        total=request.total,
        person_name=request.person_name,
        assigned_to_id=request.assigned_to_id,
        location_id=request.location_id,
        notes=request.notes,
        created_by_id=current_user.id,
    )

    await audit_service.log_action(
        action="create",
        resource_type="job",
        resource_id=job.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "job_number": job.job_number,
            "customer": job.customer,
            "job_name": job.job_name,
        },
    )

    job = await job_service.get_by_id(job.id)
    return job


# ──────────────────────────────────────────────────────────────
# UPDATE
# ──────────────────────────────────────────────────────────────

@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: str,
    request: JobUpdate,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_any_role),
) -> JobResponse:
    """Update a job."""
    job_service = JobService(db)
    audit_service = AuditService(db)

    job = await job_service.get_by_id(job_id)
    if not job:
        raise NotFoundError(resource="Job", resource_id=job_id)
    # Location access check
    if not current_user.has_location_access(job.location_id):
        raise NotFoundError(resource="Job", resource_id=job_id)

    update_data = request.model_dump(exclude_unset=True)
    if not update_data:
        return job

    old_value = {"status": job.status.value, "customer": job.customer}
    updated = await job_service.update_job(job_id, **update_data)

    await audit_service.log_action(
        action="update",
        resource_type="job",
        resource_id=job.id,
        user_id=current_user.id,
        old_value=old_value,
        new_value=update_data,
    )

    updated = await job_service.get_by_id(updated.id)
    return updated


# ──────────────────────────────────────────────────────────────
# COMPLETE (mark as done)
# ──────────────────────────────────────────────────────────────

@router.patch("/{job_id}/complete", response_model=JobResponse)
async def complete_job(
    job_id: str,
    request: JobCompleteRequest,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_any_role),
) -> JobResponse:
    """
    Mark a job as completed.
    The person fills in accepted, reshoot, and cut_films.
    If the sum matches total the job is auto-validated.
    """
    job_service = JobService(db)
    audit_service = AuditService(db)

    # Location access check
    job = await job_service.get_by_id(job_id)
    if job and not current_user.has_location_access(job.location_id):
        raise NotFoundError(resource="Job", resource_id=job_id)

    completed_job = await job_service.complete_job(
        job_id=job_id,
        completed_by_id=current_user.id,
        accepted=request.accepted,
        reshoot=request.reshoot,
        cut_films=request.cut_films,
        cut_films_count=request.cut_films_count,
    )

    await audit_service.log_action(
        action="complete",
        resource_type="job",
        resource_id=completed_job.id,
        user_id=current_user.id,
        old_value=None,
        new_value={
            "accepted": request.accepted,
            "reshoot": request.reshoot,
            "cut_films": request.cut_films,
            "cut_films_count": request.cut_films_count,
            "is_validated": completed_job.is_validated,
        },
    )

    completed_job = await job_service.get_by_id(completed_job.id)
    return completed_job


# ──────────────────────────────────────────────────────────────
# VALIDATE
# ──────────────────────────────────────────────────────────────

@router.patch("/{job_id}/validate", response_model=JobResponse)
async def validate_job(
    job_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_manager_or_admin),
) -> JobResponse:
    """
    Validate a completed job – confirms totals balance.
    Must pass before a new job can be issued.
    """
    job_service = JobService(db)
    audit_service = AuditService(db)

    # Location access check
    job = await job_service.get_by_id(job_id)
    if job and not current_user.has_location_access(job.location_id):
        raise NotFoundError(resource="Job", resource_id=job_id)

    validated = await job_service.validate_job(job_id)

    await audit_service.log_action(
        action="validate",
        resource_type="job",
        resource_id=validated.id,
        user_id=current_user.id,
        old_value=None,
        new_value={"is_validated": True},
    )

    validated = await job_service.get_by_id(validated.id)
    return validated


# ──────────────────────────────────────────────────────────────
# DELETE
# ──────────────────────────────────────────────────────────────

@router.delete("/{job_id}", response_model=MessageResponse)
async def delete_job(
    job_id: str,
    current_user: CurrentUser,
    db: DB,
    _: None = Depends(require_admin),
) -> MessageResponse:
    """Delete a job (Manager or Admin)."""
    job_service = JobService(db)
    audit_service = AuditService(db)

    job = await job_service.get_by_id(job_id)
    if not job:
        raise NotFoundError(resource="Job", resource_id=job_id)
    # Location access check
    if not current_user.has_location_access(job.location_id):
        raise NotFoundError(resource="Job", resource_id=job_id)

    await audit_service.log_action(
        action="delete",
        resource_type="job",
        resource_id=job.id,
        user_id=current_user.id,
        old_value={"job_number": job.job_number, "customer": job.customer},
        new_value=None,
    )

    await job_service.delete_job(job_id)

    return MessageResponse(message="Job deleted successfully")
