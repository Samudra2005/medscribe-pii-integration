"""
Prometheus scrape endpoint. Deliberately NOT behind auth -- this is the
standard Prometheus convention (the scraper itself has no session/login
concept), and this endpoint exposes only aggregate counters/histograms,
never patient data or any PII. If this ever needs restricting (e.g. for
a stricter government network policy), that belongs at the network/
reverse-proxy layer (e.g. only allow the Prometheus server's IP), not
application-level auth.
"""
from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)