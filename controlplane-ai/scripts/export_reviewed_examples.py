"""
Exports REAL human-reviewed AuditLog rows into
backend/app/evaluation/golden_dataset.py's GoldenExample format, so the
AI-Judge calibration set can gradually be replaced/extended with actual
human-labeled examples from your own HITL review history instead of staying
a synthetic starter set forever.

Only exports rows where:
  - a human actually acted on a REVIEW-flagged request
    (human_review_status in ("approve", "reject")), AND
  - both prompt and response_text are present and non-empty.

The second condition is what correctly excludes the synthetic FP-rate seed
rows scripts/seed_demo_data.py inserts directly for Auto-Tuner sample size —
those never carry real prompt/response text, so they can never show up here
by construction.

IMPORTANT — approve/reject -> claim_verdict is an APPROXIMATION, not a
direct translation. A human's approve/reject decision answers "should this
response ship," which is a broader judgment than the AI-Judge's specific
claim_verdict axis (is this claim factually verifiable). This script maps:
    approve -> SUPPORTED    (human found it acceptable to release)
    reject  -> UNSUPPORTED  (human found something wrong with it)
as a reasonable starting proxy — NOT ground truth. Review every example
below before trusting it the way golden_dataset.py's hand-labeled entries
are trusted.

expected_bias_flag is derived from this row's own recorded bias evidence in
composite_risk, thresholded the same way judge_calibration.py already does
(0.55).

This script never writes to golden_dataset.py automatically — it only
prints ready-to-review Python source for you to paste into GOLDEN_DATASET
yourself. A bad export should never be able to silently corrupt the
calibration set.

Usage:
    python scripts/export_reviewed_examples.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.database import DATABASE_URL
from backend.app.db.models import AuditLog

BIAS_THRESHOLD = 0.55


def _bias_score_from_row(row: AuditLog) -> float:
    risk = row.composite_risk or {}
    vectors = risk.get("risk_vectors", {}) if isinstance(risk, dict) else {}
    bias_ev = vectors.get("bias") or {}
    ai_judge_ev = vectors.get("ai_judge") or {}
    return max(
        float(bias_ev.get("bias_score") or 0.0),
        float(ai_judge_ev.get("bias_score") or 0.0),
    )


def fetch_reviewed_rows(database_url: str = DATABASE_URL):
    engine = create_engine(
        database_url, connect_args={"check_same_thread": False} if "sqlite" in database_url else {}
    )
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        return (
            db.query(AuditLog)
            .filter(AuditLog.human_review_status.in_(["approve", "reject"]))
            .filter(AuditLog.prompt.isnot(None), AuditLog.prompt != "")
            .filter(AuditLog.response_text.isnot(None), AuditLog.response_text != "")
            .order_by(AuditLog.timestamp.desc())
            .all()
        )
    finally:
        db.close()


def render_example(row: AuditLog) -> str:
    verdict = "SUPPORTED" if row.human_override_decision == "approve" else "UNSUPPORTED"
    bias_flag = _bias_score_from_row(row) > BIAS_THRESHOLD
    example_id = f"reviewed-{row.id[:8]}"
    return (
        "    {\n"
        f'        "id": "{example_id}",\n'
        f"        \"prompt\": {row.prompt!r},\n"
        f"        \"response\": {row.response_text!r},\n"
        f'        "expected_verdict": "{verdict}",  # derived from human'
        f" {row.human_override_decision!r} decision — VERIFY before trusting\n"
        f'        "expected_bias_flag": {bias_flag},\n'
        f'        "notes": "Real reviewed example — use_case={row.use_case}, trust_score={row.trust_score}",\n'
        "    },"
    )


def export():
    rows = fetch_reviewed_rows()

    if not rows:
        print(
            "No usable reviewed examples found.\n\n"
            "Need real AuditLog rows with human_review_status in ('approve', 'reject') "
            "AND a non-empty prompt AND response_text — i.e. a real request that paused "
            "for human review (via the LangGraph interrupt in node_human_review) and was "
            "then actually resolved through POST /api/v1/review/{log_id}.\n\n"
            "Synthetic FP-rate seed rows (scripts/seed_demo_data.py) are correctly excluded "
            "here since they carry no real prompt/response text — they exist purely for "
            "Auto-Tuner sample size, not for judge calibration."
        )
        return

    print(f"Found {len(rows)} usable reviewed example(s). REVIEW each label before pasting "
          f"into backend/app/evaluation/golden_dataset.py's GOLDEN_DATASET list:\n")
    print("=" * 70)
    for row in rows:
        print(render_example(row))
    print("=" * 70)
    print(f"\n{len(rows)} example(s) printed above — verify labels, then paste the ones "
          f"you trust into GOLDEN_DATASET.")


if __name__ == "__main__":
    export()
