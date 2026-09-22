"""Funnel and response-rate analytics.

Endpoints are added in the feature slice for this domain; the router is
registered in ``app.main`` now so URL prefixes and tags are fixed early.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/analytics", tags=["analytics"])
