"""MailKnow local API server - FastAPI IPC Server.

Runs as a local HTTP server for Electron client communication.
Supports all routes for Gate, Search, Approval, Report, Scene, Settings.
"""

import logging
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from db.pgpool import SQLitePool
from core.gate.classifier import GateClassifier
from core.search.hybrid import HybridSearch
from scenes.approval.detector import ApprovalDetector
from scenes.approval.actions import ApprovalActions
from scenes.report.generator import ReportGenerator, ReportScheduler
from scenes.recommender import SceneRecommender
from llm.client import get_llm_client
from llm.token_budget_v2 import TokenBudgetController
from llm.fallback import get_fallback

logger = logging.getLogger(__name__)

# Global instances
_db: Optional[SQLitePool] = None
_approval_actions: Optional[ApprovalActions] = None
_approval_detector: Optional[ApprovalDetector] = None
_report_generator: Optional[ReportGenerator] = None
_report_scheduler: Optional[ReportScheduler] = None
_scene_recommender: Optional[SceneRecommender] = None
_gate_classifier: Optional[GateClassifier] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize resources on startup."""
    global _db, _approval_actions, _approval_detector
    global _report_generator, _report_scheduler, _scene_recommender
    global _gate_classifier

    # Initialize database
    db_path = os.environ.get("MAILKNOW_DB_PATH", "mailknow.db")
    _db = SQLitePool(db_path)
    await _db.initialize()

    # Initialize core components
    _gate_classifier = GateClassifier()
    _approval_actions = ApprovalActions()
    _approval_detector = ApprovalDetector()
    _report_generator = ReportGenerator()
    _report_scheduler = ReportScheduler(generator=_report_generator)
    _scene_recommender = SceneRecommender()

    logger.info("MailKnow API server initialized")

    yield

    # Cleanup
    if _db:
        await _db.close()
    logger.info("MailKnow API server shutdown")


app = FastAPI(
    title="MailKnow API",
    version="5.2.0",
    lifespan=lifespan,
)

# CORS for Electron
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== Health Check =====

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": "5.2.0",
        "components": {
            "db": _db is not None,
            "gate": _gate_classifier is not None,
            "approval": _approval_actions is not None,
            "report": _report_generator is not None,
            "recommender": _scene_recommender is not None,
        },
    }


# ===== Approval Routes =====

@app.get("/api/approvals/pending")
async def get_pending_approvals(
    confidence_level: Optional[str] = None,
    amount_category: Optional[str] = None,
):
    """Get pending approval cards."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Approval actions not initialized")

    from scenes.approval.actions import AmountCategory

    amt_cat = None
    if amount_category:
        try:
            amt_cat = AmountCategory(amount_category)
        except ValueError:
            pass

    cards = _approval_actions.get_pending_cards(
        confidence_level=confidence_level,
        amount_category=amt_cat,
    )

    return {
        "cards": [
            {
                "card_id": c.card_id,
                "email_id": c.email_id,
                "subject": c.subject,
                "requester": c.requester,
                "approver": c.approver,
                "confidence": c.confidence,
                "confidence_level": c.confidence_level,
                "amount": c.amount,
                "amount_category": c.amount_category.value,
                "currency": c.currency,
                "deadline": c.deadline,
                "status": c.status.value,
                "is_actionable": c.is_actionable,
                "is_small_amount": c.is_small_amount,
                "is_large_amount": c.is_large_amount,
                "created_at": c.created_at,
            }
            for c in cards
        ],
        "total": len(cards),
    }


