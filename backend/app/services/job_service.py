"""
Job Service

Handles Job (Hold) management – create, list, complete, validate.
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, func, and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.base_service import BaseService


class JobService(BaseService[Job]):
    """Service for Job management."""

    @property
    def model(self):
        return Job

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _generate_job_number(self) -> str:
        """Generate a unique job reference number."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        short_id = self.generate_id()[:6].upper()
        return f"JOB-{ts}-{short_id}"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def get_by_id(self, id: str) -> Optional[Job]:
        """Get a job with related data."""
        result = await self.db.execute(
            select(Job)
            .options(
                selectinload(Job.assigned_to),
                selectinload(Job.completed_by),
                selectinload(Job.created_by),
                selectinload(Job.location),
            )
            .where(Job.id == id)
        )
        return result.scalar_one_or_none()

    async def list_jobs(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        status: Optional[str] = None,
        customer: Optional[str] = None,
        method: Optional[str] = None,
        location_id: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        filters=None,
    ) -> Tuple[List[Job], int]:
        """List jobs with filtering and pagination."""

        # Unpack filters object if provided from endpoint
        if filters is not None:
            status = getattr(filters, "status", None) or status
            customer = getattr(filters, "customer", None) or customer
            method = getattr(filters, "method", None) or method
            location_id = getattr(filters, "location_id", None) or location_id
            search = getattr(filters, "search", None) or search

        query = select(Job).options(
            selectinload(Job.assigned_to),
            selectinload(Job.completed_by),
            selectinload(Job.created_by),
            selectinload(Job.location),
        )

        # RBAC: restrict to user's locations
        if location_ids is not None:
            query = query.where(
                or_(
                    Job.location_id.in_(location_ids),
                    Job.location_id.is_(None),
                )
            )

        if location_id:
            query = query.where(Job.location_id == location_id)
        if status:
            query = query.where(Job.status == status)
        if customer:
            query = query.where(Job.customer.ilike(f"%{customer}%"))
        if method:
            query = query.where(Job.method == method)
        if search:
            pat = f"%{search}%"
            query = query.where(
                or_(
                    Job.job_number.ilike(pat),
                    Job.customer.ilike(pat),
                    Job.job_name.ilike(pat),
                    Job.person_name.ilike(pat),
                )
            )

        # Total count
        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar_one()

        # Sorting
        if hasattr(Job, sort_by):
            col = getattr(Job, sort_by)
            query = query.order_by(col.desc() if sort_order == "desc" else col.asc())

        # Pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await self.db.execute(query)
        jobs = list(result.scalars().unique().all())
        return jobs, total

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_job(
        self,
        job_date,
        customer: str,
        job_name: str,
        method: str,
        quantity: int,
        total: int,
        person_name: str,
        created_by_id: Optional[str] = None,
        coverage: Optional[str] = None,
        assigned_to_id: Optional[str] = None,
        location_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Job:
        """Create a new job in HOLD status."""
        if assigned_to_id:
            result = await self.db.execute(
                select(User)
                .options(selectinload(User.assigned_locations))
                .where(User.id == assigned_to_id)
            )
            assignee = result.scalar_one_or_none()
            if not assignee or not assignee.is_active:
                raise BadRequestError(message="Assigned user must be active")
            if (
                location_id
                and not assignee.has_all_location_access
                and location_id not in {location.id for location in assignee.assigned_locations}
            ):
                raise BadRequestError(message="Assigned user does not belong to the job location")
            person_name = assignee.name

        values = dict(
            id=self.generate_id(),
            job_date=job_date,
            customer=customer,
            job_name=job_name,
            method=method,
            quantity=quantity,
            coverage=coverage,
            total=total,
            person_name=person_name,
            assigned_to_id=assigned_to_id,
            location_id=location_id,
            status=JobStatus.HOLD,
            created_by_id=created_by_id,
            notes=notes,
        )
        for attempt in range(3):
            job = Job(job_number=self._generate_job_number(), **values)
            self.db.add(job)
            try:
                await self.db.commit()
                return await self.get_by_id(job.id)
            except IntegrityError as exc:
                await self.db.rollback()
                if attempt == 2 or "job_number" not in str(exc).lower():
                    raise
        raise RuntimeError("Unable to allocate a unique job number")

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_job(self, job_id: str, **kwargs) -> Job:
        """Update job fields with status-transition validation."""
        job = await self.get_by_id(job_id)
        if not job:
            raise NotFoundError(resource="Job", resource_id=job_id)

        # Validate status transitions
        new_status = kwargs.get("status")
        if new_status is not None:
            new_status_val = new_status.value if hasattr(new_status, 'value') else new_status
            current_status = job.status.value if hasattr(job.status, 'value') else job.status

            # VERIFIED is a terminal state — no transitions allowed
            if current_status == JobStatus.VERIFIED.value:
                raise BadRequestError(
                    message="A verified job cannot be modified."
                )

            # Backward transition COMPLETED → HOLD is not allowed
            if current_status == JobStatus.COMPLETED.value and new_status_val == JobStatus.HOLD.value:
                raise BadRequestError(
                    message="Cannot move a completed job back to Hold."
                )

        for key, value in kwargs.items():
            if value is not None and hasattr(job, key):
                setattr(job, key, value)

        await self.db.commit()
        await self.db.refresh(job)
        return await self.get_by_id(job.id)

    # ------------------------------------------------------------------
    # Complete (mark as done)
    # ------------------------------------------------------------------

    async def complete_job(
        self,
        job_id: str,
        completed_by_id: str,
        accepted: int,
        reshoot: int,
        cut_films: Optional[str],
        cut_films_count: int,
    ) -> Job:
        """
        Mark a job as completed by a person.

        Validates that accepted + reshoot + numeric portion of cut_films == total
        before allowing the job to be validated / issuing the next job.
        """
        job = await self.get_by_id(job_id)
        if not job:
            raise NotFoundError(resource="Job", resource_id=job_id)

        if job.status == JobStatus.COMPLETED or job.status == JobStatus.VERIFIED:
            raise BadRequestError(message="Job is already completed")

        if accepted < 0 or reshoot < 0 or cut_films_count < 0:
            raise BadRequestError(message="Completion quantities cannot be negative")

        completion_sum = accepted + reshoot + cut_films_count

        if completion_sum != job.total:
            raise BadRequestError(
                message=(
                    f"Totals do not match. Job total: {job.total}, "
                    f"Accepted ({accepted}) + Reshoot ({reshoot}) + "
                    f"Cut Films ({cut_films_count}) = {completion_sum}"
                )
            )

        # Store only a balanced completion.
        job.accepted = accepted
        job.reshoot = reshoot
        job.cut_films = cut_films
        job.cut_films_count = cut_films_count
        job.completed_by_id = completed_by_id
        job.completed_at = datetime.now(timezone.utc)
        job.status = JobStatus.COMPLETED

        job.is_validated = True

        await self.db.commit()
        await self.db.refresh(job)
        return await self.get_by_id(job.id)

    # ------------------------------------------------------------------
    # Validate (allow next job to be issued)
    # ------------------------------------------------------------------

    async def validate_job(self, job_id: str) -> Job:
        """
        Validate a completed job – checks totals balance.
        Once validated, the system allows issuing the next job.
        """
        job = await self.get_by_id(job_id)
        if not job:
            raise NotFoundError(resource="Job", resource_id=job_id)

        if job.status != JobStatus.COMPLETED:
            raise BadRequestError(
                message="Only completed jobs can be validated"
            )

        cut_films_count = job.cut_films_count or 0

        completion_sum = (job.accepted or 0) + (job.reshoot or 0) + cut_films_count

        if completion_sum != job.total:
            raise BadRequestError(
                message=(
                    f"Totals do not match. "
                    f"Job total: {job.total}, "
                    f"Accepted ({job.accepted or 0}) + Reshoot ({job.reshoot or 0}) "
                    f"+ Cut Films ({cut_films_count}) = {completion_sum}"
                ),
                details={
                    "total": job.total,
                    "accepted": job.accepted,
                    "reshoot": job.reshoot,
                    "cut_films": job.cut_films,
                    "completion_sum": completion_sum,
                },
            )

        job.is_validated = True
        job.status = JobStatus.VERIFIED
        await self.db.commit()
        await self.db.refresh(job)
        return await self.get_by_id(job.id)

    # ------------------------------------------------------------------
    # Check if new job can be issued
    # ------------------------------------------------------------------

    async def can_issue_new_job(
        self, person_name: Optional[str] = None, assigned_to_id: Optional[str] = None,
    ) -> bool:
        """
        Check whether a new job can be issued.
        Returns False if the person has an unvalidated completed job.
        Uses case-insensitive comparison for person_name.
        """
        query = select(func.count(Job.id)).where(
            and_(
                Job.status == JobStatus.COMPLETED,
                Job.is_validated == False,
            )
        )
        if assigned_to_id:
            query = query.where(Job.assigned_to_id == assigned_to_id)
        elif person_name:
            query = query.where(func.lower(Job.person_name) == person_name.strip().lower())

        result = await self.db.execute(query)
        unvalidated_count = result.scalar_one()
        return unvalidated_count == 0

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        job = await self.get_by_id(job_id)
        if not job:
            raise NotFoundError(resource="Job", resource_id=job_id)

        await self.db.delete(job)
        await self.db.commit()
        return True
