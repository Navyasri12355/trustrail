"""
DB init script — run once to create all tables.
Usage: python -m backend.db.init
"""

from backend.db.database import engine
from backend.db import models  # noqa: F401 — imports needed for Base.metadata


def init_db():
    print("Creating TrustRail database tables...")
    models.Base.metadata.create_all(bind=engine)
    print("✓ Tables created: mandates, audit_log")


if __name__ == "__main__":
    init_db()
