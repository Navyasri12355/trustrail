"""
DB init script — run once to create all tables.
Usage: python -m backend.db.init
"""

import os
from datetime import datetime, timezone

from backend.db import models
from backend.db.database import SessionLocal, engine


def init_db():
    print("Creating TrustRail database tables...")
    models.Base.metadata.create_all(bind=engine)
    print("✓ Tables created: mandates, audit_log")


def seed_demo_merchant() -> None:
    """
    Upsert the demo merchant (mrc_demo_001) so the test harness always
    has a valid tenant regardless of whether the DB was wiped.
    Reads Razorpay credentials from the environment (loaded via .env).
    """
    merchant_id = os.getenv("TRUSTRAIL_MERCHANT_ID", "mrc_demo_001")
    merchant_name = os.getenv("TRUSTRAIL_MERCHANT_NAME", "Demo Merchant")
    rzp_key_id = os.getenv("RAZORPAY_KEY_ID", "rzp_test_demo")
    rzp_key_secret = os.getenv("RAZORPAY_KEY_SECRET", "demo_secret")

    db = SessionLocal()
    try:
        existing = (
            db.query(models.Merchant)
            .filter(models.Merchant.merchant_id == merchant_id)
            .first()
        )
        if existing:
            # Ensure it's active and credentials are up-to-date
            existing.active = True
            existing.razorpay_key_id = rzp_key_id
            existing.razorpay_key_secret = rzp_key_secret
            existing.merchant_name = merchant_name
        else:
            db.add(
                models.Merchant(
                    merchant_id=merchant_id,
                    merchant_name=merchant_name,
                    razorpay_key_id=rzp_key_id,
                    razorpay_key_secret=rzp_key_secret,
                    currency="INR",
                    active=True,
                    created_at=datetime.now(tz=timezone.utc),
                )
            )
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
