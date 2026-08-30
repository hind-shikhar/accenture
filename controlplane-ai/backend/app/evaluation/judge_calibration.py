"""
Pure metric computation for AIJudge calibration. Kept separate from the
async run loop in scripts/calibrate_judge.py so these functions are
unit-testable against synthetic results without invoking AIJudge, a model,
or the golden dataset.
"""
from typing import Any, Dict, List, Optional

VERDICT_CLASSES = ("SUPPORTED", "UNCERTAIN", "UNSUPPORTED")


def compute_verdict_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """results: [{"expected_verdict": str, "predicted_verdict": str}, ...]
    Returns overall accuracy plus per-class precision/recall/f1."""
    total = len(results)
    correct = sum(1 for r in results if r["expected_verdict"] == r["predicted_verdict"])

    per_class: Dict[str, Dict[str, Any]] = {}
    for cls in VERDICT_CLASSES:
        tp = sum(1 for r in results if r["predicted_verdict"] == cls and r["expected_verdict"] == cls)
        fp = sum(1 for r in results if r["predicted_verdict"] == cls and r["expected_verdict"] != cls)
        fn = sum(1 for r in results if r["predicted_verdict"] != cls and r["expected_verdict"] == cls)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        f1 = (
            round(2 * precision * recall / (precision + recall), 3)
            if precision is not None and recall is not None and (precision + recall) > 0
            else None
        )
        per_class[cls] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 3) if precision is not None else None,
            "recall": round(recall, 3) if recall is not None else None,
            "f1": f1,
        }

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3) if total else None,
        "per_class": per_class,
    }


def compute_bias_flag_metrics(results: List[Dict[str, Any]], threshold: float = 0.55) -> Dict[str, Any]:
    """results: [{"expected_bias_flag": bool, "bias_score": float}, ...]
    Threshold matches the 0.55 confidence cutoff the BART bias classifier
    already uses elsewhere in this pipeline (workflows/graph.py)."""
    total = len(results)
    tp = sum(1 for r in results if r["bias_score"] > threshold and r["expected_bias_flag"])
    fp = sum(1 for r in results if r["bias_score"] > threshold and not r["expected_bias_flag"])
    fn = sum(1 for r in results if r["bias_score"] <= threshold and r["expected_bias_flag"])
    tn = sum(1 for r in results if r["bias_score"] <= threshold and not r["expected_bias_flag"])

    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    accuracy = (tp + tn) / total if total else None

    return {
        "total": total, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3) if recall is not None else None,
        "accuracy": round(accuracy, 3) if accuracy is not None else None,
    }


def compute_confidence_calibration(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """results: [{"expected_verdict": str, "predicted_verdict": str, "judge_confidence": float}, ...]

    A well-calibrated judge should score its correct predictions higher on
    average than its incorrect ones. If it doesn't, judge_confidence isn't
    actually tracking whether the judge is right — and shouldn't be trusted
    to gate REVIEW/BLOCK decisions until it does."""
    correct_conf = [r["judge_confidence"] for r in results if r["expected_verdict"] == r["predicted_verdict"]]
    incorrect_conf = [r["judge_confidence"] for r in results if r["expected_verdict"] != r["predicted_verdict"]]

    mean_correct = round(sum(correct_conf) / len(correct_conf), 3) if correct_conf else None
    mean_incorrect = round(sum(incorrect_conf) / len(incorrect_conf), 3) if incorrect_conf else None

    well_calibrated: Optional[bool] = None
    if correct_conf and incorrect_conf:
        well_calibrated = mean_correct > mean_incorrect

    return {
        "mean_confidence_when_correct": mean_correct,
        "mean_confidence_when_incorrect": mean_incorrect,
        "n_correct": len(correct_conf),
        "n_incorrect": len(incorrect_conf),
        "well_calibrated": well_calibrated,
    }
