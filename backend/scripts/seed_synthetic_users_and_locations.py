"""Seed synthetic users for User Management and configure locations (Hyderabad, Pune, Chennai, Bangalore)."""

import os
import sys
import uuid
from datetime import datetime, date, timedelta

# Ensure backend directory is in python path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import sqlite3
from app.core.security import hash_password

DB_PATH = os.path.join(backend_dir, "data", "ndt_ims.db")
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

now = datetime.now().isoformat()
default_pwd_hash = hash_password("Password123!.")

print(f"Connecting to {DB_PATH}...")

# ---------------------------------------------------------------------------
# 1. Locations: Bangalore (BLR), Pune (PUN), Hyderabad (HYD), Chennai (CHN)
# ---------------------------------------------------------------------------
blr_id = "e31b9826-141c-4a2b-803b-6463cd0b5011"
pune_id = "3219c43c-75b3-4fcd-b264-609e5b8c61c5"
hyd_id = "a415a359-490a-4a56-a723-c9dbdec06849"
chn_id = "c7e2b10a-8d4e-4f1b-9a2c-5e6f7a8b9c0d"

# Update Bangalore
cur.execute(
    "UPDATE locations SET name='Bangalore Head Office', code='BLR-001', address='Plot 45, Peenya Industrial Area, Phase 2', city='Bangalore', state='Karnataka', postal_code='560058', is_active=1, updated_at=? WHERE id=?",
    (now, blr_id),
)

# Update Mangalore -> Pune
cur.execute(
    "UPDATE locations SET name='Pune Testing Facility', code='PUN-001', address='Hinjawadi Phase 2, Industrial Tech Zone', city='Pune', state='Maharashtra', postal_code='411057', is_active=1, updated_at=? WHERE id=?",
    (now, pune_id),
)

# Update Hyderabad
cur.execute(
    "UPDATE locations SET name='Hyderabad Regional Hub', code='HYD-001', address='IDA Jeedimetla, Phase III, Sector 5', city='Hyderabad', state='Telangana', postal_code='500055', is_active=1, updated_at=? WHERE id=?",
    (now, hyd_id),
)

# Insert Chennai if not exists
cur.execute("SELECT id FROM locations WHERE id=?", (chn_id,))
if not cur.fetchone():
    cur.execute(
        """INSERT INTO locations (id, name, code, address, city, state, country, postal_code, is_active, created_at, updated_at)
           VALUES (?, 'Chennai Marine Testing Yard', 'CHN-001', 'Ennore Port Expressway, Ambattur Industrial Estate', 'Chennai', 'Tamil Nadu', 'India', '600058', 1, ?, ?)""",
        (chn_id, now, now),
    )
    print("Added Chennai location (CHN-001)")
else:
    cur.execute(
        "UPDATE locations SET name='Chennai Marine Testing Yard', code='CHN-001', address='Ennore Port Expressway, Ambattur Industrial Estate', city='Chennai', state='Tamil Nadu', postal_code='600058', is_active=1, updated_at=? WHERE id=?",
        (now, chn_id),
    )

print("Locations updated:")
cur.execute("SELECT code, name, city, state FROM locations WHERE is_active=1")
for r in cur.fetchall():
    print(f"  [{r[0]}] {r[1]} - {r[2]}, {r[3]}")

# ---------------------------------------------------------------------------
# 2. Update Serialized Assets for Pune and add for Hyderabad & Chennai
# ---------------------------------------------------------------------------
# Update existing assets that were MNG to PUN
cur.execute("UPDATE serialized_assets SET serial_number='UT-EPOCH650-PUN-002', location_id=? WHERE serial_number='UT-EPOCH650-MNG-002'", (pune_id,))
cur.execute("UPDATE serialized_assets SET serial_number='MPT-YOKE-ACDC-PUN-002', location_id=? WHERE serial_number='MPT-YOKE-ACDC-MNG-002'", (pune_id,))
cur.execute("UPDATE serialized_assets SET serial_number='CAL-V1-BLOCK-PUN-002', location_id=? WHERE serial_number='CAL-V1-BLOCK-MNG-002'", (pune_id,))

