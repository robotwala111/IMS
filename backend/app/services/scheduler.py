"""
Scheduler Service

Handles scheduled background tasks like:
- Calibration due date notifications
- Stock level alerts
- Report generation
- Data cleanup
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional
from threading import Thread, Event
from uuid import uuid4

from sqlalchemy import and_, select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import database_url, postgres_connect_args

logger = get_logger(__name__)


class ScheduledTask:
    """Represents a scheduled task."""
    
    def __init__(
        self,
        name: str,
        func: Callable,
        interval_seconds: int,
        enabled: bool = True,
    ):
        self.name = name
        self.func = func
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self.last_run: Optional[datetime] = None
        self.next_run: Optional[datetime] = None
        self.run_count: int = 0
        self.error_count: int = 0


class SchedulerService:
    """
    Simple scheduler service for background tasks.
    
    In production, this could be replaced with Celery or APScheduler.
    """
    
    def __init__(self):
        self._tasks: Dict[str, ScheduledTask] = {}
        self._running = False
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._engine = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None
    
    def register_task(
        self,
        name: str,
        func: Callable,
        interval_seconds: int,
        enabled: bool = True,
    ) -> None:
        """Register a scheduled task."""
        task = ScheduledTask(
            name=name,
            func=func,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )
        self._tasks[name] = task
        logger.info(f"Registered scheduled task: {name} (interval: {interval_seconds}s)")
    
    def unregister_task(self, name: str) -> None:
        """Unregister a scheduled task."""
        if name in self._tasks:
            del self._tasks[name]
            logger.info(f"Unregistered scheduled task: {name}")
    
    def enable_task(self, name: str) -> None:
        """Enable a scheduled task."""
        if name in self._tasks:
            self._tasks[name].enabled = True
            logger.info(f"Enabled scheduled task: {name}")
    
    def disable_task(self, name: str) -> None:
        """Disable a scheduled task."""
        if name in self._tasks:
            self._tasks[name].enabled = False
            logger.info(f"Disabled scheduled task: {name}")
    
    def get_task_status(self) -> List[Dict[str, Any]]:
        """Get status of all scheduled tasks."""
        return [
            {
                "name": task.name,
                "enabled": task.enabled,
                "interval_seconds": task.interval_seconds,
                "last_run": task.last_run.isoformat() if task.last_run else None,
                "next_run": task.next_run.isoformat() if task.next_run else None,
                "run_count": task.run_count,
                "error_count": task.error_count,
            }
            for task in self._tasks.values()
        ]
    
    def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return
        
        self._running = True
        self._stop_event.clear()
        
        # Register default tasks
        self._register_default_tasks()
        
        # Start scheduler thread
        self._thread = Thread(target=self._run_scheduler, daemon=True)
        self._thread.start()
        
        logger.info("Scheduler started")
    
    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if not self._running:
            return
        
        logger.info("Stopping scheduler...")
        self._running = False
        self._stop_event.set()
        
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info("Scheduler stopped")
    
    def _register_default_tasks(self) -> None:
        """Register default scheduled tasks."""
        # Calibration check - every hour
        self.register_task(
            name="calibration_check",
            func=self._check_calibration_due,
            interval_seconds=3600,
        )
        
        # Stock level check - daily (once per day) using configured interval
        self.register_task(
            name="stock_level_check",
            func=self._check_stock_levels,
            interval_seconds=max(1, settings.LOW_STOCK_CHECK_INTERVAL_HOURS) * 3600,
        )

        self.register_task(
            name="vision_certificate_reminder",
            func=self._check_vision_certificate_due,
            interval_seconds=max(1, settings.VISION_CERTIFICATE_REMINDER_INTERVAL_HOURS) * 3600,
        )

        # Return date reminder - every hour
        self.register_task(
            name="return_date_reminder",
            func=self._check_return_date_reminders,
            interval_seconds=3600,
        )
        
        # Notification cleanup - daily
        self.register_task(
            name="notification_cleanup",
            func=self._cleanup_old_notifications,
            interval_seconds=86400,
        )

        self.register_task(
            name="email_outbox_delivery",
            func=self._process_email_outbox,
            interval_seconds=60,
        )
        
        # Audit log archival - daily
        self.register_task(
            name="audit_archival",
            func=self._archive_old_audit_logs,
            interval_seconds=86400,
        )

        # Archive warning check - daily (fires warning email N days before quarterly archive)
        self.register_task(
            name="archive_warning_check",
            func=self._check_archive_warning,
            interval_seconds=86400,
        )

        # Quarterly archive runner - daily (only acts on quarter boundary day)
        self.register_task(
            name="quarterly_archive",
            func=self._run_quarterly_archive,
            interval_seconds=86400,
        )

        # Audit registers - daily check, sends once per configured interval
        self.register_task(
            name="register_email_delivery",
            func=self._send_periodic_registers,
            interval_seconds=86400,
        )

        # Monthly generated PI/DC/register ZIP email - daily check, acts on month boundary
        self.register_task(
            name="monthly_generated_documents",
            func=self._send_monthly_generated_documents,
            interval_seconds=86400,
        )

        self.register_task(
            name="generated_document_cleanup",
            func=self._cleanup_generated_documents,
            interval_seconds=86400,
        )
    
    def _run_scheduler(self) -> None:
        """Main scheduler loop."""
        logger.info("Scheduler loop started")
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        engine_kwargs = {"poolclass": NullPool}
        if not settings.is_sqlite:
            engine_kwargs["connect_args"] = postgres_connect_args()
        self._engine = create_async_engine(database_url, **engine_kwargs)
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        try:
            while not self._stop_event.is_set():
                now = datetime.utcnow()

                for task in self._tasks.values():
                    if not task.enabled:
                        continue

                    should_run = (
                        task.last_run is None
                        or (now - task.last_run).total_seconds() >= task.interval_seconds
                    )
                    if should_run:
                        self._execute_task(task)

                self._stop_event.wait(timeout=10)
        finally:
            if self._engine is not None:
                self._loop.run_until_complete(self._engine.dispose())
            self._loop.close()
            self._loop = None
            self._engine = None
            self._session_factory = None

    def _run_async(self, coroutine) -> None:
        """Run a scheduler coroutine on the scheduler's persistent event loop."""
        if self._loop is None:
            raise RuntimeError("Scheduler event loop is not initialized")
        self._loop.run_until_complete(coroutine)

    @asynccontextmanager
    async def _db_session(self):
        """Yield a session owned by, and cleaned up on, the scheduler loop.

        Scheduler jobs run in a dedicated thread and event loop, so they must
        never borrow the web application's session factory.  Explicit rollback
        and close here also ensure a failed job cannot leave an open transaction
        or connection behind for the next run.
        """
        if self._session_factory is None:
            raise RuntimeError("Scheduler database session is not initialized")

        session = self._session_factory()
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        finally:
            await session.close()
    
    def _execute_task(self, task: ScheduledTask) -> None:
        """Execute a scheduled task."""
        logger.debug(f"Executing scheduled task: {task.name}")
        
        try:
            task.func()
            task.run_count += 1
            task.last_run = datetime.utcnow()
            logger.debug(f"Task {task.name} completed successfully")
        except Exception as e:
            task.error_count += 1
            logger.exception(f"Error executing task {task.name}: {e}")
            try:
                self._run_async(self._audit_scheduler_failure(task.name, str(e)))
            except Exception:
                logger.exception("Failed to persist scheduler failure audit")

    async def _audit_scheduler_failure(self, task_name: str, error: str) -> None:
        from app.models.audit import AuditLog

        async with self._db_session() as db:
            db.add(AuditLog(
                id=str(uuid4()), action="scheduler_task_failed",
                resource_type="scheduler_task", resource_id=None,
                resource_name=task_name, user_email="system@scheduler", user_role="system",
                new_value=json.dumps({"task_name": task_name}), status="failure",
                error_message=error, occurred_at=datetime.utcnow(),
            ))
            await db.commit()
    
    # Default task implementations
    def _process_email_outbox(self) -> None:
        """Deliver pending/failed email notifications from the durable outbox."""
        self._run_async(self._async_process_email_outbox())

    async def _async_process_email_outbox(self) -> None:
        from app.services.notification_service import NotificationService

        async with self._db_session() as db:
            result = await NotificationService(db).process_email_outbox()
            if result["claimed"]:
                logger.info("Email outbox processed: %s", result)

    def _check_calibration_due(self) -> None:
        """Check for assets with calibration due or expired and send email alerts."""
        logger.debug("Checking calibration due dates...")
        try:
            self._run_async(self._async_check_calibration_due())
        except Exception as e:
            logger.exception(f"Error checking calibration due dates: {e}")

    async def _async_check_calibration_due(self) -> None:
        """
        Query assets whose latest calibration is expired or due within CALIBRATION_ALERT_DAYS.
        Groups by location and emails location managers; sends full summary to HQ/Admin.
        """
        from collections import defaultdict
        from app.models.asset import SerializedAsset
        from app.models.calibration import CalibrationRecord
        from app.models.item import Item
        from app.models.location import Location
        from app.models.notification import Notification, NotificationChannel, NotificationStatus, NotificationType
        from app.models.user import User, UserRole, user_location_association
        from app.services.email_service import get_email_service
        from sqlalchemy.orm import selectinload

        alert_days = settings.CALIBRATION_ALERT_DAYS
        today = date.today()
        now = datetime.utcnow()
        threshold = today + timedelta(days=alert_days)
        interval_window_start = now - timedelta(hours=24)

        async with self._db_session() as db:
            # Fetch latest calibration record per asset using a subquery
            # Get all calibration records due within threshold or already expired
            cal_q = (
                select(CalibrationRecord)
                .where(CalibrationRecord.due_at <= threshold)
                .order_by(CalibrationRecord.asset_id, CalibrationRecord.due_at.desc())
            )
            cal_result = await db.execute(cal_q)
            all_cal_records = cal_result.scalars().all()

            if not all_cal_records:
                logger.debug("No calibration records approaching due date")
                return

            # Keep only the latest record per asset
            latest_per_asset: dict = {}
            for rec in all_cal_records:
                if rec.asset_id not in latest_per_asset:
                    latest_per_asset[rec.asset_id] = rec

            if not latest_per_asset:
                return

            # Fetch corresponding assets
            asset_ids = list(latest_per_asset.keys())
            asset_q = (
                select(SerializedAsset)
                .options(
                    selectinload(SerializedAsset.item),
                    selectinload(SerializedAsset.location),
                )
                .where(SerializedAsset.id.in_(asset_ids))
            )
            asset_result = await db.execute(asset_q)
            assets = asset_result.scalars().all()

            if not assets:
                return

            # Build location → items map
            location_items: dict = defaultdict(list)
            for asset in assets:
                if not asset.item or not asset.item.requires_calibration:
                    continue
                cal_rec = latest_per_asset.get(asset.id)
                if not cal_rec:
                    continue
                days_until_due = (cal_rec.due_at - today).days
                location_items[asset.location_id].append({
                    'serial_number': asset.serial_number,
                    'item_name': asset.item.name if asset.item else 'Unknown',
                    'item_sku': asset.item.sku if asset.item else '-',
                    'location_name': asset.location.name if asset.location else 'Unknown',
                    'location_id': asset.location_id,
                    'due_date': str(cal_rec.due_at),
                    'days_until_due': days_until_due,
                    'status': 'expired' if days_until_due < 0 else 'due_soon',
                })

            if not location_items:
                logger.debug("No calibration-required assets approaching due date")
                return

            logger.info(
                f"Found calibration alerts across {len(location_items)} location(s)"
            )
            email_service = get_email_service()

            # 1. Location managers — per-location emails
            for loc_id, items in location_items.items():
                location_name = items[0]['location_name']
                mgr_q = (
                    select(User)
                    .join(user_location_association, User.id == user_location_association.c.user_id)
                    .where(
                        user_location_association.c.location_id == loc_id,
                        User.is_active == True,  # noqa: E712
                        User.role == UserRole.LOCATION_MANAGER,
                    )
                )
                mgr_result = await db.execute(mgr_q)
                managers = mgr_result.scalars().all()
                mgr_emails = [u.email for u in managers if u.email]
                if mgr_emails:
                    email_service.send_calibration_alert(mgr_emails, items, location_name=location_name)
                    logger.info(
                        f"Calibration alert sent to managers {mgr_emails} for '{location_name}' "
                        f"({len(items)} assets)"
                    )
                for manager in managers:
                    duplicate_result = await db.execute(
                        select(Notification.id)
                        .where(
                            and_(
                                Notification.notification_type == NotificationType.CALIBRATION_DUE,
                                Notification.recipient_id == manager.id,
                                Notification.reference_type == "location",
                                Notification.reference_id == loc_id,
                                Notification.created_at >= interval_window_start,
                            )
                        )
                        .limit(1)
                    )
                    if duplicate_result.scalar_one_or_none() is not None:
                        continue
                    db.add(
                        Notification(
                            id=str(uuid4()),
                            notification_type=NotificationType.CALIBRATION_DUE,
                            channel=NotificationChannel.IN_APP,
                            recipient_id=manager.id,
                            recipient_email=manager.email,
                            subject=f"Calibration due: {location_name}",
                            body=f"{len(items)} instrument(s) require calibration attention at {location_name}.",
                            payload=json.dumps({"location_id": loc_id, "items": items}),
                            status=NotificationStatus.SENT,
                            sent_at=now,
                            reference_type="location",
                            reference_id=loc_id,
                        )
                    )

            # 2. Admins / Head Office — full summary
            hq_q = select(User).where(
                User.is_active == True,  # noqa: E712
                User.role.in_([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]),
            )
            hq_result = await db.execute(hq_q)
            hq_users = hq_result.scalars().all()
            hq_emails = list({u.email for u in hq_users if u.email})
            all_items = [item for items in location_items.values() for item in items]
            if hq_emails:
                email_service.send_calibration_alert(hq_emails, all_items)
                logger.info(
                    f"Calibration summary sent to HQ {hq_emails} ({len(all_items)} assets)"
                )
            for hq_user in hq_users:
                duplicate_result = await db.execute(
                    select(Notification.id)
                    .where(
                        and_(
                            Notification.notification_type == NotificationType.CALIBRATION_DUE,
                            Notification.recipient_id == hq_user.id,
                            Notification.reference_type == "calibration_summary",
                            Notification.reference_id == "company",
                            Notification.created_at >= interval_window_start,
                        )
                    )
                    .limit(1)
                )
                if duplicate_result.scalar_one_or_none() is not None:
                    continue
                db.add(
                    Notification(
                        id=str(uuid4()),
                        notification_type=NotificationType.CALIBRATION_DUE,
                        channel=NotificationChannel.IN_APP,
                        recipient_id=hq_user.id,
                        recipient_email=hq_user.email,
                        subject="Company calibration alerts",
                        body=f"{len(all_items)} instrument(s) require calibration attention.",
                        payload=json.dumps({"items": all_items}),
                        status=NotificationStatus.SENT,
                        sent_at=now,
                        reference_type="calibration_summary",
                        reference_id="company",
                    )
                )
            await db.commit()
    
    def _check_stock_levels(self) -> None:
        """Check for low stock levels and send email alerts."""
        logger.debug("Checking stock levels...")
        
        try:
            # Run async function in new event loop
            self._run_async(self._async_check_stock_levels())
        except Exception as e:
            logger.exception(f"Error checking stock levels: {e}")
    
    async def _async_check_stock_levels(self) -> None:
        """Periodic low-stock check."""
        from app.services.stock_service import StockService

        async with self._db_session() as db:
            stock_service = StockService(db)
            result = await stock_service.send_low_stock_alerts()
            if result["count"] == 0:
                logger.debug("No low stock items found")
                return
            logger.info(
                "Low stock alert sent for %s item(s) to %s recipient(s)",
                result["count"],
                result["recipients"],
            )
    
    def _cleanup_old_notifications(self) -> None:
        """Clean up old read notifications from the database."""
        logger.debug("Cleaning up old notifications...")
        try:
            self._run_async(self._async_cleanup_old_notifications())
        except Exception as e:
            logger.exception(f"Error cleaning up notifications: {e}")

    async def _async_cleanup_old_notifications(self) -> None:
        """
        Delete notifications that are:
        - READ and older than 30 days
        - SENT/FAILED and older than 90 days (delivery log pruning)
        """
        from app.models.notification import Notification, NotificationStatus
        from sqlalchemy import delete as sa_delete

        now = datetime.utcnow()
        read_cutoff = now - timedelta(days=30)
        sent_cutoff = now - timedelta(days=90)

        async with self._db_session() as db:
            # Delete old READ notifications
            read_del = await db.execute(
                sa_delete(Notification).where(
                    Notification.status == NotificationStatus.READ,
                    Notification.read_at <= read_cutoff,
                )
            )
            # Delete stale SENT / FAILED delivery records
            sent_del = await db.execute(
                sa_delete(Notification).where(
                    Notification.status.in_([NotificationStatus.SENT, NotificationStatus.FAILED]),
                    Notification.sent_at <= sent_cutoff,
                )
            )
            await db.commit()
            total = (read_del.rowcount or 0) + (sent_del.rowcount or 0)
            if total:
                logger.info(f"Deleted {total} stale notification records")
            else:
                logger.debug("No stale notifications to clean up")

    def _archive_old_audit_logs(self) -> None:
        """Archive (delete) audit logs older than the configured retention period."""
        logger.debug("Archiving old audit logs...")
        try:
            self._run_async(self._async_archive_old_audit_logs())
        except Exception as e:
            logger.exception(f"Error archiving audit logs: {e}")

    async def _async_archive_old_audit_logs(self) -> None:
        """
        Audit logs are append-only. Quarterly archives provide external copies,
        but operational evidence is retained and never automatically deleted.
        """
        logger.debug("Audit logs retained: append-only policy is active")

    def _send_periodic_registers(self) -> None:
        """Send stock and purchase register workbooks on the configured interval."""
        logger.debug("Checking periodic register email delivery...")
        try:
            self._run_async(self._async_send_periodic_registers())
        except Exception as e:
            logger.exception(f"Error sending periodic register workbooks: {e}")

    async def _async_send_periodic_registers(self) -> None:
        from app.models.notification import Notification, NotificationChannel, NotificationStatus, NotificationType
        from app.schemas.reports import ReportFormat
        from app.services.archive_service import get_archive_recipients
        from app.services.email_service import get_email_service
        from app.services.report_service import ReportService

        interval_days = max(1, settings.REGISTER_EMAIL_INTERVAL_DAYS)
        now = datetime.utcnow()
        dedupe_start = now - timedelta(days=interval_days)

        async with self._db_session() as db:
            duplicate_result = await db.execute(
                select(Notification.id)
                .where(
                    and_(
                        Notification.notification_type == NotificationType.SYSTEM_ALERT,
                        Notification.reference_type == "register_email_delivery",
                        Notification.created_at >= dedupe_start,
                    )
                )
                .limit(1)
            )
            if duplicate_result.scalar_one_or_none() is not None:
                logger.debug("Periodic register email already sent inside configured interval")
                return

            recipients = await get_archive_recipients(self._session_factory)
            if not recipients:
                logger.error("Periodic register email skipped: no recipients found")
                return

            report_service = ReportService(db)
            stock_content, stock_filename, stock_type = await report_service.export_inventory_report(
                format=ReportFormat.EXCEL,
                include_zero_stock=True,
            )
            purchase_content, purchase_filename, purchase_type = await report_service.export_purchase_register()

            subject = f"[ScienceTech-IMS] Stock and Purchase Registers - {now.strftime('%d %b %Y')}"
            body_text = (
                "Please find the latest Stock Register and Purchase Register attached.\n"
                f"This automatic email is sent every {interval_days} day(s)."
            )
            body_html = (
                "<p>Please find the latest <strong>Stock Register</strong> and "
                "<strong>Purchase Register</strong> attached.</p>"
                f"<p>This automatic email is sent every {interval_days} day(s).</p>"
            )

            email_service = get_email_service()
            sent = email_service.send_email_with_attachments(
                to_emails=recipients,
                subject=subject,
                body_html=body_html,
                body_text=body_text,
                attachments=[
                    (stock_filename, stock_content.getvalue(), stock_type),
                    (purchase_filename, purchase_content.getvalue(), purchase_type),
                ],
            )

            db.add(
                Notification(
                    id=str(uuid4()),
                    notification_type=NotificationType.SYSTEM_ALERT,
                    channel=NotificationChannel.EMAIL,
                    recipient_id=None,
                    recipient_email=", ".join(recipients),
                    subject=subject,
                    body=body_text,
                    payload=json.dumps(
                        {
                            "stock_register": stock_filename,
                            "purchase_register": purchase_filename,
                            "interval_days": interval_days,
                        }
                    ),
                    status=NotificationStatus.SENT if sent else NotificationStatus.FAILED,
                    sent_at=now if sent else None,
                    error_message=None if sent else "Failed to send register email",
                    reference_type="register_email_delivery",
                    reference_id=now.strftime("%Y%m%d"),
                )
            )
            await self._log_system_audit(
                db=db,
                action="register_email_sent",
                resource_type="reports",
                resource_id=now.strftime("%Y%m%d"),
                payload={
                    "recipients": len(recipients),
                    "sent": sent,
                    "stock_register": stock_filename,
                    "purchase_register": purchase_filename,
                },
            )
            await db.commit()

    def _send_monthly_generated_documents(self) -> None:
        """Send previous month's generated document ZIPs to active admin users."""
        logger.debug("Checking monthly generated document delivery...")
        try:
            self._run_async(self._async_send_monthly_generated_documents())
        except Exception as e:
            logger.exception(f"Error sending monthly generated documents: {e}")

    async def _async_send_monthly_generated_documents(self) -> None:
        if datetime.utcnow().day != 1:
            return

        from app.models.generated_document import GeneratedDocument
        from app.services.generated_document_service import GeneratedDocumentService

        today = date.today()
        previous_month_last = today.replace(day=1) - timedelta(days=1)
        year = previous_month_last.year
        month = previous_month_last.month

        async with self._db_session() as db:
            service = GeneratedDocumentService(db)
            period_start, _ = service.month_bounds(year, month)
            existing_result = await db.execute(
                select(GeneratedDocument.id)
                .where(
                    GeneratedDocument.document_type == "MONTHLY_ZIP",
                    GeneratedDocument.period_start == period_start,
                    GeneratedDocument.emailed_at.is_not(None),
                )
                .limit(1)
            )
            if existing_result.scalar_one_or_none():
                logger.info("Monthly generated documents already sent for %s-%02d", year, month)
                return

            result = await service.send_monthly_zip_to_admins(year=year, month=month)
            logger.info("Monthly generated document email result: %s", result)

    def _cleanup_generated_documents(self) -> None:
        """Delete expired generated document copies."""
        logger.debug("Checking generated document retention cleanup...")
        try:
            self._run_async(self._async_cleanup_generated_documents())
        except Exception as e:
            logger.exception(f"Error cleaning generated documents: {e}")

    async def _async_cleanup_generated_documents(self) -> None:
        from app.services.generated_document_service import GeneratedDocumentService

        async with self._db_session() as db:
            service = GeneratedDocumentService(db)
            deleted = await service.cleanup_expired()
            if deleted:
                logger.info("Deleted %s expired generated document copies", deleted)

    def _check_vision_certificate_due(self) -> None:
        """Check vision certificates nearing 3-month due and notify managers."""
        logger.debug("Checking vision certificate reminders...")

        try:
            self._run_async(self._async_check_vision_certificate_due())
        except Exception as e:
            logger.exception(f"Error checking vision certificate reminders: {e}")

    async def _log_system_audit(
        self,
        db,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        payload: Dict[str, Any],
    ) -> None:
        """Write scheduler audit log entries."""
        from app.models.audit import AuditLog

        audit = AuditLog(
            id=str(uuid4()),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            user_id=None,
            user_email="system@scheduler",
            user_role="system",
            old_value=None,
            new_value=json.dumps(payload),
            status="success",
            occurred_at=datetime.utcnow(),
        )
        db.add(audit)

    async def _async_check_vision_certificate_due(self) -> None:
        """Send daily reminders for personnel qualifications nearing expiry."""
        from app.models.employee_record import EmployeeRecord, EmployeeRecordType
        from app.models.location import Location
        from app.models.notification import Notification, NotificationChannel, NotificationStatus, NotificationType
        from app.models.user import User, UserRole
        from app.services.email_service import get_email_service
        from sqlalchemy.orm import selectinload

        now = datetime.utcnow()
        today = now.date()
        interval_window_start = now - timedelta(hours=max(1, settings.VISION_CERTIFICATE_REMINDER_INTERVAL_HOURS))

        async with self._db_session() as db:
            query = (
                select(EmployeeRecord)
                .options(
                    selectinload(EmployeeRecord.user).selectinload(User.assigned_locations),
                    selectinload(EmployeeRecord.employee),
                )
                .where(
                    and_(
                        EmployeeRecord.record_type == EmployeeRecordType.PERSONAL_QUALIFICATION,
                        EmployeeRecord.is_active == True,
                    )
                )
            )
            result = await db.execute(query)
            records = list(result.scalars().unique().all())

            if not records:
                return

            hq_result = await db.execute(
                select(User).where(
                    and_(
                        User.is_active == True,
                        User.role.in_([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]),
                    )
                )
            )
            hq_users = list(hq_result.scalars().all())
            email_service = get_email_service()
            notification_count = 0

            for record in records:
                expiry = record.expiry_date
                if not expiry:
                    continue

                title = (record.title or "").strip().lower()
                alert_days = 90 if "level 3" in title or "level iii" in title else 15
                due_threshold = today + timedelta(days=alert_days)
                if expiry < today or expiry > due_threshold:
                    continue

                recipients: List[User] = []
                if record.user and record.user.is_active:
                    recipients.append(record.user)

                loc_id = None
                if record.user and record.user.assigned_locations:
                    loc_id = record.user.assigned_locations[0].id
                elif record.employee and record.employee.location_id:
                    loc_id = record.employee.location_id

                if loc_id:
                    loc_mgr_result = await db.execute(
                        select(User).where(
                            and_(
                                User.is_active == True,
                                User.role == UserRole.LOCATION_MANAGER,
                                User.assigned_locations.any(Location.id == loc_id),
                            )
                        )
                    )
                    recipients.extend(list(loc_mgr_result.scalars().unique().all()))

                recipients.extend(hq_users)
                unique_recipients = list({u.id: u for u in recipients if u and u.id}.values())
                if not unique_recipients:
                    continue

                employee_name = record.user_name or "Unknown Employee"
                days_left = (expiry - today).days
                method_match = str(record.notes or "").split("Method:", 1)
                method = method_match[1].splitlines()[0].strip().upper() if len(method_match) > 1 else "-"
                subject = f"[ScienceTech-IMS] Personnel certificate due: {employee_name}"
                body = (
                    f"Personnel certificate for {employee_name} ({method}, {record.title}) is due on "
                    f"{expiry.isoformat()} (in {days_left} day(s)). This reminder repeats daily until updated."
                )

                email_recipients: List[str] = []
                for recipient in unique_recipients:
                    duplicate_result = await db.execute(
                        select(Notification.id)
                        .where(
                            and_(
                                Notification.notification_type == NotificationType.EXPIRY_ALERT,
                                Notification.recipient_id == recipient.id,
                                Notification.reference_type == "employee_record",
                                Notification.reference_id == record.id,
                                Notification.created_at >= interval_window_start,
                            )
                        )
                        .limit(1)
                    )
                    if duplicate_result.scalar_one_or_none() is not None:
                        continue

                    if recipient.email:
                        email_recipients.append(recipient.email)

                    db.add(
                        Notification(
                            id=str(uuid4()),
                            notification_type=NotificationType.EXPIRY_ALERT,
                            channel=NotificationChannel.IN_APP,
                            recipient_id=recipient.id,
                            recipient_email=recipient.email,
                            subject=subject,
                            body=body,
                            payload=json.dumps(
                                {
                                    "employee_record_id": record.id,
                                    "employee_name": employee_name,
                                    "record_type": "personal_qualification",
                                    "method": method,
                                    "title": record.title,
                                    "expiry_date": expiry.isoformat(),
                                    "days_left": days_left,
                                }
                            ),
                            status=NotificationStatus.SENT,
                            sent_at=now,
                            reference_type="employee_record",
                            reference_id=record.id,
                        )
                    )
                    notification_count += 1

                unique_emails = sorted(set(email_recipients))
                if unique_emails:
                    sent = email_service.send_email(
                        to_emails=unique_emails,
                        subject=subject,
                        body_html=f"<p>{body}</p>",
                        body_text=body,
                    )
                    db.add(
                        Notification(
                            id=str(uuid4()),
                            notification_type=NotificationType.EXPIRY_ALERT,
                            channel=NotificationChannel.EMAIL,
                            recipient_id=None,
                            recipient_email=", ".join(unique_emails),
                            subject=subject,
                            body=body,
                            payload=json.dumps({"employee_record_id": record.id}),
                            status=NotificationStatus.SENT if sent else NotificationStatus.FAILED,
                            sent_at=now if sent else None,
                            error_message=None if sent else "Failed to send personnel certificate reminder",
                            reference_type="employee_record",
                            reference_id=record.id,
                        )
                    )

            await db.commit()
            if notification_count:
                logger.info(f"Personnel certificate reminders sent: {notification_count}")

    def _check_return_date_reminders(self) -> None:
        """Check equipment transfers approaching return date and send reminders."""
        logger.debug("Checking return date reminders...")

        try:
            self._run_async(self._async_check_return_date_reminders())
        except Exception as e:
            logger.exception(f"Error checking return date reminders: {e}")

    async def _async_check_return_date_reminders(self) -> None:
        """Send reminders for equipment transfers approaching return date."""
        from app.models.transfer import Transfer, TransferStatus
        from app.models.notification import (
            Notification,
            NotificationChannel,
            NotificationStatus,
            NotificationType,
        )
        from app.models.user import User, UserRole
        from app.services.email_service import get_email_service
        from sqlalchemy.orm import selectinload

        now = datetime.utcnow()

        async with self._db_session() as db:
            # Query active equipment transfers with a return date and reminder configured
            transfers_query = (
                select(Transfer)
                .where(
                    and_(
                        Transfer.transfer_type == "equipment",
                        Transfer.return_date.isnot(None),
                        Transfer.status.notin_([
                            TransferStatus.CANCELLED,
                            TransferStatus.REJECTED,
                        ]),
                    )
                )
            )
            transfers_result = await db.execute(transfers_query)
            transfers = list(transfers_result.scalars().all())

            if not transfers:
                logger.debug("No equipment transfers with return dates found")
                return

            email_service = get_email_service()
            reminder_count = 0

            for transfer in transfers:
                reminder_days = transfer.return_reminder_days or 3
                return_date = transfer.return_date.replace(tzinfo=None) if transfer.return_date.tzinfo else transfer.return_date
                days_until_return = (return_date - now).days

                # Send reminder if within the reminder window (including overdue)
                if days_until_return > reminder_days:
                    continue

                # Deduplicate: check if a reminder was already sent in the last 24 hours
                dedup_window = now - timedelta(hours=24)
                duplicate_query = (
                    select(Notification.id)
                    .where(
                        and_(
                            Notification.notification_type == NotificationType.RETURN_DATE_DUE,
                            Notification.reference_type == "transfer",
                            Notification.reference_id == transfer.id,
                            Notification.created_at >= dedup_window,
                        )
                    )
                    .limit(1)
                )
                duplicate_result = await db.execute(duplicate_query)
                if duplicate_result.scalar_one_or_none() is not None:
                    continue

                # Find recipients: admin/manager users + the requester
                recipients_query = select(User).where(
                    and_(
                        User.is_active == True,
                        or_(
                            User.role.in_([UserRole.ADMIN, UserRole.HEAD_OFFICE_MANAGER]),
                            User.id == transfer.requested_by_id,
                        ),
                    )
                )
                recipients_result = await db.execute(recipients_query)
                recipients = list(recipients_result.scalars().unique().all())

                if not recipients:
                    continue

                transfer_number = transfer.transfer_number or transfer.id
                return_date_str = return_date.strftime("%d-%b-%Y")

                if days_until_return < 0:
                    urgency = "OVERDUE"
                    subject = f"[ScienceTech-IMS] OVERDUE: Equipment return overdue - {transfer_number}"
                    body_text = (
                        f"Equipment transfer {transfer_number} return date was {return_date_str} "
                        f"({abs(days_until_return)} day(s) overdue).\n"
                        f"Please arrange immediate return of the equipment."
                    )
                elif days_until_return == 0:
                    urgency = "TODAY"
                    subject = f"[ScienceTech-IMS] Equipment return due TODAY - {transfer_number}"
                    body_text = (
                        f"Equipment transfer {transfer_number} is due for return TODAY ({return_date_str}).\n"
                        f"Please ensure the equipment is returned on time."
                    )
                else:
                    urgency = "UPCOMING"
                    subject = f"[ScienceTech-IMS] Equipment return in {days_until_return} day(s) - {transfer_number}"
                    body_text = (
                        f"Equipment transfer {transfer_number} is due for return on {return_date_str} "
                        f"({days_until_return} day(s) remaining).\n"
                        f"Please plan for timely return of the equipment."
                    )

                body_html = f"""
                <div style="font-family: Arial, sans-serif; max-width: 600px;">
                    <h2 style="color: {'#dc2626' if urgency == 'OVERDUE' else '#f59e0b' if urgency == 'TODAY' else '#2563eb'};">
                        Equipment Return {'Overdue' if urgency == 'OVERDUE' else 'Due Today' if urgency == 'TODAY' else 'Reminder'}
                    </h2>
                    <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                        <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Transfer #</td>
                            <td style="padding: 8px; border: 1px solid #e2e8f0;">{transfer_number}</td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Return Date</td>
                            <td style="padding: 8px; border: 1px solid #e2e8f0;">{return_date_str}</td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Status</td>
                            <td style="padding: 8px; border: 1px solid #e2e8f0; color: {'#dc2626' if urgency == 'OVERDUE' else '#f59e0b' if urgency == 'TODAY' else '#2563eb'}; font-weight: bold;">
                                {'OVERDUE by ' + str(abs(days_until_return)) + ' day(s)' if urgency == 'OVERDUE' else 'Due TODAY' if urgency == 'TODAY' else str(days_until_return) + ' day(s) remaining'}
                            </td></tr>
                        <tr><td style="padding: 8px; border: 1px solid #e2e8f0; font-weight: bold;">Reminder Setting</td>
                            <td style="padding: 8px; border: 1px solid #e2e8f0;">{reminder_days} day(s) before return</td></tr>
                    </table>
                    <p style="color: #64748b; font-size: 12px;">This is an automated reminder from ScienceTech-IMS.</p>
                </div>
                """

                payload = {
                    "transfer_id": transfer.id,
                    "transfer_number": transfer_number,
                    "return_date": return_date_str,
                    "days_until_return": days_until_return,
                    "urgency": urgency,
                    "reminder_days": reminder_days,
                }

                to_emails: List[str] = []
                for user in recipients:
                    if user.email:
                        to_emails.append(user.email)

                    db.add(
                        Notification(
                            id=str(uuid4()),
                            notification_type=NotificationType.RETURN_DATE_DUE,
                            channel=NotificationChannel.IN_APP,
                            recipient_id=user.id,
                            recipient_email=user.email,
                            subject=subject,
                            body=body_text,
                            payload=json.dumps(payload),
                            status=NotificationStatus.SENT,
                            sent_at=now,
                            reference_type="transfer",
                            reference_id=transfer.id,
                        )
                    )

                unique_emails = sorted(set(to_emails))
                if unique_emails:
                    sent = email_service.send_email(
                        to_emails=unique_emails,
                        subject=subject,
                        body_html=body_html,
                        body_text=body_text,
                    )
                    db.add(
                        Notification(
                            id=str(uuid4()),
                            notification_type=NotificationType.RETURN_DATE_DUE,
                            channel=NotificationChannel.EMAIL,
                            recipient_id=None,
                            recipient_email=", ".join(unique_emails),
                            subject=subject,
                            body=body_text,
                            payload=json.dumps(payload),
                            status=NotificationStatus.SENT if sent else NotificationStatus.FAILED,
                            sent_at=now if sent else None,
                            error_message=None if sent else "Failed to send return date reminder email",
                            reference_type="transfer",
                            reference_id=transfer.id,
                        )
                    )

                await self._log_system_audit(
                    db=db,
                    action="return_date_reminder_sent",
                    resource_type="transfer",
                    resource_id=transfer.id,
                    payload={
                        "transfer_number": transfer_number,
                        "return_date": return_date_str,
                        "days_until_return": days_until_return,
                        "urgency": urgency,
                        "recipients": len(recipients),
                    },
                )

                reminder_count += 1

            await db.commit()
            if reminder_count:
                logger.info(f"Return date reminders sent: {reminder_count}")

    # ------------------------------------------------------------------
    # Quarterly archive tasks
    # ------------------------------------------------------------------

    def _check_archive_warning(self) -> None:
        """Check whether the quarterly archive is due in ARCHIVE_WARNING_DAYS days and send a warning email."""
        try:
            self._run_async(self._async_check_archive_warning())
        except Exception as e:
            logger.exception(f"Error in archive warning check: {e}")

    async def _async_check_archive_warning(self) -> None:
        from app.services.archive_service import get_archive_recipients
        from app.services.email_service import get_email_service

        today = datetime.utcnow().date()
        retention_months = settings.ARCHIVE_RETENTION_MONTHS
        warning_days = settings.ARCHIVE_WARNING_DAYS

        # Archive fires on the 1st of each quarter (based on retention months)
        # Quarters: Jan, Apr, Jul, Oct for 3-month retention
        quarter_starts = [1, 1 + retention_months, 1 + retention_months * 2, 1 + retention_months * 3]
        quarter_months = sorted(set((m - 1) % 12 + 1 for m in quarter_starts))

        # Find the next archive date
        next_archive = None
        for month in quarter_months:
            candidate_year = today.year if month >= today.month else today.year + 1
            candidate = date(candidate_year, month, 1)
            if candidate > today:
                next_archive = candidate
                break
        if next_archive is None:
            # wrap around to next year
            next_archive = date(today.year + 1, quarter_months[0], 1)

        days_until = (next_archive - today).days
        if days_until != warning_days:
            return  # Not today

        # Build period: the past 3 months up to yesterday
        period_end = datetime.combine(next_archive - timedelta(days=1), datetime.max.time())
        period_start = datetime(
            period_end.year - (1 if period_end.month - retention_months < 1 else 0),
            (period_end.month - retention_months - 1) % 12 + 1,
            1,
        )

        recipients = await get_archive_recipients(self._session_factory)
        if not recipients:
            logger.warning("Archive warning: no recipients found, skipping.")
            return

        email_service = get_email_service()
        sent = email_service.send_archive_warning(
            to_emails=recipients,
            archive_date=datetime.combine(next_archive, datetime.min.time()),
            period_start=period_start,
            period_end=period_end,
            warning_days=warning_days,
        )
        if sent:
            logger.info(f"Archive warning email sent to {recipients} (archive on {next_archive})")
        else:
            logger.error("Failed to send archive warning email")

    def _run_quarterly_archive(self) -> None:
        """Run the quarterly archive: export, email, purge."""
        try:
            self._run_async(self._async_run_quarterly_archive())
        except Exception as e:
            logger.exception(f"Error running quarterly archive: {e}")

    async def _async_run_quarterly_archive(self) -> None:
        from app.services.archive_service import build_archive, get_archive_recipients, verify_archive
        from app.services.email_service import get_email_service
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email.mime.text import MIMEText
        from email import encoders

        today = datetime.utcnow()
        retention_months = settings.ARCHIVE_RETENTION_MONTHS

        # Today must be the 1st of a quarter month
        quarter_months = sorted(set((m - 1) % 12 + 1 for m in [1, 1 + retention_months, 1 + retention_months * 2]))
        if today.day != 1 or today.month not in quarter_months:
            logger.debug("Quarterly archive: not a quarter boundary day, skipping.")
            return

        # Period: 3 months ending yesterday
        period_end = datetime(today.year, today.month, 1) - timedelta(seconds=1)
        start_month = (today.month - retention_months - 1) % 12 + 1
        start_year = today.year if today.month > retention_months else today.year - 1
        period_start = datetime(start_year, start_month, 1)

        logger.info(f"Running quarterly archive: {period_start.date()} to {period_end.date()}")

        try:
            zip_bytes = await build_archive(
                period_start,
                period_end,
                include_attachments=True,
                session_factory=self._session_factory,
            )
            verify_archive(zip_bytes)
        except Exception as exc:
            logger.exception(f"Archive build failed: {exc}")
            return

        recipients = await get_archive_recipients(self._session_factory)
        if not recipients:
            logger.error("Quarterly archive: no recipients found, archive not sent.")
            return

        # Count records for the delivery email
        period_label = f"{period_start.strftime('%Y%m%d')}-{period_end.strftime('%Y%m%d')}"
        filename = f"sciencetech_ims_archive_{period_label}.zip"

        email_service = get_email_service()

        # Send delivery notification (text/summary first)
        record_counts = {
            "Transactions": 0, "Audit Logs": 0, "Transfers": 0,
            "Purchase Indents": 0, "Calibration Records": 0,
            "Maintenance Records": 0, "Jobs": 0, "Notification Log": 0,
        }
        email_service.send_archive_delivery(
            to_emails=recipients,
            period_start=period_start,
            period_end=period_end,
            record_counts=record_counts,
            purged=True,
        )

        # Send the actual ZIP as attachment via SMTP directly
        if (
            settings.ARCHIVE_EMAIL_ATTACHMENTS_ENABLED
            and email_service.enabled
            and email_service.backend == "smtp"
        ):
            try:
                msg = MIMEMultipart()
                msg["Subject"] = f"[ScienceTech-IMS] Archive Bundle — {period_label}"
                msg["From"] = f"{email_service.from_name} <{email_service.from_email}>"
                msg["To"] = ", ".join(recipients)
                msg.attach(MIMEText("Please find the quarterly archive bundle attached.", "plain"))

                part = MIMEBase("application", "zip")
                part.set_payload(zip_bytes)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                msg.attach(part)

                if email_service.smtp_port == 465:
                    with smtplib.SMTP_SSL(email_service.smtp_host, email_service.smtp_port) as s:
                        if email_service.smtp_user:
                            s.login(email_service.smtp_user, email_service.smtp_password)
                        s.sendmail(email_service.from_email, recipients, msg.as_string())
                else:
                    with smtplib.SMTP(email_service.smtp_host, email_service.smtp_port) as s:
                        s.starttls()
                        if email_service.smtp_user:
                            s.login(email_service.smtp_user, email_service.smtp_password)
                        s.sendmail(email_service.from_email, recipients, msg.as_string())

                logger.info(f"Archive ZIP sent to {recipients}")
            except Exception as exc:
                logger.exception(f"Failed to send archive ZIP email: {exc}")
        else:
            # Console backend — save to disk so it's not lost
            archive_out_dir = os.path.join(settings.STORAGE_LOCAL_PATH, "archives")
            os.makedirs(archive_out_dir, exist_ok=True)
            out_path = os.path.join(archive_out_dir, filename)
            with open(out_path, "wb") as fh:
                fh.write(zip_bytes)
            logger.info(f"[CONSOLE] Archive saved to {out_path} (email disabled)")

        # This artifact is an audit export, not a relational database backup. Never
        # purge operational records based on it; a tested database backup/restore
        # process must be configured before retention deletion can be enabled.
        logger.info("Quarterly archive verified; operational record purge remains disabled")


# Global scheduler instance
scheduler_service = SchedulerService()
