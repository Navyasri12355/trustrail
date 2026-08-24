"""
Story-02: UCP-style merchant manifest endpoint
GET /.well-known/ucp — agent-discoverable catalog
Multi-tenant: requires X-Merchant-ID header to return merchant-specific manifest.
"""

from fastapi import APIRouter, Depends, HTTPException
from backend.dependencies.tenant import get_merchant_from_header

router = APIRouter()


@router.get("/.well-known/ucp")
def ucp_manifest(merchant = Depends(get_merchant_from_header)):
    """
    UCP-style manifest. Agents discover this endpoint to learn what the merchant
    sells, which categories are available, and that mandate-scoped payment is required.
    Multi-tenant: Returns merchant-specific catalog based on X-Merchant-ID header.
    """
    return {
        "schema_version": "ucp-1.0",
        "merchant": {
            "id":       merchant.merchant_id,
            "name":     merchant.merchant_name,
            "currency": merchant.currency,
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