# Items lookup
cur.execute("SELECT id, sku FROM items WHERE is_serialized=1")
items_by_sku = {r[1]: r[0] for r in cur.fetchall()}
ut_item_id = items_by_sku.get("UT-EPOCH650")
mpt_item_id = items_by_sku.get("MPT-YOKE-ACDC")
cal_item_id = items_by_sku.get("CAL-V1-BLOCK")

# Additional assets to ensure all 4 locations (Bangalore, Hyderabad, Pune, Chennai) have equipment
new_assets = [
    # (serial_number, item_id, location_id, cost, asset_tag)
    ("UT-EPOCH650-HYD-003", ut_item_id, hyd_id, 450000.00, "AST-UT-HYD-03"),
    ("UT-EPOCH650-CHN-004", ut_item_id, chn_id, 450000.00, "AST-UT-CHN-04"),
    ("MPT-YOKE-ACDC-HYD-003", mpt_item_id, hyd_id, 45000.00, "AST-MPT-HYD-03"),
    ("MPT-YOKE-ACDC-CHN-004", mpt_item_id, chn_id, 45000.00, "AST-MPT-CHN-04"),
    ("CAL-V1-BLOCK-HYD-003", cal_item_id, hyd_id, 25000.00, "AST-CAL-HYD-03"),
    ("CAL-V1-BLOCK-CHN-004", cal_item_id, chn_id, 25000.00, "AST-CAL-CHN-04"),
]

