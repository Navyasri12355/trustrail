"""
Story-02: UCP-style merchant manifest endpoint
GET /.well-known/ucp — agent-discoverable catalog
"""

from fastapi import APIRouter
import os

router = APIRouter()

MERCHANT_ID   = os.getenv("TRUSTRAIL_MERCHANT_ID",   "mrc_demo_001")
MERCHANT_NAME = os.getenv("TRUSTRAIL_MERCHANT_NAME", "Demo Merchant")


@router.get("/.well-known/ucp")
def ucp_manifest():
    """
    UCP-style manifest. Agents discover this endpoint to learn what the merchant
    sells, which categories are available, and that mandate-scoped payment is required.
    """
    return {
        "schema_version": "ucp-1.0",
        "merchant": {
            "id":       MERCHANT_ID,
            "name":     MERCHANT_NAME,
            "currency": "INR",
        },
        "catalog": {
            "categories": [
                {
                    "id":          "groceries",
                    "label":       "Groceries",
                    "description": "Fresh produce, packaged food, dairy",
                    "max_item_price_inr": 2000,
                },
                {
                    "id":          "household",
                    "label":       "Household",
                    "description": "Cleaning supplies, kitchen essentials",
                    "max_item_price_inr": 5000,
                },
                {
                    "id":          "electronics",
                    "label":       "Electronics",
                    "description": "Gadgets, accessories, cables",
                    "max_item_price_inr": 15000,
                },
            ]
        },
        "capabilities": {
            "mandate_required":    True,
            "supported_protocols": ["ucp-1.0", "ap2-draft", "uap-ready"],
            "guardrail_endpoint":  "/pay",
            "mandate_endpoint":    "/mandates",
            "audit_endpoint":      "/audit-log",
        },
    }
