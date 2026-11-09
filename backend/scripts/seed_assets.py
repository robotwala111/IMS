"""
Seed dummy data: reclassify items as instrument/consumable/accessory
and add serialized assets + stock entries.
Run from backend dir: python scripts/seed_assets.py
"""
import sqlite3, uuid

DB = "./data/app.db"
conn = sqlite3.connect(DB)
cur = conn.cursor()

# ── Item IDs to reclassify ──────────────────────────────────────────────────
INSTRUMENTS = [
    "62b711a3-2fe0-442b-878c-7b4600057aea",  # UT Straight Beam Probe 5MHz
    "7d520f82-ba60-4ed2-a1f0-797b2ab4edbe",  # UT Angle Beam Probe 70°
    "ee7a47ba-8a29-4c01-b813-517267166a80",  # ET Surface Probe 100kHz
    "dd314840-e435-4b46-b53b-9b2938f1aa0a",  # Gauss Meter Digital
    "649350ef-51d2-4642-8217-25d27a17eff7",  # Radiation Dosimeter Badge
]

CONSUMABLES = [
    "523bf55b-6937-4b41-84ba-95ce989178ce",  # Ultrasonic Couplant Gel 500ml
    "484c27b7-d44d-45c3-872d-5c41ee42b135",  # Industrial X-Ray Film AGFA D7
    "d848032b-54de-423e-b5ff-d3c333d44200",  # Magnetic Particle Powder - Black
    "d47be4b1-0a29-4e4f-b112-5fcdbb00401b",  # Magnetic Particle Ink - Fluorescent
    "8cd0bde4-058e-41a5-8fd2-e4f1e5942435",  # Penetrant Dye - Zyglo ZL-27A
    "b3849240-3f67-46a6-b1b8-23d3d6d43d83",  # Developer - SKD-S2
    "fabb1448-9899-49f1-adea-483ca8def4f7",  # Cleaner/Remover - SKC-S
    "ae672bd5-2516-42f9-abe6-930add370ce2",  # Visible Dye Penetrant Red
    "83c3a94f-f2e6-4a77-96f2-a565e382dbe7",  # Film Developer Solution 5L
    "aacab7f6-8905-42a8-ac21-e5a4a150d42e",  # Film Fixer Solution 5L
    "75712bb2-20bc-4199-b7d9-98b08d78f8f7",  # Cotton Cloth Roll (10m)
    "6258a890-d881-40bd-bf06-d1656ddaa5f4",  # Isopropyl Alcohol 99% (1L)
    "e7b17611-3a57-43db-b9f4-2d5e9ddf4157",  # Acetone Solvent (1L)
]

ACCESSORIES = [
    "976be893-19c6-4ab4-915f-26ea4fb266eb",  # Lead Letter Set A-Z
    "cb60b1a3-2050-43de-9be1-6c3885648e18",  # IQI Wire Type ASME
    "cab287c8-16d5-4c5f-baee-bf64f8e7dfdb",  # Weld Inspection Gauge Set
    "14248f71-02cb-40bf-b850-6b77d359797b",  # Magnifying Glass 10x
    "649c20a1-cb93-43d4-a073-9c6dc8416364",  # Safety Glasses - UV Protection
    "9a4bfa1c-3163-4244-bdd6-910e938dac17",  # Lead Apron - Full Body
    "2d783db3-b44a-4319-b59f-3b97dc7e74c2",  # Nitrile Gloves Box (100 pcs)
    "8535209c-ab41-478d-a9f8-660a26ab3401",  # Marking Pen - White Industrial
    "ac6d43ab-15e4-4175-b374-5d62f32810f9",  # Masking Tape 2 inch (50m)
]

# ── Fetch locations ─────────────────────────────────────────────────────────
cur.execute("SELECT id, name FROM locations")
locations = cur.fetchall()
loc_ids = [r[0] for r in locations]
print(f"Locations: {[r[1] for r in locations]}")

# ── STEP 1: Reclassify items ────────────────────────────────────────────────
print("\n--- Reclassifying items ---")
for iid in INSTRUMENTS:
    cur.execute("UPDATE items SET asset_type='instrument', is_serialized=1 WHERE id=?", (iid,))
for iid in CONSUMABLES:
    cur.execute("UPDATE items SET asset_type='consumable', is_serialized=0 WHERE id=?", (iid,))
for iid in ACCESSORIES:
    cur.execute("UPDATE items SET asset_type='accessory', is_serialized=0 WHERE id=?", (iid,))
conn.commit()
print("Reclassification done.")

# ── STEP 2: Serialized asset records for instruments ───────────────────────
print("\n--- Adding serialized assets for instruments ---")

