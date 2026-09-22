"""One-time bootstrap: seed a default admin user, and (idempotently) import
any existing bank_sites.json/tender_tags.json rows into Postgres now that
those are real tables instead of flat files (see crawler/models.py).

Run from the crawler/ directory, after `alembic upgrade head`:

    python db_seed.py [admin-email]

Safe to re-run: the admin user is upserted by email, and each JSON file is
only imported while its matching table is still empty (so re-running after
the tables already have rows - e.g. ones added through the API - is a no-op
for that table, not a duplicate import).
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from crawler.db import SessionLocal
from crawler.models import BankSite, TenderTag, User, UserRole

DEFAULT_ADMIN_EMAIL = "pachauria534@gmail.com"


def _load_json_list(path):
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def run(admin_email):
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(email=admin_email).one_or_none()
        if admin is None:
            admin = User(email=admin_email, role=UserRole.admin, name="Admin")
            db.add(admin)
            db.flush()
            print(f"Created admin user: {admin_email}")
        else:
            print(f"Admin user already exists: {admin_email}")

        if db.query(BankSite).count() == 0:
            rows = _load_json_list(BASE_DIR / "bank_sites.json")
            for row in rows:
                db.add(BankSite(name=row["name"], url=row["url"], created_by_id=admin.id))
            print(f"Imported {len(rows)} bank site(s) from bank_sites.json")
        else:
            print("bank_sites table already has rows - skipping JSON import")

        if db.query(TenderTag).count() == 0:
            rows = _load_json_list(BASE_DIR / "tender_tags.json")
            for row in rows:
                db.add(TenderTag(
                    name=row["name"],
                    description=row.get("description"),
                    enabled=row.get("enabled", True),
                    created_by_id=admin.id,
                ))
            print(f"Imported {len(rows)} tender tag(s) from tender_tags.json")
        else:
            print("tender_tags table already has rows - skipping JSON import")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ADMIN_EMAIL
    run(email)
