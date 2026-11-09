"""
Location Service

Handles location management operations.
"""

from typing import Optional, List, Tuple

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.asset import SerializedAsset
from app.models.employee import Employee
from app.models.location import Location
from app.models.purchase_indent import PurchaseIndent, PurchaseIndentStatus
from app.models.stock import Stock
from app.models.transfer import Transfer, TransferStatus
from app.services.base_service import BaseService


class LocationService(BaseService[Location]):
    """Service for location management."""
    
    @property
    def model(self):
        return Location
    
    async def get_by_id(self, id: str) -> Optional[Location]:
        """Get location by ID with assigned users."""
        result = await self.db.execute(
            select(Location).where(Location.id == id).options(selectinload(Location.assigned_users))
        )
        return result.scalar_one_or_none()
    
    async def get_by_code(self, code: str) -> Optional[Location]:
        """Get location by code."""
        result = await self.db.execute(
            select(Location).where(Location.code == code.upper())
        )
        return result.scalar_one_or_none()

    async def get_active_locations(
        self,
        location_ids: Optional[List[str]] = None,
    ) -> List[Location]:
        """Get active locations for dropdowns and selectors."""
        query = (
            select(Location)
            .options(selectinload(Location.assigned_users))
            .where(Location.is_active.is_(True))
            .order_by(Location.name.asc())
        )

        if location_ids is not None:
            query = query.where(Location.id.in_(location_ids))

        result = await self.db.execute(query)
        return list(result.scalars().unique().all())
    
    async def list_locations(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "name",
        sort_order: str = "asc",
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
        location_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Location], int]:
        """
        List locations with filtering.
        
        Args:
            page: Page number
            page_size: Items per page
            sort_by: Sort field
            sort_order: Sort direction
            is_active: Filter by active status
            search: Search in name, code, city
            location_ids: Filter to specific locations (for RBAC)
            
        Returns:
            Tuple of (locations, total_count)
        """
        query = select(Location)
        
        # Filter by location access
        if location_ids is not None:
            query = query.where(Location.id.in_(location_ids))
        
        # Apply filters
        if is_active is not None:
            query = query.where(Location.is_active == is_active)
        
        if search:
            search_pattern = f"%{search}%"
            query = query.where(
                or_(
                    Location.name.ilike(search_pattern),
                    Location.code.ilike(search_pattern),
                    Location.city.ilike(search_pattern),
                    Location.address.ilike(search_pattern),
                )
            )
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(Location, sort_by):
            order_column = getattr(Location, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        query = query.options(selectinload(Location.assigned_users))
        
        result = await self.db.execute(query)
        locations = list(result.scalars().all())
        
        return locations, total
    
    async def create_location(
        self,
        name: str,
        code: str,
        address: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        postal_code: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Location:
        """
        Create a new location.
        
        Returns:
            Created location
            
        Raises:
            BadRequestError: If code already exists
        """
        # Check code uniqueness
        existing = await self.get_by_code(code)
        if existing:
            raise BadRequestError(message=f"Location code '{code}' already exists")
        
        location = Location(
            id=self.generate_id(),
            name=name,
            code=code.upper(),
            address=address,
            city=city,
            state=state,
            country=country,
            postal_code=postal_code,
            phone=phone,
            email=email,
            is_active=True,
        )
        
        self.db.add(location)
        await self.db.commit()
        await self.db.refresh(location)
        
        return location
    
    async def update_location(
        self,
        location_id: str,
        name: Optional[str] = None,
        code: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        country: Optional[str] = None,
        postal_code: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Location:
        """
        Update a location.
        
        Returns:
            Updated location
            
        Raises:
            NotFoundError: If location not found
            BadRequestError: If code conflicts
        """
        location = await self.get_by_id(location_id)
        if not location:
            raise NotFoundError(resource="Location", resource_id=location_id)
        
        # Check code uniqueness
        if code and code.upper() != location.code:
            existing = await self.get_by_code(code)
            if existing:
                raise BadRequestError(message=f"Location code '{code}' already exists")
            location.code = code.upper()
        
        # Update fields
        if name is not None:
            location.name = name
        if address is not None:
            location.address = address
        if city is not None:
            location.city = city
        if state is not None:
            location.state = state
        if country is not None:
            location.country = country
        if postal_code is not None:
            location.postal_code = postal_code
        if phone is not None:
            location.phone = phone
        if email is not None:
            location.email = email
        if is_active is not None:
            location.is_active = is_active
        
        await self.db.commit()
        await self.db.refresh(location)
        
        return location
    
    async def delete_location(self, location_id: str) -> bool:
        """
        Soft delete a location.
        
        Returns:
            True if successful
            
        Raises:
            NotFoundError: If location not found
        """
        location = await self.get_by_id(location_id)
        if not location:
            raise NotFoundError(resource="Location", resource_id=location_id)
        
        location.is_active = False
        await self.db.commit()
        
        return True

    async def has_stock(self, location_id: str) -> bool:
        """Check whether a location has any stock quantity or reservation."""
        result = await self.db.execute(
            select(func.count(Stock.id)).where(
                Stock.location_id == location_id,
                or_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_reserved > 0,
                    Stock.quantity_on_order > 0,
                ),
            )
        )
        return result.scalar_one() > 0

    async def get_deactivation_blockers(self, location_id: str) -> List[str]:
        """Return active operational dependencies that prevent deactivation."""
        blockers: List[str] = []
        checks = (
            ("existing stock", select(func.count(Stock.id)).where(
                Stock.location_id == location_id,
                or_(
                    Stock.quantity_on_hand > 0,
                    Stock.quantity_reserved > 0,
                    Stock.quantity_on_order > 0,
                ),
            )),
            ("serialized assets", select(func.count(SerializedAsset.id)).where(
                SerializedAsset.location_id == location_id
            )),
            ("active employees", select(func.count(Employee.id)).where(
                Employee.location_id == location_id,
                Employee.is_active.is_(True),
            )),
            ("pending transfers", select(func.count(Transfer.id)).where(
                or_(
                    Transfer.from_location_id == location_id,
                    Transfer.to_location_id == location_id,
                ),
                Transfer.status.in_((
                    TransferStatus.REQUESTED,
                    TransferStatus.APPROVED,
                    TransferStatus.IN_TRANSIT,
                    TransferStatus.PARTIALLY_RECEIVED,
                )),
            )),
            ("active purchase indents", select(func.count(PurchaseIndent.id)).where(
                or_(
                    PurchaseIndent.requested_by_location_id == location_id,
                    PurchaseIndent.supplying_location_id == location_id,
                ),
                PurchaseIndent.status.in_((
                    PurchaseIndentStatus.DRAFT,
                    PurchaseIndentStatus.SUBMITTED,
                    PurchaseIndentStatus.APPROVED,
                    PurchaseIndentStatus.PARTIALLY_FULFILLED,
                )),
            )),
        )
        for label, query in checks:
            if (await self.db.execute(query)).scalar_one() > 0:
                blockers.append(label)
        return blockers