instrument_data = [
    # (item_id, serial_number, location_idx, status, acquired_date, cost, asset_tag)
    ("62b711a3-2fe0-442b-878c-7b4600057aea", "PRB-UT-S-001", 0, "IN_SERVICE",        "2023-03-15", 18500.00, "AST-INST-001"),
    ("62b711a3-2fe0-442b-878c-7b4600057aea", "PRB-UT-S-002", 1, "IN_SERVICE",        "2023-03-15", 18500.00, "AST-INST-002"),
    ("62b711a3-2fe0-442b-878c-7b4600057aea", "PRB-UT-S-003", 2, "RETIRED",           "2021-06-10", 18500.00, "AST-INST-003"),
    ("7d520f82-ba60-4ed2-a1f0-797b2ab4edbe", "PRB-UT-A-001", 0, "IN_SERVICE",        "2023-04-20", 22000.00, "AST-INST-004"),
    ("7d520f82-ba60-4ed2-a1f0-797b2ab4edbe", "PRB-UT-A-002", 3, "IN_SERVICE",        "2024-01-10", 22000.00, "AST-INST-005"),
    ("ee7a47ba-8a29-4c01-b813-517267166a80", "PRB-ET-001",   0, "IN_SERVICE",        "2022-11-05", 35000.00, "AST-INST-006"),
    ("ee7a47ba-8a29-4c01-b813-517267166a80", "PRB-ET-002",   4, "UNDER_MAINTENANCE", "2022-11-05", 35000.00, "AST-INST-007"),
    ("dd314840-e435-4b46-b53b-9b2938f1aa0a", "GM-DIG-2301",  0, "IN_SERVICE",        "2023-01-18", 42000.00, "AST-INST-008"),
    ("dd314840-e435-4b46-b53b-9b2938f1aa0a", "GM-DIG-2302",  2, "IN_SERVICE",        "2023-01-18", 42000.00, "AST-INST-009"),
    ("649350ef-51d2-4642-8217-25d27a17eff7", "DOSE-2401",    0, "IN_SERVICE",        "2024-06-01",  4800.00, "AST-INST-010"),
    ("649350ef-51d2-4642-8217-25d27a17eff7", "DOSE-2402",    1, "IN_SERVICE",        "2024-06-01",  4800.00, "AST-INST-011"),
    ("649350ef-51d2-4642-8217-25d27a17eff7", "DOSE-2403",    3, "IN_SERVICE",        "2024-06-01",  4800.00, "AST-INST-012"),
    ("649350ef-51d2-4642-8217-25d27a17eff7", "DOSE-2301",    4, "RETIRED",           "2023-01-15",  4800.00, "AST-INST-013"),
]

for item_id, serial, loc_idx, status, acq, cost, tag in instrument_data:
    cur.execute("SELECT id FROM serialized_assets WHERE serial_number=?", (serial,))
    if cur.fetchone():
        print(f"  SKIP (exists): {serial}")
        continue
    asset_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO serialized_assets (id, item_id, serial_number, location_id, status, acquired_at, cost, asset_tag, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))",
        (asset_id, item_id, serial, loc_ids[loc_idx], status, acq, cost, tag)
    )
    print(f"  Added: {serial} [{status}]")

conn.commit()

# ── STEP 3: Stock entries for consumables ──────────────────────────────────
print("\n--- Adding stock for consumables ---")

consumable_stocks = [
    # (item_id, loc_idx, qty, min_level, reorder_point)
    ("523bf55b-6937-4b41-84ba-95ce989178ce", 0, 24,  5,  8),
    ("523bf55b-6937-4b41-84ba-95ce989178ce", 1, 12,  3,  5),
    ("523bf55b-6937-4b41-84ba-95ce989178ce", 2,  8,  3,  5),
    ("484c27b7-d44d-45c3-872d-5c41ee42b135", 0, 200, 50, 80),
    ("484c27b7-d44d-45c3-872d-5c41ee42b135", 1,  80, 20, 40),
    ("d848032b-54de-423e-b5ff-d3c333d44200", 0, 10,  2,  4),
    ("d848032b-54de-423e-b5ff-d3c333d44200", 3,  6,  2,  3),
    ("d47be4b1-0a29-4e4f-b112-5fcdbb00401b", 0, 15,  3,  5),
    ("8cd0bde4-058e-41a5-8fd2-e4f1e5942435", 0, 18,  4,  6),
    ("8cd0bde4-058e-41a5-8fd2-e4f1e5942435", 1,  9,  2,  4),
    ("8cd0bde4-058e-41a5-8fd2-e4f1e5942435", 2,  6,  2,  3),
    ("b3849240-3f67-46a6-b1b8-23d3d6d43d83", 0, 12,  3,  5),
    ("fabb1448-9899-49f1-adea-483ca8def4f7", 0, 20,  5,  8),
    ("fabb1448-9899-49f1-adea-483ca8def4f7", 4,  8,  2,  4),
    ("ae672bd5-2516-42f9-abe6-930add370ce2", 0, 10,  2,  4),
    ("83c3a94f-f2e6-4a77-96f2-a565e382dbe7", 0,  6,  2,  3),
    ("aacab7f6-8905-42a8-ac21-e5a4a150d42e", 0,  6,  2,  3),
    ("75712bb2-20bc-4199-b7d9-98b08d78f8f7", 0, 30,  5, 10),
    ("75712bb2-20bc-4199-b7d9-98b08d78f8f7", 1, 15,  3,  5),
    ("6258a890-d881-40bd-bf06-d1656ddaa5f4", 0, 20,  5,  8),
    ("e7b17611-3a57-43db-b9f4-2d5e9ddf4157", 0, 15,  4,  6),
]

