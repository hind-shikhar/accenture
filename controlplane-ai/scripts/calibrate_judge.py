"""
AI-Judge calibration harness.

Runs AIJudge (backend/app/evaluation/ai_judge.py) against the golden
dataset (backend/app/evaluation/golden_dataset.py) and reports verdict
accuracy, per-class precision/recall/f1, bias-flag accuracy, and whether
judge_confidence actually tracks correctness.

IMPORTANT: the golden dataset is a small SYNTHETIC starter set (see its
module docstring) — treat this report as "does the harness work and is the
judge directionally sane," not "the judge is production-validated." Before
trusting judge_confidence to gate real decisions, replace/extend the golden
dataset with real human-reviewed examples.

In DEMO_MODE (the default) or with no live provider key configured, AIJudge
falls back to its heuristic scoring — this still exercises the harness
end-to-end, it just calibrates the heuristic path rather than a live model.

Usage:
    python scripts/calibrate_judge.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # avoid mojibake on Windows' default console codepage
except AttributeError:
    pass

from backend.app.evaluation.ai_judge import AIJudge
from backend.app.evaluation.golden_dataset import get_golden_dataset
from backend.app.evaluation.judge_calibration import (
    compute_verdict_metrics,
    compute_bias_flag_metrics,
    compute_confidence_calibration,
)


async def run() -> None:
    judge = AIJudge()
    dataset = get_golden_dataset()
    results = []

    for example in dataset:
        ev = await judge.evaluate(example["prompt"], example["response"], example.get("history", []))
        results.append({
            "id": example["id"],
            "expected_verdict": example["expected_verdict"],
            "predicted_verdict": ev["claim_verdict"],
            "expected_bias_flag": example["expected_bias_flag"],
            "bias_score": ev["bias_score"],
            "judge_confidence": ev["judge_confidence"],
            "method": ev["method"],
        })

    verdict_metrics = compute_verdict_metrics(results)
    bias_metrics = compute_bias_flag_metrics(results)
    calibration = compute_confidence_calibration(results)

    print(f"\nJudge calibration report — {len(dataset)} examples ({results[0]['method']} method)")
    print("=" * 64)

    print("\nMisclassified examples:")
    misses = [r for r in results if r["expected_verdict"] != r["predicted_verdict"]]
    if not misses:
        print("  (none)")
    for r in misses:
        print(f"  [{r['id']}] expected {r['expected_verdict']}, got {r['predicted_verdict']}"
              f" (confidence={r['judge_confidence']})")

    print(f"\nVerdict accuracy: {verdict_metrics['accuracy']} ({verdict_metrics['correct']}/{verdict_metrics['total']})")
    for cls, m in verdict_metrics["per_class"].items():
        print(f"  {cls:<12} precision={m['precision']}  recall={m['recall']}  f1={m['f1']}"
              f"  (tp={m['tp']} fp={m['fp']} fn={m['fn']})")

    print(f"\nBias-flag accuracy: {bias_metrics['accuracy']}  "
          f"precision={bias_metrics['precision']}  recall={bias_metrics['recall']}"
          f"  (tp={bias_metrics['tp']} fp={bias_metrics['fp']} fn={bias_metrics['fn']} tn={bias_metrics['tn']})")

    print("\nConfidence calibration:")
    print(f"  mean confidence when correct:   {calibration['mean_confidence_when_correct']} (n={calibration['n_correct']})")
    print(f"  mean confidence when incorrect: {calibration['mean_confidence_when_incorrect']} (n={calibration['n_incorrect']})")
    if calibration["well_calibrated"] is False:
        print("  WARNING: confidence does NOT track correctness on this dataset —"
              " do not trust judge_confidence to gate decisions yet.")
    elif calibration["well_calibrated"] is True:
        print("  OK: confidence is higher on average for correct predictions than incorrect ones.")
    print()


if __name__ == "__main__":
    asyncio.run(run())
