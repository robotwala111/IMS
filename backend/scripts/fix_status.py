import sqlite3
conn = sqlite3.connect('./data/app.db')
cur = conn.cursor()
cur.execute("UPDATE serialized_assets SET status='IN_SERVICE' WHERE status='in_service'")
cur.execute("UPDATE serialized_assets SET status='UNDER_MAINTENANCE' WHERE status='under_maintenance'")
cur.execute("UPDATE serialized_assets SET status='RETIRED' WHERE status='retired'")
conn.commit()
cur.execute("SELECT serial_number, status FROM serialized_assets")
for r in cur.fetchall():
    print(r)
conn.close()
print("Done")
