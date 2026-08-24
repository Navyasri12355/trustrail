"""
Database migration script: Single-tenant → Multi-tenant

This script migrates existing single-tenant TrustRail installations to the new
multi-tenant architecture by:
1. Creating the new merchants table
2. Creating a default merchant from environment variables
3. Adding merchant_id foreign key to mandates and audit_log tables
4. Updating existing mandates and audit logs with the default merchant_id

Usage:
    python -m scripts.migrate_to_multitenant

BACKUP YOUR DATABASE BEFORE RUNNING THIS SCRIPT!
"""

import os
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import text
from backend.db.database import engine, get_db
from backend.db.models import Base, Merchant


def migrate():
    """Execute the migration from single-tenant to multi-tenant."""
    
    print("=" * 60)
    print("TrustRail Multi-Tenant Migration")
    print("=" * 60)
    print()
    
    # Step 1: Create merchants table
    print("Step 1: Creating merchants table...")
    try:
        with engine.connect() as conn:
            # Check if merchants table already exists
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='merchants'"
            ))
            if result.fetchone():
                print("  ✓ Merchants table already exists, skipping creation")
            else:
                Base.metadata.tables['merchants'].create(bind=engine)
                print("  ✓ Merchants table created")
    except Exception as e:
        print(f"  ✗ Error creating merchants table: {e}")
        return False
    
    # Step 2: Create default merchant from environment variables
    print("\nStep 2: Creating default merchant from environment variables...")
    merchant_id = os.getenv("TRUSTRAIL_MERCHANT_ID", "mrc_demo_001")
    merchant_name = os.getenv("TRUSTRAIL_MERCHANT_NAME", "Demo Merchant")
    razorpay_key_id = os.getenv("RAZORPAY_KEY_ID", "")
    razorpay_key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    
    if not razorpay_key_id or not razorpay_key_secret:
        print("  ⚠ Warning: RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not set")
        print("  ⚠ Default merchant will be created without Razorpay credentials")
    
    try:
        db = next(get_db())
        existing_merchant = db.query(Merchant).filter(
            Merchant.merchant_id == merchant_id
        ).first()
        
        if existing_merchant:
            print(f"  ✓ Merchant {merchant_id} already exists, skipping creation")
        else:
            default_merchant = Merchant(
                merchant_id=merchant_id,
                merchant_name=merchant_name,
                razorpay_key_id=razorpay_key_id,
                razorpay_key_secret=razorpay_key_secret,
                currency="INR",
                active=True,
                created_at=datetime.utcnow()
            )
            db.add(default_merchant)
            db.commit()
            print(f"  ✓ Default merchant '{merchant_name}' (ID: {merchant_id}) created")
    except Exception as e:
        print(f"  ✗ Error creating default merchant: {e}")
        return False
    finally:
        db.close()
    
    # Step 3: Add merchant_id column to mandates table
    print("\nStep 3: Adding merchant_id to mandates table...")
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("PRAGMA table_info(mandates)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'merchant_id' in columns:
                print("  ✓ merchant_id column already exists in mandates")
            else:
                conn.execute(text(
                    "ALTER TABLE mandates ADD COLUMN merchant_id VARCHAR REFERENCES merchants(merchant_id)"
                ))
                conn.commit()
                print("  ✓ merchant_id column added to mandates table")
    except Exception as e:
        print(f"  ✗ Error adding merchant_id to mandates: {e}")
        return False
    
    # Step 4: Add merchant_id column to audit_log table
    print("\nStep 4: Adding merchant_id to audit_log table...")
    try:
        with engine.connect() as conn:
            # Check if column already exists
            result = conn.execute(text("PRAGMA table_info(audit_log)"))
            columns = [row[1] for row in result.fetchall()]
            
            if 'merchant_id' in columns:
                print("  ✓ merchant_id column already exists in audit_log")
            else:
                conn.execute(text(
                    "ALTER TABLE audit_log ADD COLUMN merchant_id VARCHAR REFERENCES merchants(merchant_id)"
                ))
                conn.commit()
                print("  ✓ merchant_id column added to audit_log table")
    except Exception as e:
        print(f"  ✗ Error adding merchant_id to audit_log: {e}")
        return False
    
    # Step 5: Update existing mandates with default merchant_id
    print("\nStep 5: Updating existing mandates with default merchant_id...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM mandates WHERE merchant_id IS NULL"
            ))
            null_count = result.fetchone()[0]
            
            if null_count == 0:
                print("  ✓ All mandates already have merchant_id")
            else:
                conn.execute(text(
                    f"UPDATE mandates SET merchant_id = '{merchant_id}' WHERE merchant_id IS NULL"
                ))
                conn.commit()
                print(f"  ✓ Updated {null_count} mandates with merchant_id: {merchant_id}")
    except Exception as e:
        print(f"  ✗ Error updating mandates: {e}")
        return False
    
    # Step 6: Update existing audit logs with default merchant_id
    print("\nStep 6: Updating existing audit logs with default merchant_id...")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "SELECT COUNT(*) FROM audit_log WHERE merchant_id IS NULL"
            ))
            null_count = result.fetchone()[0]
            
            if null_count == 0:
                print("  ✓ All audit logs already have merchant_id")
            else:
                conn.execute(text(
                    f"UPDATE audit_log SET merchant_id = '{merchant_id}' WHERE merchant_id IS NULL"
                ))
                conn.commit()
                print(f"  ✓ Updated {null_count} audit logs with merchant_id: {merchant_id}")
    except Exception as e:
        print(f"  ✗ Error updating audit logs: {e}")
        return False
    
    # Step 7: Create indexes for performance
    print("\nStep 7: Creating indexes for tenant isolation...")
    try:
        with engine.connect() as conn:
            # Check if indexes already exist
            result = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
            existing_indexes = [row[0] for row in result.fetchall()]
            
            if 'ix_mandates_merchant_id' not in existing_indexes:
                conn.execute(text("CREATE INDEX ix_mandates_merchant_id ON mandates(merchant_id)"))
                conn.commit()
                print("  ✓ Created index on mandates.merchant_id")
            else:
                print("  ✓ Index on mandates.merchant_id already exists")
            
            if 'ix_audit_log_merchant_id' not in existing_indexes:
                conn.execute(text("CREATE INDEX ix_audit_log_merchant_id ON audit_log(merchant_id)"))
                conn.commit()
                print("  ✓ Created index on audit_log.merchant_id")
            else:
                print("  ✓ Index on audit_log.merchant_id already exists")
    except Exception as e:
        print(f"  ✗ Error creating indexes: {e}")
        return False
    
    print()
    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
    print()
    print("Next steps:")
    print("1. Restart your application")
    print("2. All API endpoints now require X-Merchant-ID header")
    print(f"3. Use merchant_id: {merchant_id} for existing mandates")
    print("4. Create new merchants via POST /merchants API")
    print()
    
    return True


if __name__ == "__main__":
    print("WARNING: This script will modify your database schema.")
    print("Please ensure you have a backup before proceeding.")
    print()
    
    response = input("Do you want to proceed? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        success = migrate()
        sys.exit(0 if success else 1)
    else:
        print("Migration cancelled.")
        sys.exit(0)
