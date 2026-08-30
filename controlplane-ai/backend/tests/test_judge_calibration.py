"""
Unit coverage for the pure metric functions in
backend/app/evaluation/judge_calibration.py, used by
scripts/calibrate_judge.py. Exercised against synthetic result dicts —
never invokes AIJudge or the golden dataset — so these confirm the scoring
math itself is correct, independent of how good (or bad) the judge
currently is.
"""
from backend.app.evaluation.judge_calibration import (
    compute_verdict_metrics,
    compute_bias_flag_metrics,
    compute_confidence_calibration,
)


def test_verdict_metrics_perfect_predictions():
    results = [
        {"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED"},
        {"expected_verdict": "UNCERTAIN", "predicted_verdict": "UNCERTAIN"},
        {"expected_verdict": "UNSUPPORTED", "predicted_verdict": "UNSUPPORTED"},
    ]
    m = compute_verdict_metrics(results)
    assert m["accuracy"] == 1.0
    assert m["correct"] == 3
    for cls in ("SUPPORTED", "UNCERTAIN", "UNSUPPORTED"):
        assert m["per_class"][cls]["precision"] == 1.0
        assert m["per_class"][cls]["recall"] == 1.0


def test_verdict_metrics_all_predicted_one_class():
    # Judge always says SUPPORTED regardless of the true label — this is
    # exactly the failure mode the harness is meant to catch.
    results = [
        {"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED"},
        {"expected_verdict": "UNCERTAIN", "predicted_verdict": "SUPPORTED"},
        {"expected_verdict": "UNSUPPORTED", "predicted_verdict": "SUPPORTED"},
        {"expected_verdict": "UNSUPPORTED", "predicted_verdict": "SUPPORTED"},
    ]
    m = compute_verdict_metrics(results)
    assert m["accuracy"] == 0.25
    assert m["per_class"]["SUPPORTED"]["precision"] == 0.25  # 1 correct out of 4 predicted SUPPORTED
    assert m["per_class"]["SUPPORTED"]["recall"] == 1.0      # caught the only true SUPPORTED case
    assert m["per_class"]["UNCERTAIN"]["recall"] == 0.0
    assert m["per_class"]["UNCERTAIN"]["precision"] is None  # never predicted -> undefined, not zero
    assert m["per_class"]["UNSUPPORTED"]["recall"] == 0.0


def test_verdict_metrics_empty_results():
    m = compute_verdict_metrics([])
    assert m["accuracy"] is None
    assert m["total"] == 0


def test_bias_flag_metrics_basic():
    results = [
        {"expected_bias_flag": True, "bias_score": 0.8},   # tp
        {"expected_bias_flag": False, "bias_score": 0.9},  # fp
        {"expected_bias_flag": True, "bias_score": 0.2},   # fn
        {"expected_bias_flag": False, "bias_score": 0.1},  # tn
    ]
    m = compute_bias_flag_metrics(results, threshold=0.55)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (1, 1, 1, 1)
    assert m["precision"] == 0.5
    assert m["recall"] == 0.5
    assert m["accuracy"] == 0.5


def test_bias_flag_metrics_threshold_matches_bart_convention():
    # 0.55 is the same cutoff the BART bias classifier uses in workflows/graph.py
    results = [{"expected_bias_flag": True, "bias_score": 0.55}]  # exactly at threshold, not above it
    m = compute_bias_flag_metrics(results, threshold=0.55)
    assert m["tp"] == 0
    assert m["fn"] == 1


def test_confidence_calibration_well_calibrated():
    results = [
        {"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.95},
        {"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.9},
        {"expected_verdict": "UNSUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.4},
    ]
    m = compute_confidence_calibration(results)
    assert m["well_calibrated"] is True
    assert m["mean_confidence_when_correct"] > m["mean_confidence_when_incorrect"]


def test_confidence_calibration_poorly_calibrated():
    # Confidence is HIGHER on the wrong answer — a judge whose confidence
    # can't be trusted, which is exactly what this check exists to catch.
    results = [
        {"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.5},
        {"expected_verdict": "UNSUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.9},
    ]
    m = compute_confidence_calibration(results)
    assert m["well_calibrated"] is False


def test_confidence_calibration_undefined_when_no_errors_or_no_successes():
    all_correct = [{"expected_verdict": "SUPPORTED", "predicted_verdict": "SUPPORTED", "judge_confidence": 0.9}]
    m = compute_confidence_calibration(all_correct)
    assert m["well_calibrated"] is None
