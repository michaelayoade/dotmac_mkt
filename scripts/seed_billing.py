"""Seed billing permissions and settings domain."""

from dotenv import load_dotenv

from app.db import SessionLocal
from app.services.settings_seed import seed_billing_settings


def main() -> None:
    load_dotenv()
    db = SessionLocal()
    try:
        seed_billing_settings(db)
        print("Billing settings seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
