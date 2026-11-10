"""
Email Service

Handles sending email notifications including low stock alerts.
"""

import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional, Tuple
from datetime import datetime

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """Service for sending email notifications."""
    
    def __init__(self):
        settings = get_settings()
        self.enabled = settings.EMAIL_ENABLED
        self.backend = settings.EMAIL_BACKEND
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL
        self.from_name = settings.SMTP_FROM_NAME
    
    def _create_message(
        self,
        to_emails: List[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None
    ) -> MIMEMultipart:
        """Create an email message."""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{self.from_name} <{self.from_email}>"
        msg['To'] = ', '.join(to_emails)
        
        # Plain text fallback
        if body_text:
            part1 = MIMEText(body_text, 'plain')
            msg.attach(part1)
        
        # HTML body
        part2 = MIMEText(body_html, 'html')
        msg.attach(part2)
        
        return msg
    
    def send_email(
        self,
        to_emails: List[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None
    ) -> bool:
        """
        Send an email.
        
        Args:
            to_emails: List of recipient email addresses
            subject: Email subject
            body_html: HTML body
            body_text: Plain text body (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            logger.info(f"Email disabled. Would send to {to_emails}: {subject}")
            return True
        
        if self.backend == "console":
            logger.info(f"[CONSOLE EMAIL] To: {to_emails}")
            logger.info(f"[CONSOLE EMAIL] Subject: {subject}")
            logger.info(f"[CONSOLE EMAIL] Body: {body_text or body_html[:200]}...")
            return True
        
        try:
            msg = self._create_message(to_emails, subject, body_html, body_text)
            
            if self.smtp_port == 465:
                # SSL connection
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_emails, msg.as_string())
            else:
                # TLS connection
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_emails, msg.as_string())
            
            logger.info(f"Email sent successfully to {to_emails}: {subject}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            return False

    def send_email_with_attachments(
        self,
        to_emails: List[str],
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
        attachments: Optional[List[Tuple[str, bytes, str]]] = None,
    ) -> bool:
        """Send an email with file attachments.

        Attachments are tuples of (filename, content_bytes, content_type).
        """
        attachments = attachments or []
        if not self.enabled:
            logger.info(f"Email disabled. Would send {len(attachments)} attachment(s) to {to_emails}: {subject}")
            return True

        if self.backend == "console":
            logger.info(f"[CONSOLE EMAIL] To: {to_emails}")
            logger.info(f"[CONSOLE EMAIL] Subject: {subject}")
            logger.info(f"[CONSOLE EMAIL] Attachments: {[name for name, _, _ in attachments]}")
            logger.info(f"[CONSOLE EMAIL] Body: {body_text or body_html[:200]}...")
            return True

        try:
            msg = MIMEMultipart()
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = ", ".join(to_emails)

            if body_text:
                msg.attach(MIMEText(body_text, "plain"))
            msg.attach(MIMEText(body_html, "html"))

            for filename, content, content_type in attachments:
                maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
                part = MIMEBase(maintype, subtype)
                part.set_payload(content)
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
                msg.attach(part)

            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_emails, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.from_email, to_emails, msg.as_string())

            logger.info(f"Email with {len(attachments)} attachment(s) sent to {to_emails}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email with attachments: {str(e)}")
            return False
    
    def send_low_stock_alert(
        self,
        to_emails: List[str],
        low_stock_items: List[dict],
        location_name: Optional[str] = None,
    ) -> bool:
        """
        Send low stock alert email.

        Args:
            to_emails: List of recipient email addresses
            low_stock_items: List of stock items that are low
            location_name: If provided, the subject/header targets a specific location
                           (used when emailing a location manager). None = company-wide summary.

        Returns:
            True if successful, False otherwise
        """
        if not low_stock_items:
            return True
        
        # Build email content
        location_label = f" — {location_name}" if location_name else ""
        subject = f"[ScienceTech-IMS Alert] {len(low_stock_items)} Item(s) Low on Stock{location_label}"
        header_text = (
            f"Low Stock Alert — {location_name}"
            if location_name
            else "Low Stock Alert — All Locations"
        )
        
        # Build HTML table rows
        table_rows = ""
        for item in low_stock_items:
            table_rows += f"""
                <tr>
                    <td style="padding: 8px; border: 1px solid #ddd;">{item.get('item_sku', '-')}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{item.get('item_name', 'Unknown')}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{item.get('location_name', 'Unknown')}</td>
                    <td style="padding: 8px; border: 1px solid #ddd; color: #dc3545; font-weight: bold;">{item.get('quantity_on_hand', 0)}</td>
                    <td style="padding: 8px; border: 1px solid #ddd;">{item.get('reorder_point', 0)}</td>
                </tr>
            """
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                th {{ background: #007bff; color: white; padding: 10px; text-align: left; }}
                .footer {{ text-align: center; padding: 15px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>⚠️ Low Stock Alert</h1>
                    <p style="margin:0; font-size:14px;">{header_text}</p>
                </div>
                <div class="content">
                    <p>Dear Team,</p>
                    <p>The following <strong>{len(low_stock_items)} item(s)</strong> are running low on stock and require attention:</p>
                    
                    <table>
                        <thead>
                            <tr>
                                <th>SKU</th>
                                <th>Item Name</th>
                                <th>Location</th>
                                <th>Current Qty</th>
                                <th>Reorder Point</th>
                            </tr>
                        </thead>
                        <tbody>
                            {table_rows}
                        </tbody>
                    </table>
                    
                    <p style="margin-top: 20px;">Please take necessary action to replenish stock.</p>
                    <p>Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ScienceTech-IMS Inventory Management System.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # Plain text version
        body_text = f"""
Low Stock Alert - ScienceTech-IMS

{len(low_stock_items)} item(s) are running low on stock:

"""
        for item in low_stock_items:
            body_text += f"- {item.get('item_sku', '-')}: {item.get('item_name', 'Unknown')} at {item.get('location_name', 'Unknown')} - Current: {item.get('quantity_on_hand', 0)}, Reorder Point: {item.get('reorder_point', 0)}\n"
        
        body_text += f"\nGenerated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        body_text += "\nThis is an automated message from ScienceTech-IMS Inventory Management System."
        
        return self.send_email(to_emails, subject, body_html, body_text)

    def send_instant_low_stock_alert(
        self,
        to_emails: List[str],
        item_sku: str,
        item_name: str,
        location_name: str,
        current_qty: int,
        min_level: int,
        action: str = "issue"
    ) -> bool:
        """
        Send instant low stock alert when stock drops below minimum.
        
        Args:
            to_emails: List of recipient email addresses
            item_sku: Item SKU
            item_name: Item name
            location_name: Location name
            current_qty: Current quantity after operation
            min_level: Minimum stock level
            action: The action that triggered this (issue, adjustment)
            
        Returns:
            True if successful, False otherwise
        """
        subject = f"[ScienceTech-IMS Alert] Stock Low: {item_sku} - {item_name}"
        
        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #dc3545; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .alert-box {{ background: #fff3cd; border: 1px solid #ffc107; padding: 15px; border-radius: 5px; margin: 15px 0; }}
                .footer {{ text-align: center; padding: 15px; color: #666; font-size: 12px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>⚠️ Immediate Stock Alert</h1>
                </div>
                <div class="content">
                    <p>Dear Team,</p>
                    <p>A stock {action} operation has caused the following item to drop <strong>below its minimum level</strong>:</p>
                    
                    <div class="alert-box">
                        <p><strong>Item:</strong> {item_sku} - {item_name}</p>
                        <p><strong>Location:</strong> {location_name}</p>
                        <p><strong>Current Quantity:</strong> <span style="color: #dc3545; font-weight: bold;">{current_qty}</span></p>
                        <p><strong>Minimum Level:</strong> {min_level}</p>
                    </div>
                    
                    <p style="color: #dc3545; font-weight: bold;">⚡ Immediate action required to replenish stock!</p>
                    <p>Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ScienceTech-IMS Inventory Management System.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        body_text = f"""
Immediate Stock Alert - ScienceTech-IMS

A stock {action} operation has caused the following item to drop below its minimum level:

Item: {item_sku} - {item_name}
Location: {location_name}
Current Quantity: {current_qty}
Minimum Level: {min_level}

Immediate action required to replenish stock!

Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

This is an automated message from ScienceTech-IMS Inventory Management System.
"""
        
        return self.send_email(to_emails, subject, body_html, body_text)

    def send_calibration_alert(
        self,
        to_emails: List[str],
        calibration_items: List[dict],
        location_name: Optional[str] = None,
    ) -> bool:
        """
        Send calibration due/expired alert email.

        Args:
            to_emails: List of recipient email addresses
            calibration_items: List of dicts with keys: serial_number, item_name, item_sku,
                               location_name, due_date, days_until_due, status
            location_name: Optional location scope label

        Returns:
            True if successful, False otherwise
        """
        if not calibration_items:
            return True

        expired = [i for i in calibration_items if i.get('days_until_due', 0) < 0]
        due_soon = [i for i in calibration_items if i.get('days_until_due', 0) >= 0]
        location_label = f" — {location_name}" if location_name else ""
        subject = (
            f"[ScienceTech-IMS] Calibration Alert{location_label}: "
            f"{len(expired)} Expired, {len(due_soon)} Due Soon"
        )

        def row_color(item):
            return "#ffeaea" if item.get('days_until_due', 0) < 0 else "#fff8e1"

        def status_badge(item):
            d = item.get('days_until_due', 0)
            if d < 0:
                return f'<span style="color:#dc3545;font-weight:bold;">EXPIRED ({abs(d)}d ago)</span>'
            return f'<span style="color:#f59e0b;font-weight:bold;">Due in {d} day(s)</span>'

        table_rows = "".join(
            f"""<tr style="background:{row_color(item)};">
                <td style="padding:8px;border:1px solid #ddd;">{item.get('serial_number', '-')}</td>
                <td style="padding:8px;border:1px solid #ddd;">{item.get('item_name', 'Unknown')}</td>
                <td style="padding:8px;border:1px solid #ddd;">{item.get('item_sku', '-')}</td>
                <td style="padding:8px;border:1px solid #ddd;">{item.get('location_name', '-')}</td>
                <td style="padding:8px;border:1px solid #ddd;">{item.get('due_date', '-')}</td>
                <td style="padding:8px;border:1px solid #ddd;">{status_badge(item)}</td>
            </tr>"""
            for item in calibration_items
        )

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 700px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #f59e0b; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                th {{ background: #f59e0b; color: white; padding: 10px; text-align: left; }}
                .footer {{ text-align: center; padding: 15px; color: #666; font-size: 12px; }}
                .summary {{ display: flex; gap: 20px; margin-bottom: 16px; }}
                .summary-box {{ padding: 12px 18px; border-radius: 6px; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>&#128203; Calibration Alert</h1>
                    <p style="margin:0;font-size:14px;">{location_label.strip(' — ') or 'All Locations'}</p>
                </div>
                <div class="content">
                    <p>Dear Team,</p>
                    <p>The following asset(s) require calibration attention:</p>
                    <p>
                        <span style="background:#ffeaea;padding:4px 10px;border-radius:4px;color:#dc3545;font-weight:bold;">
                            &#10060; {len(expired)} Expired
                        </span>&nbsp;&nbsp;
                        <span style="background:#fff8e1;padding:4px 10px;border-radius:4px;color:#f59e0b;font-weight:bold;">
                            &#9888; {len(due_soon)} Due Soon
                        </span>
                    </p>
                    <table>
                        <thead>
                            <tr>
                                <th>Serial No.</th>
                                <th>Item</th>
                                <th>SKU</th>
                                <th>Location</th>
                                <th>Due Date</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows}</tbody>
                    </table>
                    <p style="margin-top:20px;">
                        Please schedule calibration for expired instruments immediately. Assets with expired
                        calibration certificates are <strong>blocked from transfer</strong>.
                    </p>
                    <p>Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="footer">
                    <p>This is an automated message from ScienceTech-IMS Inventory Management System.</p>
                </div>
            </div>
        </body>
        </html>
        """

        body_text = (
            f"Calibration Alert — ScienceTech-IMS\n\n"
            f"{len(expired)} expired, {len(due_soon)} due soon.\n\n"
            + "\n".join(
                f"- {i.get('serial_number', '-')} | {i.get('item_name', '?')} | "
                f"{i.get('location_name', '?')} | Due: {i.get('due_date', '?')} | "
                f"{'EXPIRED' if i.get('days_until_due', 0) < 0 else 'Due in ' + str(i.get('days_until_due', 0)) + 'd'}"
                for i in calibration_items
            )
            + f"\n\nGenerated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "This is an automated message from ScienceTech-IMS."
        )

        return self.send_email(to_emails, subject, body_html, body_text)

    # ------------------------------------------------------------------
    # Archive emails
    # ------------------------------------------------------------------

    def send_archive_warning(
        self,
        to_emails: List[str],
        archive_date: datetime,
        period_start: datetime,
        period_end: datetime,
        warning_days: int,
    ) -> bool:
        """
        Send a warning email N days before the automatic archive runs.
        Gives GM/CEO a heads-up to manually export if needed.
        """
        subject = (
            f"[ScienceTech-IMS] Archive Scheduled in {warning_days} Days — "
            f"{period_start.strftime('%b %Y')} to {period_end.strftime('%b %Y')}"
        )

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 620px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #2E75B6; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .info-box {{ background: #fff3cd; border-left: 4px solid #ffc107; padding: 14px 18px; margin: 16px 0; border-radius: 3px; }}
                .footer {{ text-align: center; padding: 14px; color: #666; font-size: 12px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
                td, th {{ padding: 9px 12px; border: 1px solid #ddd; }}
                th {{ background: #2E75B6; color: white; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>&#128196; Quarterly Archive Notice</h2>
                    <p style="margin:0; font-size:14px;">Automatic archive in <strong>{warning_days} days</strong></p>
                </div>
                <div class="content">
                    <p>Dear Manager,</p>
                    <p>This is an automated reminder that the quarterly data archive will run automatically on
                    <strong>{archive_date.strftime('%B %d, %Y')}</strong>.</p>

                    <table>
                        <tr><th>Archive Period</th><td>{period_start.strftime('%d %b %Y')} &rarr; {period_end.strftime('%d %b %Y')}</td></tr>
                        <tr><th>Scheduled Archive Date</th><td>{archive_date.strftime('%d %b %Y')}</td></tr>
                        <tr><th>Data Included</th><td>Transactions, Audit Logs, Transfers, Purchase Indents,
                            Calibration Records, Maintenance Records, Jobs, Notification Log, Attachments/PDFs</td></tr>
                    </table>

                    <div class="info-box">
                        <strong>Action Required (Optional):</strong><br>
                        If you need a custom export before the automatic archive, please log in to the system
                        and use the <em>Manual Export</em> feature to download data for any date range now.
                        After the archive runs, records older than {period_end.strftime('%d %b %Y')} will be
                        removed from the live database — the archive bundle will be sent to your email.
                    </div>

                    <p>No action is required if you are comfortable with the automatic archive process.</p>
                    <p style="color:#666; font-size:12px;">Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                </div>
                <div class="footer">
                    <p>ScienceTech-IMS &mdash; Automated Data Archival System</p>
                </div>
            </div>
        </body>
        </html>
        """

        body_text = (
            f"Quarterly Archive Notice — ScienceTech-IMS\n\n"
            f"The automatic quarterly archive will run on {archive_date.strftime('%Y-%m-%d')}.\n"
            f"Period: {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}\n\n"
            f"If you need a custom export, log in and use the Manual Export feature before {archive_date.strftime('%Y-%m-%d')}.\n\n"
            f"This is an automated message from ScienceTech-IMS."
        )

        return self.send_email(to_emails, subject, body_html, body_text)

    def send_archive_delivery(
        self,
        to_emails: List[str],
        period_start: datetime,
        period_end: datetime,
        record_counts: dict,
        purged: bool = True,
    ) -> bool:
        """
        Send an email notifying GM/CEO that the archive has been generated and attached
        (or is available for download — actual ZIP sent separately via API or stored).
        """
        subject = (
            f"[ScienceTech-IMS] Archive Ready — "
            f"{period_start.strftime('%b %Y')} to {period_end.strftime('%b %Y')}"
        )

        rows_html = "".join(
            f"<tr><td style='padding:8px 12px;border:1px solid #ddd;'>{name}</td>"
            f"<td style='padding:8px 12px;border:1px solid #ddd;text-align:right;'>{count:,}</td></tr>"
            for name, count in record_counts.items()
        )

        purge_note = (
            "<p style='color:#dc3545;'><strong>Note:</strong> Records older than "
            f"{period_end.strftime('%d %b %Y')} have been removed from the live database. "
            "The archive bundle (attached / downloadable via the system) is the permanent record.</p>"
            if purged else
            "<p>Records have <strong>not</strong> been purged from the live database (manual export mode).</p>"
        )

        body_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 620px; margin: 0 auto; padding: 20px; }}
                .header {{ background: #1F4E79; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border: 1px solid #ddd; }}
                .success-box {{ background: #d4edda; border-left: 4px solid #28a745; padding: 14px 18px; margin: 16px 0; border-radius: 3px; }}
                .footer {{ text-align: center; padding: 14px; color: #666; font-size: 12px; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
                td, th {{ padding: 9px 12px; border: 1px solid #ddd; }}
                th {{ background: #1F4E79; color: white; text-align: left; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>&#10003; Quarterly Archive Complete</h2>
                    <p style="margin:0; font-size:14px;">{period_start.strftime('%d %b %Y')} &mdash; {period_end.strftime('%d %b %Y')}</p>
                </div>
                <div class="content">
                    <p>Dear Manager,</p>
                    <div class="success-box">
                        The quarterly archive has been generated successfully. The archive bundle (Excel + attachments)
                        is attached to this email / available for download from the system.
                    </div>

                    <h3 style="color:#1F4E79;">Archive Contents</h3>
                    <table>
                        <thead><tr><th>Data Category</th><th style="text-align:right;">Records</th></tr></thead>
                        <tbody>{rows_html}</tbody>
                    </table>

                    {purge_note}

                    <p style="color:#666; font-size:12px;">Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                </div>
                <div class="footer">
                    <p>ScienceTech-IMS &mdash; Automated Data Archival System</p>
                </div>
            </div>
        </body>
        </html>
        """

        body_text = (
            f"Quarterly Archive Complete — ScienceTech-IMS\n\n"
            f"Period: {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}\n\n"
            "Archive Contents:\n"
            + "\n".join(f"  {k}: {v:,}" for k, v in record_counts.items())
            + f"\n\n{'Records have been purged from the live database.' if purged else 'Records NOT purged (manual export).'}\n\n"
            "This is an automated message from ScienceTech-IMS."
        )

        return self.send_email(to_emails, subject, body_html, body_text)

    # ------------------------------------------------------------------
    # Transfer Request / Delivery Challan emails
    # ------------------------------------------------------------------

    def send_transfer_request_alert(
        self,
        to_emails: List[str],
        transfer_number: str,
        pi_number: str,
        from_location: str,
        to_location: str,
        requester_name: str,
        items: List[dict],
        priority: str = "normal",
        required_by_date: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Email sent to the supplying location's manager when a new transfer
        request (with auto-created PI) is raised.
        """
        subject = f"[ScienceTech-IMS] New Transfer Request {transfer_number} from {to_location}"
        priority_badge = {
            "urgent": ("#dc2626", "URGENT"),
            "high": ("#f59e0b", "HIGH"),
            "normal": ("#3b82f6", "NORMAL"),
            "low": ("#6b7280", "LOW"),
        }.get(priority.lower(), ("#3b82f6", priority.upper()))

        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;'>{item.get('sku', '')} — {item.get('name', '')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;'>{item.get('quantity_requested', item.get('quantity', ''))}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;'>{item.get('notes', '') or ''}</td>"
            f"</tr>"
            for item in items
        )

        required_by_html = (
            f"<p style='margin:4px 0;color:#374151;'><strong>Required By:</strong> {required_by_date}</p>"
            if required_by_date else ""
        )
        notes_html = (
            f"<p style='margin:4px 0;color:#374151;'><strong>Notes:</strong> {notes}</p>"
            if notes else ""
        )

        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Transfer Request</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;margin:0;padding:0;">
  <div style="max-width:600px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#1e3a5f,#2563eb);padding:28px 32px;">
      <img src="cid:logo" alt="ScienceTech" style="height:36px;margin-bottom:12px;display:block;">
      <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">Transfer Request Received</h1>
      <p style="color:#bfdbfe;margin:6px 0 0;font-size:14px;">Purchase Indent: <strong>{pi_number}</strong></p>
    </div>
    <div style="padding:28px 32px;">
      <div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap;">
        <span style="background:{priority_badge[0]};color:#fff;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:700;">{priority_badge[1]}</span>
        <span style="background:#f3f4f6;color:#374151;padding:4px 12px;border-radius:20px;font-size:12px;">Transfer: {transfer_number}</span>
      </div>
      <p style="margin:4px 0;color:#374151;"><strong>Requested by:</strong> {requester_name} ({to_location})</p>
      <p style="margin:4px 0;color:#374151;"><strong>Supplying Location:</strong> {from_location}</p>
      {required_by_html}
      {notes_html}
      <h3 style="font-size:15px;color:#111827;margin:20px 0 10px;">Items Requested</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;">Item</th>
            <th style="padding:8px 12px;text-align:center;color:#6b7280;font-weight:600;">Qty</th>
            <th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;">Notes</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:16px;margin-top:24px;">
        <p style="margin:0;font-size:13px;color:#92400e;">
          <strong>Action Required:</strong> Please log in to the ScienceTech-IMS portal to review
          the transfer request, check item availability, and approve or reject it.
          A Delivery Challan will be auto-generated upon approval.
        </p>
      </div>
    </div>
    <div style="padding:16px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af;text-align:center;">
      ScienceTech Inventory Management System &mdash; Automated Notification
    </div>
  </div>
</body>
</html>"""

        body_text = (
            f"Transfer Request: {transfer_number}\n"
            f"Purchase Indent: {pi_number}\n"
            f"Requested By: {requester_name} ({to_location})\n"
            f"Supplying Location: {from_location}\n"
            f"Priority: {priority}\n\n"
            f"Items:\n" +
            "\n".join(f"  - {i.get('sku','')} {i.get('name','')}: qty {i.get('quantity_requested', i.get('quantity',''))}" for i in items) +
            "\n\nPlease log in to ScienceTech-IMS to approve or reject this request."
        )
        return self.send_email(to_emails, subject, body_html, body_text)

    def send_delivery_challan_email(
        self,
        to_emails: List[str],
        dc_number: str,
        transfer_number: str,
        pi_number: Optional[str],
        from_location: str,
        to_location: str,
        approved_by_name: str,
        items: List[dict],
        shipping_notes: Optional[str] = None,
    ) -> bool:
        """
        Email sent to the requesting location after the transfer is approved —
        contains the Delivery Challan details.
        """
        subject = f"[ScienceTech-IMS] Delivery Challan {dc_number} — Transfer {transfer_number} Approved"

        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;'>{item.get('sku', '')} — {item.get('name', '')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;'>{item.get('quantity_requested', '')}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:center;'>{item.get('quantity_shipped', item.get('quantity_requested', ''))}</td>"
            f"<td style='padding:8px 12px;border-bottom:1px solid #e5e7eb;color:#6b7280;'>{item.get('lot_number', '') or ''}</td>"
            f"</tr>"
            for item in items
        )
        pi_row = f"<p style='margin:4px 0;color:#374151;'><strong>Purchase Indent:</strong> {pi_number}</p>" if pi_number else ""
        notes_html = (
            f"<p style='margin:4px 0;color:#374151;'><strong>Shipping Notes:</strong> {shipping_notes}</p>"
            if shipping_notes else ""
        )

        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Delivery Challan</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;margin:0;padding:0;">
  <div style="max-width:620px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#065f46,#10b981);padding:28px 32px;">
      <img src="cid:logo" alt="ScienceTech" style="height:36px;margin-bottom:12px;display:block;">
      <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">Delivery Challan</h1>
      <p style="color:#a7f3d0;margin:6px 0 0;font-size:15px;font-weight:600;">{dc_number}</p>
    </div>
    <div style="padding:28px 32px;">
      <p style="margin:4px 0;color:#374151;"><strong>Transfer No:</strong> {transfer_number}</p>
      {pi_row}
      <p style="margin:4px 0;color:#374151;"><strong>From:</strong> {from_location}</p>
      <p style="margin:4px 0;color:#374151;"><strong>To:</strong> {to_location}</p>
      <p style="margin:4px 0;color:#374151;"><strong>Approved By:</strong> {approved_by_name}</p>
      {notes_html}
      <h3 style="font-size:15px;color:#111827;margin:20px 0 10px;">Items Dispatched</h3>
      <table style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="background:#ecfdf5;">
            <th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;">Item</th>
            <th style="padding:8px 12px;text-align:center;color:#6b7280;font-weight:600;">Requested</th>
            <th style="padding:8px 12px;text-align:center;color:#6b7280;font-weight:600;">Dispatched</th>
            <th style="padding:8px 12px;text-align:left;color:#6b7280;font-weight:600;">Batch No</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:16px;margin-top:24px;">
        <p style="margin:0;font-size:13px;color:#065f46;">
          <strong>Your transfer request has been approved.</strong> The items listed above
          are being dispatched. Please acknowledge receipt in the ScienceTech-IMS portal
          once you receive the goods.
        </p>
      </div>
    </div>
    <div style="padding:16px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af;text-align:center;">
      ScienceTech Inventory Management System &mdash; Automated Notification
    </div>
  </div>
</body>
</html>"""

        body_text = (
            f"DELIVERY CHALLAN: {dc_number}\n"
            f"Transfer: {transfer_number}\n"
            f"PI: {pi_number or 'N/A'}\n"
            f"From: {from_location}  To: {to_location}\n"
            f"Approved By: {approved_by_name}\n\n"
            f"Items:\n" +
            "\n".join(
                f"  - {i.get('sku','')} {i.get('name','')}: {i.get('quantity_shipped', i.get('quantity_requested',''))} dispatched"
                for i in items
            ) +
            "\n\nPlease log in to ScienceTech-IMS to acknowledge receipt."
        )
        return self.send_email(to_emails, subject, body_html, body_text)
    def send_password_reset_email(
        self,
        to_email: str,
        user_name: str,
        reset_link: Optional[str] = None,
    ) -> bool:
        """
        Send password reset email to user.
        
        Args:
            to_email: Recipient email address
            user_name: User's full name
            reset_link: Password reset link (if available)
            
        Returns:
            True if successful, False otherwise
        """
        subject = "[ScienceTech-IMS] Password Reset Request"
        
        reset_link_html = (
            f'<a href="{reset_link}" style="display:inline-block;background:#2563eb;color:#fff;padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:600;margin:16px 0;">Reset Password</a>'
            if reset_link else
            "<p style='margin:16px 0;color:#dc3545;'><strong>Note:</strong> Contact your administrator to reset your password.</p>"
        )
        
        body_html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Password Reset</title></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f9fafb;margin:0;padding:0;">
  <div style="max-width:580px;margin:32px auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">
    <div style="background:linear-gradient(135deg,#1e40af,#2563eb);padding:28px 32px;">
      <h1 style="color:#fff;margin:0;font-size:22px;font-weight:700;">Password Reset Request</h1>
    </div>
    <div style="padding:28px 32px;">
      <p style="margin:0 0 16px;color:#374151;">Hello {user_name},</p>
      <p style="margin:0 0 16px;color:#374151;">
        We received a request to reset your password for your ScienceTech-IMS account. 
        If you did not make this request, you can ignore this email.
      </p>
      <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:16px;margin:16px 0;">
        <p style="margin:0;color:#1e40af;font-size:14px;">
          <strong>To reset your password, click the button below:</strong>
        </p>
        {reset_link_html}
      </div>
      <div style="background:#f9fafb;border-left:4px solid #9ca3af;border-radius:4px;padding:12px 16px;margin:16px 0;">
        <p style="margin:0;font-size:13px;color:#6b7280;">
          <strong>Security Tip:</strong> Never share this link with anyone. ScienceTech-IMS support 
          will never ask for your password via email.
        </p>
      </div>
      <p style="margin:16px 0 0;color:#6b7280;font-size:13px;">
        If you have trouble resetting your password, please contact your IT administrator.
      </p>
    </div>
    <div style="padding:16px 32px;background:#f9fafb;border-top:1px solid #e5e7eb;font-size:11px;color:#9ca3af;text-align:center;">
      ScienceTech Inventory Management System
    </div>
  </div>
</body>
</html>"""
        
        body_text = f"""
Password Reset Request — ScienceTech-IMS

Hello {user_name},

We received a request to reset your password. If you did not make this request, you can ignore this email.

To reset your password, visit this link (or copy and paste it into your browser):
{reset_link or 'Contact your administrator to reset your password.'}

Security Tip: Never share this link with anyone.

ScienceTech Inventory Management System
"""
        
        return self.send_email([to_email], subject, body_html, body_text)


# Singleton instance
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get the email service singleton."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
