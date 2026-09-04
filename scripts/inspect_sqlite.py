import sqlite3

con = sqlite3.connect("storage/app.db")
cur = con.cursor()
tables = [
    r[0]
    for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
]
print("Tables found in SQLite:", tables)
for t in tables:
    cnt = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
    print(f"  {t}: {cnt} rows")
con.close()