for serial, item_id, loc_id, cost, tag in new_assets:
    if not item_id:
        continue
    cur.execute("SELECT id FROM serialized_assets WHERE serial_number=?", (serial,))
    existing = cur.fetchone()
    if existing:
        asset_id = existing[0]
        cur.execute("UPDATE serialized_assets SET location_id=?, status='IN_SERVICE', updated_at=? WHERE id=?", (loc_id, now, asset_id))
    else:
        asset_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO serialized_assets (id, item_id, serial_number, location_id, status, acquired_at, cost, asset_tag, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'IN_SERVICE', '2024-01-15', ?, ?, ?, ?)""",
            (asset_id, item_id, serial, loc_id, cost, tag, now, now),
        )
        print(f"  Added serialized asset: {serial}")

    # Ensure calibration record exists
    cur.execute("SELECT id FROM calibration_records WHERE asset_id=?", (asset_id,))
    if not cur.fetchone():
        cal_id = str(uuid.uuid4())
        cur.execute(
            """INSERT INTO calibration_records (id, asset_id, recorded_by_id, certificate_number, performed_at, due_at, performed_by, calibration_lab, calibration_procedure, result, as_found_condition, as_left_condition, created_at, updated_at)
               VALUES (?, ?, '5041cafe-c5e3-4255-82ef-72638c2a4b22', ?, '2026-08-10', '2027-08-10', 'Quality Lead', 'Amiro Standards Lab', 'ISO-17025 / ASTM E164', 'PASS', 'IN_TOLERANCE', 'IN_TOLERANCE', ?, ?)""",
            (cal_id, asset_id, f"CERT-{serial}", now, now),
        )

# ---------------------------------------------------------------------------
# 3. Synthetic Users for User Management
# ---------------------------------------------------------------------------
synthetic_users = [
    {
        "id": "u-admin-rajesh-001",
        "email": "rajesh.sharma@amirotech.com",
        "name": "Rajesh Sharma",
        "role": "admin",
        "phone": "+91 98450 11201",
        "department": "Operations & Executive",
        "is_active": 1,
        "locations": [blr_id, hyd_id, pune_id, chn_id],
    },
    {
        "id": "u-gm-priya-002",
        "email": "priya.patel@amirotech.com",
        "name": "Priya Patel",
        "role": "head_office_manager",
        "phone": "+91 98450 22302",
        "department": "Quality Assurance",
        "is_active": 1,
        "locations": [blr_id, hyd_id, pune_id, chn_id],
    },
    {
        "id": "u-mgr-karthik-003",
        "email": "karthik.v@amirotech.com",
        "name": "Karthik Venkat",
        "role": "location_manager",
        "phone": "+91 98450 33403",
        "department": "NDT Inspection Services - HYD",
        "is_active": 1,
        "locations": [hyd_id],
    },
    {
        "id": "u-mgr-sneha-004",
        "email": "sneha.deshmukh@amirotech.com",
        "name": "Sneha Deshmukh",
        "role": "location_manager",
        "phone": "+91 98450 44504",
        "department": "Industrial Testing - Pune",
        "is_active": 1,
        "locations": [pune_id],
    },
    {
        "id": "u-mgr-arun-005",
        "email": "arun.m@amirotech.com",
        "name": "Arun Murugan",
        "role": "location_manager",
        "phone": "+91 98450 55605",
        "department": "Marine Inspection - Chennai",
        "is_active": 1,
        "locations": [chn_id],
    },
    {
        "id": "u-mgr-vikram-006",
        "email": "vikram.reddy@amirotech.com",
        "name": "Vikram Reddy",
        "role": "location_manager",
        "phone": "+91 98450 66706",
        "department": "Central Laboratory - BLR",
        "is_active": 1,
        "locations": [blr_id],
    },
    {
        "id": "u-mgr-rohan-007",
        "email": "rohan.joshi@amirotech.com",
        "name": "Rohan Joshi",
        "role": "location_manager",
        "phone": "+91 98450 77807",
        "department": "Ultrasonic & Radiography - Pune",
        "is_active": 1,
        "locations": [pune_id],
    },
    {
        "id": "u-mgr-divya-008",
        "email": "divya.s@amirotech.com",
        "name": "Divya Sundaram",
        "role": "location_manager",
        "phone": "+91 98450 88908",
        "department": "NDT Level II Inspection - Chennai",
        "is_active": 1,
        "locations": [chn_id],
    },
    {
        "id": "u-gm-meera-009",
        "email": "meera.nambiar@amirotech.com",
        "name": "Meera Nambiar",
        "role": "head_office_manager",
        "phone": "+91 98450 99009",
        "department": "Safety & Regulatory Compliance",
        "is_active": 1,
        "locations": [blr_id, hyd_id, pune_id, chn_id],
    },
    {
        "id": "u-mgr-ananya-010",
        "email": "ananya.k@amirotech.com",
        "name": "Ananya Kulkarni",
        "role": "location_manager",
        "phone": "+91 98450 00110",
        "department": "Field Operations - Pune",
        "is_active": 0,  # Inactive user to demonstrate status filtering
        "locations": [pune_id],
    },
]

print("\nSeeding synthetic users...")
for u in synthetic_users:
    cur.execute("SELECT id FROM users WHERE email=?", (u["email"],))
    existing = cur.fetchone()
    if existing:
        user_id = existing[0]
        cur.execute(
            "UPDATE users SET name=?, role=?, phone=?, department=?, is_active=?, updated_at=? WHERE id=?",
            (u["name"], u["role"], u["phone"], u["department"], u["is_active"], now, user_id),
        )
        print(f"  Updated user: {u['name']} ({u['email']}) [{u['role']}]")
    else:
        user_id = u["id"]
        cur.execute(
            """INSERT INTO users (id, email, name, password_hash, role, is_active, phone, department, failed_login_attempts, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (user_id, u["email"], u["name"], default_pwd_hash, u["role"], u["is_active"], u["phone"], u["department"], now, now),
        )
        print(f"  Created user: {u['name']} ({u['email']}) [{u['role']}]")

    # Update user_locations association
    cur.execute("DELETE FROM user_locations WHERE user_id=?", (user_id,))
    for loc_id in u["locations"]:
        cur.execute("INSERT OR IGNORE INTO user_locations (user_id, location_id) VALUES (?, ?)", (user_id, loc_id))

# Also ensure Super Admin and Demo User have appropriate locations
cur.execute("SELECT id FROM users WHERE email='mkumar.amiro@gmail.com'")
sa = cur.fetchone()
if sa:
    for loc_id in [blr_id, hyd_id, pune_id, chn_id]:
        cur.execute("INSERT OR IGNORE INTO user_locations (user_id, location_id) VALUES (?, ?)", (sa[0], loc_id))

conn.commit()
conn.close()
print("\nSynthetic data seeding completed successfully!")