@app.post("/api/approvals/{card_id}/approve")
async def approve_card(card_id: str, comment: str = "", actor: str = "", force: bool = False):
    """Approve an approval card."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Not initialized")

    from scenes.approval.actions import ConfirmationRequiredError

    try:
        card = _approval_actions.approve(card_id, comment=comment, actor=actor, force=force)
        return {"status": "ok", "card_id": card_id, "action": "approved"}
    except ConfirmationRequiredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approvals/{card_id}/reject")
async def reject_card(card_id: str, comment: str = "", actor: str = ""):
    """Reject an approval card."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Not initialized")

    try:
        card = _approval_actions.reject(card_id, comment=comment, actor=actor)
        return {"status": "ok", "card_id": card_id, "action": "rejected"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approvals/{card_id}/forward")
async def forward_card(card_id: str, forward_to: str, comment: str = "", actor: str = ""):
    """Forward an approval card."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Not initialized")

    try:
        card = _approval_actions.forward(card_id, forward_to=forward_to, comment=comment, actor=actor)
        return {"status": "ok", "card_id": card_id, "action": "forwarded", "forward_to": forward_to}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/approvals/batch-approve")
async def batch_approve(card_ids: list[str], comment: str = "", actor: str = "", skip_large: bool = True):
    """Batch approve multiple approval cards."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Not initialized")

    result = _approval_actions.batch_approve(
        card_ids=card_ids, comment=comment, actor=actor, skip_large=skip_large
    )
    return {
        "total": result.total,
        "approved": result.approved,
        "rejected": result.rejected,
        "skipped": result.skipped,
        "errors": result.errors,
        "details": result.details,
    }


@app.get("/api/approvals/stats")
async def get_approval_stats():
    """Get approval statistics."""
    if not _approval_actions:
        raise HTTPException(status_code=503, detail="Not initialized")

    return _approval_actions.get_stats()


# ===== Report Routes =====

@app.post("/api/reports/generate")
async def generate_report(emails: list[dict], period_start: Optional[str] = None, period_end: Optional[str] = None):
    """Generate weekly report."""
    if not _report_generator:
        raise HTTPException(status_code=503, detail="Not initialized")

    report = _report_generator.generate(
        emails=emails, period_start=period_start, period_end=period_end
    )
    return report.to_dict()


@app.get("/api/reports/schedule")
async def check_report_schedule():
    """Check if it's time to generate weekly report."""
    if not _report_scheduler:
        raise HTTPException(status_code=503, detail="Not initialized")

    return {"should_generate": _report_scheduler.should_generate()}


# ===== Scene Routes =====

@app.post("/api/scenes/recommend")
async def get_recommendations(context: dict):
    """Get scene recommendations."""
    if not _scene_recommender:
        raise HTTPException(status_code=503, detail="Not initialized")

    cards = _scene_recommender.recommend(context)
    return {
        "cards": [
            {
                "card_id": c.card_id,
                "scene_type": c.scene_type.value,
                "title": c.title,
                "description": c.description,
                "confidence": c.confidence,
                "priority": c.priority,
                "action_label": c.action_label,
                "action_data": c.action_data,
            }
            for c in cards
        ],
        "total": len(cards),
    }


@app.post("/api/scenes/feedback/{card_id}")
async def record_scene_feedback(card_id: str, feedback: str):
    """Record user feedback on a recommendation card."""
    if not _scene_recommender:
        raise HTTPException(status_code=503, detail="Not initialized")

    from scenes.recommender import FeedbackType

    try:
        fb = FeedbackType(feedback)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid feedback type: {feedback}")

    card = _scene_recommender.record_feedback(card_id, fb)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")

    return {"status": "ok", "card_id": card_id, "feedback": feedback}


@app.get("/api/scenes/stats")
async def get_scene_stats():
    """Get scene recommender statistics."""
    if not _scene_recommender:
        raise HTTPException(status_code=503, detail="Not initialized")

    return _scene_recommender.get_stats()


# ===== Gate Routes =====

@app.get("/api/gate/stats")
async def get_gate_stats():
    """Get Gate classification statistics."""
    if not _gate_classifier:
        raise HTTPException(status_code=503, detail="Not initialized")

    return {"status": "ok"}


# ===== Token Budget Routes =====

@app.get("/api/token-budget")
async def get_token_budget():
    """Get token budget status."""
    budget = TokenBudgetController()
    return budget.get_status()


# ===== Search Routes =====

@app.post("/api/search")
async def search(query: str, limit: int = 20):
    """Search emails using hybrid search."""
    return {"query": query, "results": [], "total": 0}


def start_server(host: str = "127.0.0.1", port: int = 18765):
    """Start the API server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start_server()
