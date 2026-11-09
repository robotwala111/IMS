"""
Audit Service

Handles audit logging for all system actions.
"""

import json
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, and_, distinct, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.audit import AuditLog
from app.models.user import User
from app.services.base_service import BaseService
from app.core.logging import get_correlation_id

# Major/mandatory actions shown in log management.
# Only these actions are displayed — everything else (logins, logouts,
# password changes, email events, minor attribute edits, etc.) is excluded.
IMPORTANT_ACTIONS = {
    # Inventory transactions
    "receipt",
    "issue",
    "return",
    "adjustment",
    # Item / asset lifecycle
    "create",
    "delete",
    "deactivate",
    "permanent_delete",
    "status_change",
    "assign",
    "unassign",
    # Transfers
    "approve",
    "reject",
    "ship",
    "receive",
    "cancel",
    "transfer_blocked",
    # Maintenance & calibration
    "create_maintenance",
    "delete_maintenance",
    "create_calibration",
    # Stock
    "scrap",
    "cycle_count",
    # Security and delivery evidence
    "login_failed",
    "download",
    "email_delivery_failed",
    "scheduler_task_failed",
}


class AuditService(BaseService[AuditLog]):
    """Service for audit log management."""
    
    @property
    def model(self):
        return AuditLog
    
    async def get_by_id(self, id: str) -> Optional[AuditLog]:
        """Get audit log with user info."""
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.id == id)
        )
        return result.scalar_one_or_none()
    
    async def list_logs(
        self,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "occurred_at",
        sort_order: str = "desc",
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        user_id: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        important_only: bool = True,
    ) -> Tuple[List[AuditLog], int]:
        """
        List audit logs with filtering.
        
        Args:
            important_only: If True, excludes routine actions (logins, logouts,
                minor updates) to surface only significant operations.
        
        Returns:
            Tuple of (logs, total_count)
        """
        query = select(AuditLog)
        
        # Show only major/mandatory transactions
        if important_only and not action:
            query = query.where(AuditLog.action.in_(IMPORTANT_ACTIONS))
        
        # Apply filters
        if action:
            query = query.where(AuditLog.action == action)
        
        if resource_type:
            query = query.where(AuditLog.resource_type == resource_type)
        
        if resource_id:
            query = query.where(AuditLog.resource_id == resource_id)
        
        if user_id:
            query = query.where(AuditLog.user_id == user_id)
        
        if start_date:
            start_datetime = datetime.combine(start_date, datetime.min.time())
            query = query.where(AuditLog.occurred_at >= start_datetime)
        
        if end_date:
            end_datetime = datetime.combine(end_date, datetime.max.time())
            query = query.where(AuditLog.occurred_at <= end_datetime)
        
        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await self.db.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        if hasattr(AuditLog, sort_by):
            order_column = getattr(AuditLog, sort_by)
            if sort_order.lower() == "desc":
                query = query.order_by(order_column.desc())
            else:
                query = query.order_by(order_column.asc())
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        result = await self.db.execute(query)
        logs = list(result.scalars().unique().all())
        
        return logs, total
    
    async def get_action_types(self) -> List[str]:
        """Get list of all action types."""
        result = await self.db.execute(
            select(distinct(AuditLog.action)).order_by(AuditLog.action)
        )
        return [row[0] for row in result.all()]
    
    async def get_resource_types(self) -> List[str]:
        """Get list of all resource types."""
        result = await self.db.execute(
            select(distinct(AuditLog.resource_type)).order_by(AuditLog.resource_type)
        )
        return [row[0] for row in result.all()]
    
    async def log_action(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        user_id: Optional[str],
        old_value: Optional[Dict[str, Any]] = None,
        new_value: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        http_method: Optional[str] = None,
        http_path: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.
        
        Args:
            action: Action performed (create, update, delete, etc.)
            resource_type: Type of resource affected
            resource_id: ID of the affected resource
            user_id: User who performed the action
            old_value: Previous state (for updates)
            new_value: New state (for creates/updates)
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Created audit log entry
        """
        # Convert values to JSON-serializable format
        if old_value:
            old_value = self._serialize_value(old_value)
        if new_value:
            new_value = self._serialize_value(new_value)
        changes = self._build_changes(old_value, new_value)

        # Auto-populate user_name and user_email from user_id so the log shows who did what
        resolved_name = None
        resolved_email = None
        resolved_role = None
        if user_id:
            user_result = await self.db.execute(select(User).where(User.id == user_id))
            user_obj = user_result.scalar_one_or_none()
            if user_obj:
                resolved_name = user_obj.name
                resolved_email = user_obj.email
                resolved_role = user_obj.role.value if hasattr(user_obj.role, "value") else str(user_obj.role)

        # Auto-resolve a human-readable resource name from the resource_id
        resolved_resource_name = await self._resolve_resource_name(resource_type, resource_id)

        log = AuditLog(
            id=self.generate_id(),
            correlation_id=get_correlation_id(),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resolved_resource_name,
            user_id=user_id,
            user_name=resolved_name,
            user_email=resolved_email,
            user_role=resolved_role,
            old_value=old_value,
            new_value=new_value,
            changes=changes,
            client_ip=ip_address,
            user_agent=user_agent,
            http_method=http_method,
            http_path=http_path,
            status=status,
            error_message=error_message,
            occurred_at=datetime.now(timezone.utc),
        )
        
        self.db.add(log)
        await self.db.commit()
        await self.db.refresh(log)
        
        return log

    @staticmethod
    def _build_changes(old_value: Optional[str], new_value: Optional[str]) -> Optional[str]:
        old = json.loads(old_value) if old_value else {}
        new = json.loads(new_value) if new_value else {}
        changes = {
            key: {"before": old.get(key), "after": new.get(key)}
            for key in sorted(set(old) | set(new))
            if old.get(key) != new.get(key)
        }
        return json.dumps(changes) if changes else None

    async def verify_integrity(self) -> Dict[str, Any]:
        logs = list((await self.db.execute(select(AuditLog))).scalars().all())
        invalid_ids = [log.id for log in logs if not log.has_valid_integrity_hash()]
        return {"total": len(logs), "valid": len(logs) - len(invalid_ids), "invalid_ids": invalid_ids}

    async def _resolve_resource_name(self, resource_type: str, resource_id: Optional[str]) -> Optional[str]:
        """Look up a human-readable name for the given resource."""
        if not resource_id:
            return None
        # Map resource_type → (table, name_column)
        mapping = {
            "user": ("users", "name"),
            "item": ("items", "name"),
            "category": ("categories", "name"),
            "location": ("locations", "name"),
            "employee": ("employees", "name"),
            "transfer": ("transfers", "transfer_number"),
            "job": ("jobs", "job_number"),
            "purchase_indent": ("purchase_indents", "indent_number"),
            "employee_record": ("employee_records", "title"),
            "asset": ("serialized_assets", "serial_number"),
            "calibration": ("calibration_records", "certificate_number"),
            "maintenance": ("maintenance_records", "work_order_number"),
        }
        info = mapping.get(resource_type)
        if not info:
            return None
        table, col = info
        try:
            result = await self.db.execute(
                text(f"SELECT {col} FROM {table} WHERE id = :rid"),
                {"rid": resource_id},
            )
            row = result.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def _serialize_value(self, value: Dict[str, Any]) -> str:
        """Serialize value for JSON storage."""
        result = {}
        for key, val in value.items():
            if isinstance(val, datetime):
                result[key] = val.isoformat()
            elif isinstance(val, date):
                result[key] = val.isoformat()
            elif hasattr(val, '__dict__'):
                result[key] = str(val)
            else:
                result[key] = val
        return json.dumps(result)
    
    async def get_user_activity_summary(
        self,
        user_id: str,
        days: int = 30,
    ) -> Dict[str, int]:
        """Get activity summary for a user."""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        result = await self.db.execute(
            select(
                AuditLog.action,
                func.count(AuditLog.id).label("count")
            )
            .where(
                and_(
                    AuditLog.user_id == user_id,
                    AuditLog.occurred_at >= start_date,
                )
            )
            .group_by(AuditLog.action)
        )
        
        return {row.action: row.count for row in result.all()}
    
    async def get_resource_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 50,
    ) -> List[AuditLog]:
        """Get audit history for a specific resource."""
        result = await self.db.execute(
            select(AuditLog)
            .where(
                and_(
                    AuditLog.resource_type == resource_type,
                    AuditLog.resource_id == resource_id,
                )
            )
            .order_by(AuditLog.occurred_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