for item_id, loc_idx, qty, min_lvl, reorder in consumable_stocks:
    cur.execute("SELECT id FROM stocks WHERE item_id=? AND location_id=?", (item_id, loc_ids[loc_idx]))
    if cur.fetchone():
        cur.execute("UPDATE stocks SET quantity_on_hand=?, min_level=?, reorder_point=? WHERE item_id=? AND location_id=?",
                    (qty, min_lvl, reorder, item_id, loc_ids[loc_idx]))
        print(f"  UPDATE: {item_id[-8:]} loc[{loc_idx}] qty={qty}")
    else:
        sid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO stocks (id, item_id, location_id, quantity_on_hand, min_level, reorder_point, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (sid, item_id, loc_ids[loc_idx], qty, min_lvl, reorder)
        )
        print(f"  Added: {item_id[-8:]} loc[{loc_idx}] qty={qty}")

conn.commit()

# ── STEP 4: Stock entries for accessories ──────────────────────────────────
print("\n--- Adding stock for accessories ---")

accessory_stocks = [
    ("976be893-19c6-4ab4-915f-26ea4fb266eb", 0,  5, 1, 2),
    ("976be893-19c6-4ab4-915f-26ea4fb266eb", 1,  3, 1, 2),
    ("cb60b1a3-2050-43de-9be1-6c3885648e18", 0,  8, 2, 3),
    ("cb60b1a3-2050-43de-9be1-6c3885648e18", 3,  4, 1, 2),
    ("cab287c8-16d5-4c5f-baee-bf64f8e7dfdb", 0,  6, 1, 2),
    ("cab287c8-16d5-4c5f-baee-bf64f8e7dfdb", 2,  3, 1, 2),
    ("14248f71-02cb-40bf-b850-6b77d359797b", 0, 15, 3, 5),
    ("14248f71-02cb-40bf-b850-6b77d359797b", 4,  6, 2, 3),
    ("649c20a1-cb93-43d4-a073-9c6dc8416364", 0, 25, 5,10),
    ("649c20a1-cb93-43d4-a073-9c6dc8416364", 1, 12, 3, 5),
    ("649c20a1-cb93-43d4-a073-9c6dc8416364", 2,  8, 2, 4),
    ("9a4bfa1c-3163-4244-bdd6-910e938dac17", 0,  4, 1, 2),
    ("9a4bfa1c-3163-4244-bdd6-910e938dac17", 3,  2, 1, 2),
    ("2d783db3-b44a-4319-b59f-3b97dc7e74c2", 0, 10, 2, 4),
    ("2d783db3-b44a-4319-b59f-3b97dc7e74c2", 1,  5, 1, 3),
    ("8535209c-ab41-478d-a9f8-660a26ab3401", 0, 40, 8,15),
    ("8535209c-ab41-478d-a9f8-660a26ab3401", 4, 20, 5, 8),
    ("ac6d43ab-15e4-4175-b374-5d62f32810f9", 0, 30, 5,10),
    ("ac6d43ab-15e4-4175-b374-5d62f32810f9", 2, 15, 3, 5),
]

for item_id, loc_idx, qty, min_lvl, reorder in accessory_stocks:
    cur.execute("SELECT id FROM stocks WHERE item_id=? AND location_id=?", (item_id, loc_ids[loc_idx]))
    if cur.fetchone():
        cur.execute("UPDATE stocks SET quantity_on_hand=?, min_level=?, reorder_point=? WHERE item_id=? AND location_id=?",
                    (qty, min_lvl, reorder, item_id, loc_ids[loc_idx]))
        print(f"  UPDATE: {item_id[-8:]} loc[{loc_idx}] qty={qty}")
    else:
        sid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO stocks (id, item_id, location_id, quantity_on_hand, min_level, reorder_point, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'))",
            (sid, item_id, loc_ids[loc_idx], qty, min_lvl, reorder)
        )
        print(f"  Added: {item_id[-8:]} loc[{loc_idx}] qty={qty}")

conn.commit()

# ── Summary ─────────────────────────────────────────────────────────────────
print("\n=== SUMMARY ===")
cur.execute("SELECT asset_type, COUNT(*) FROM items GROUP BY asset_type")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} items")
cur.execute("SELECT COUNT(*) FROM serialized_assets")
print(f"  Total serialized assets: {cur.fetchone()[0]}")
cur.execute("SELECT COUNT(*) FROM stocks")
print(f"  Total stock entries: {cur.fetchone()[0]}")

conn.close()
print("\nDone!")
