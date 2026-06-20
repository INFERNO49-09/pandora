"""
Contradictions API.
"""
from fastapi import APIRouter, Query, BackgroundTasks
from discovery.contradiction_detector import ContradictionDetector
from loguru import logger

router = APIRouter(prefix="/contradictions", tags=["contradictions"])

_detector = ContradictionDetector()


@router.get("")
async def get_contradictions(
    domain: str | None = Query(None),
    contradiction_type: str | None = Query(None, enum=["quantitative", "qualitative", "methodological"]),
    min_confidence: float = Query(0.70, ge=0.0, le=1.0),
    limit: int = Query(50, ge=1, le=200),
):
    """Get detected contradictions, optionally filtered by domain or type."""
    results = await _detector.get_stored_contradictions(
        domain=domain,
        contradiction_type=contradiction_type,
        min_confidence=min_confidence,
        limit=limit,
    )
    return {"contradictions": results, "total": len(results)}


@router.post("/scan")
async def trigger_scan(
    background_tasks: BackgroundTasks,
    domain: str | None = Query(None),
    min_confidence: float = Query(0.70),
):
    """
    Trigger an async contradiction scan.
    Runs in the background — results stored to DB + Neo4j.
    """
    async def _run_scan():
        try:
            contradictions = await _detector.scan_domain(
                domain=domain,
                min_confidence=min_confidence,
                limit=100,
            )
            logger.info(f"Scan complete: {len(contradictions)} contradictions found")
            # Persist results to PostgreSQL and Neo4j
            await _detector.persist_contradictions(contradictions)
        except Exception as e:
            logger.error(f"Contradiction scan failed: {e}")

    background_tasks.add_task(_run_scan)
    return {"status": "scan_started", "domain": domain}


@router.get("/live")
async def live_scan(
    domain: str = Query(...),
    min_confidence: float = Query(0.70),
    limit: int = Query(20),
):
    """
    Synchronous live scan — runs immediately, returns results.
    Slower than cached results but always fresh.
    Use sparingly; prefer the scheduled nightly scan.
    """
    contradictions = await _detector.scan_domain(
        domain=domain,
        min_confidence=min_confidence,
        limit=limit,
    )
    return {
        "contradictions": [c.__dict__ for c in contradictions],
        "total": len(contradictions),
        "domain": domain,
    }
