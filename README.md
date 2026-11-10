# NDT IMS

Inventory management system for NDT operations.

The current workflow is:

- **Products**: serialized Equipment and Instruments.
- **Stock Levels**: quantity-based Consumables and Accessories.
- **Database**: Supabase PostgreSQL.
- **Deployment direction**: Vercel and Supabase.

## Main Modules

| Module | Purpose |
| --- | --- |
| Dashboard | Company/location summaries, alerts, and recent activity. |
| Categories | Category type and stock-handling control. |
| Products | Serialized assets such as Equipment and Instruments. |
| Stock Levels | Consumables and Accessories with receipt, issue, adjustment, and reorder workflows. |
| Transfers | Transfer Request -> PI -> Approval -> DC -> Receive workflow. |
| Compliance | Instrument calibration tracking and alerts. |
| Personnel | Employee method/title certificate tracking and expiry alerts. |
| Users | Admin, General Manager, and Location Manager access. |

## Roles

| Role | Access |
| --- | --- |
| Admin | Complete access. |
| General Manager | Access to all locations. |
| Location Manager | Access to assigned location only. |

## Run Locally

Open PowerShell:

```powershell
cd "d:\LMS Amiro\IMS\backend"
.\run.ps1
```

Open the app:

```text
http://localhost:8000
```

## Demo Booking Calendar

The access request form checks live availability on the Google Calendar configured for `amirotechsolutions.sales@gmail.com`. It offers weekday demo slots from 10:00 AM to 5:00 PM India time, creates a 30-minute event on that calendar, requests a Google Meet link, and emails the calendar invitation to the requester. Amiro sees the booking on the organizer calendar.

To enable bookings, enable the Google Calendar API in the Google Cloud project and authorize the `amirotechsolutions.sales@gmail.com` calendar with `https://www.googleapis.com/auth/calendar.events` and `https://www.googleapis.com/auth/calendar.freebusy` scopes. Add `http://localhost:8765/oauth2callback` as an authorized redirect URI for the OAuth web client. Put the OAuth client ID and secret in `backend/.env`, then run `python scripts/connect_google_calendar.py` from the `backend` directory and approve access while signed into the `amirotechsolutions.sales@gmail.com` account. The script saves the refresh token directly to `backend/.env`. Keep OAuth credentials in deployment secrets in production. Until authorization is complete, the form reports that live calendar scheduling is unavailable and does not accept a booking.

Demo email confirmations are separate from Google Calendar invitations. To send a detailed confirmation to the requester and a full access enquiry to Amiro, enable `DEMO_BOOKING_EMAIL_ENABLED` and configure Gmail SMTP in `backend/.env`. For Gmail, create an App Password with 2-Step Verification enabled; use it as `SMTP_PASSWORD`, with `SMTP_USER` and `SMTP_FROM_EMAIL` set to `amirotechsolutions.sales@gmail.com` and `SMTP_FROM_NAME=Amiro Tech Solutions`. Keep the App Password out of chat and source control. Restart the backend after updating the environment.

API docs:

```text
http://localhost:8000/api/v1/docs
```

If port `8000` is busy:

```powershell
.\run.ps1 --port 8001
```

## Default Credentials

| Role | Email | Password |
| --- | --- | --- |
| Admin (Superadmin) | `mkumar.amiro@gmail.com` | `Password123!.` |
| Default Admin | `admin@ndt.com` | `Admin@123` |

## Environment

Backend settings are stored in:

```text
backend/.env
```

By default for local development, SQLite is configured:
```text
DATABASE_URL=sqlite:///./data/ndt_ims.db
```
For production or Supabase PostgreSQL, set `DATABASE_URL` to your PostgreSQL URL (with `?prepared_statement_cache_size=0` for Supabase pooler compatibility).

## Documentation

The business user manual is available at:

```text
docs/user-manual.html
```
