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
cd "D:\Amiro Tech\NDT_IMS_Final\ndt-ims\backend"
.\run.ps1
```

Open the app:

```text
http://localhost:8000
```

API docs:

```text
http://localhost:8000/api/v1/docs
```

If port `8000` is busy:

```powershell
.\run.ps1 --port 8001
```

## Environment

Backend settings are stored in:

```text
backend/.env
```

The current database connection uses Supabase PostgreSQL. For Supabase pooler compatibility, the asyncpg URL should include:

```text
?prepared_statement_cache_size=0
```

## Documentation

The current business user manual is available at:

```text
documents/user-manual.html
```
