"""
Multi-tenant merchant management API.
POST   /merchants          - Create a new merchant
GET    /merchants          - List all merchants (admin only)
GET    /merchants/{id}     - Get merchant details
PUT    /merchants/{id}     - Update merchant
DELETE /merchants/{id}     - Deactivate merchant (soft delete)
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Merchant

router = APIRouter(prefix="/merchants", tags=["merchants"])


# ── Request / Response schemas ───────────────────────────────────────────────


class CreateMerchantRequest(BaseModel):
    merchant_name: str = Field(..., examples=["Acme Corp"])
    razorpay_key_id: str = Field(..., examples=["rzp_test_XXXXXXXXXXXXXXXX"])
    razorpay_key_secret: str = Field(..., examples=["XXXXXXXXXXXXXXXXXXXXXXXX"])
    currency: str = Field(default="INR", examples=["INR"])


class UpdateMerchantRequest(BaseModel):
    merchant_name: str = None
    razorpay_key_id: str = None
    razorpay_key_secret: str = None
    currency: str = None
    active: bool = None


class MerchantResponse(BaseModel):
    merchant_id: str
    merchant_name: str
    razorpay_key_id: str
    currency: str
    active: bool
    created_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _merchant_to_response(m: Merchant) -> MerchantResponse:
    return MerchantResponse(
        merchant_id=m.merchant_id,
        merchant_name=m.merchant_name,
        razorpay_key_id=m.razorpay_key_id,
        currency=m.currency,
        active=m.active,
        created_at=m.created_at.isoformat() + "Z",
    )


# ── Routes ────────────────────────────────────────────────────────────────────


@router.post("", status_code=201, response_model=MerchantResponse)
def create_merchant(body: CreateMerchantRequest, db: Session = Depends(get_db)):
    """
    Create a new merchant with their own Razorpay credentials.
    Each merchant operates in isolation - mandates, audit logs, and payments
    are scoped to their merchant_id.
    """
    merchant_id = "mrc_" + str(uuid.uuid4()).replace("-", "")

    # Check if merchant name already exists
    existing = (
        db.query(Merchant).filter(Merchant.merchant_name == body.merchant_name).first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Merchant name already exists")

    merchant = Merchant(
        merchant_id=merchant_id,
        merchant_name=body.merchant_name,
        razorpay_key_id=body.razorpay_key_id,
        razorpay_key_secret=body.razorpay_key_secret,
        currency=body.currency,
        active=True,
        created_at=datetime.now(timezone.utc),
    )

    db.add(merchant)
    db.commit()
    db.refresh(merchant)

    return _merchant_to_response(merchant)


@router.get("", response_model=list[MerchantResponse])
def list_merchants(db: Session = Depends(get_db)):
    """
    List all merchants.
    In production, this should be restricted to admin users only.
    """
    merchants = db.query(Merchant).all()
    return [_merchant_to_response(m) for m in merchants]


@router.get("/{merchant_id}", response_model=MerchantResponse)
def get_merchant(merchant_id: str, db: Session = Depends(get_db)):
    """Get merchant details by ID."""
    merchant = db.query(Merchant).filter(Merchant.merchant_id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    return _merchant_to_response(merchant)


@router.put("/{merchant_id}", response_model=MerchantResponse)
def update_merchant(
    merchant_id: str, body: UpdateMerchantRequest, db: Session = Depends(get_db)
):
    """
    Update merchant details.
    Only provided fields are updated (partial update).
    """
    merchant = db.query(Merchant).filter(Merchant.merchant_id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    if body.merchant_name is not None:
        merchant.merchant_name = body.merchant_name
    if body.razorpay_key_id is not None:
        merchant.razorpay_key_id = body.razorpay_key_id
    if body.razorpay_key_secret is not None:
        merchant.razorpay_key_secret = body.razorpay_key_secret
    if body.currency is not None:
        merchant.currency = body.currency
    if body.active is not None:
        merchant.active = body.active

    db.commit()
    db.refresh(merchant)

    return _merchant_to_response(merchant)


@router.delete("/{merchant_id}", status_code=200)
def deactivate_merchant(merchant_id: str, db: Session = Depends(get_db)):
    """
    Deactivate a merchant (soft delete).
    Sets active=False. All existing mandates remain but new operations
    will be blocked for this merchant.
    """
    merchant = db.query(Merchant).filter(Merchant.merchant_id == merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    merchant.active = False
    db.commit()

    return {
        "merchant_id": merchant_id,
        "active": False,
        "message": "Merchant deactivated successfully",
    }
