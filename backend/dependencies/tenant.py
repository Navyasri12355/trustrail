"""
Multi-tenant dependency helpers for FastAPI routes.
Extracts and validates merchant_id from requests to ensure tenant isolation.
"""

from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional

from backend.db.database import get_db
from backend.db.models import Merchant


def get_merchant_from_header(
    x_merchant_id: Optional[str] = Header(None, alias="X-Merchant-ID"),
    db: Session = Depends(get_db)
) -> Merchant:
    """
    Extract merchant_id from X-Merchant-ID header and validate merchant exists and is active.
    
    Usage:
        @router.post("/mandates")
        def create_mandate(merchant: Merchant = Depends(get_merchant_from_header), ...):
            # merchant.merchant_id, merchant.razorpay_key_id, etc. are available
    """
    if not x_merchant_id:
        raise HTTPException(
            status_code=400,
            detail="X-Merchant-ID header is required for multi-tenant requests"
        )
    
    merchant = db.query(Merchant).filter(
        Merchant.merchant_id == x_merchant_id,
        Merchant.active == True
    ).first()
    
    if not merchant:
        raise HTTPException(
            status_code=404,
            detail=f"Merchant {x_merchant_id} not found or inactive"
        )
    
    return merchant


def get_merchant_from_path(
    merchant_id: str,
    db: Session = Depends(get_db)
) -> Merchant:
    """
    Extract merchant_id from path parameter and validate merchant exists and is active.
    
    Usage:
        @router.get("/merchants/{merchant_id}/mandates")
        def list_mandates(merchant: Merchant = Depends(get_merchant_from_path), ...):
            # merchant.merchant_id, merchant.razorpay_key_id, etc. are available
    """
    merchant = db.query(Merchant).filter(
        Merchant.merchant_id == merchant_id,
        Merchant.active == True
    ).first()
    
    if not merchant:
        raise HTTPException(
            status_code=404,
            detail=f"Merchant {merchant_id} not found or inactive"
        )
    
    return merchant
