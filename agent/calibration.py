"""
agent/calibration.py — probability calibration layer.

n < 50 resolved calls: fixed log-odds extremization (Baron et al. 2014,
Decision Analysis 11(2):133-145). alpha=0.10 is conservative.

n >= 50 resolved calls: Platt scaling (logistic regression of outcome on
logit(raw_probability)). Pure Python, no numpy required.

Both return an integer probability 0–100.
"""
import math
import logging

log = logging.getLogger(__name__)
EXTREMIZATION_ALPHA = 0.10


def extremize(p_pct: int,
              alpha: float = EXTREMIZATION_ALPHA) -> int:
    """Push p slightly toward 0 or 1 in log-odds space."""
    p = max(0.01, min(0.99, p_pct / 100.0))
    logit = math.log(p / (1.0 - p))
    p2 = 1.0 / (1.0 + math.exp(-logit * (1.0 + alpha)))
    return int(round(p2 * 100))


def _fit_platt(resolved: list[dict]) -> tuple[float, float]:
    """Fit logistic regression: outcome ~ A * logit(raw_p) + B.
    resolved = [{arke_pct: int, outcome_yes: bool}]
    Returns (A, B). Uses gradient descent (2000 steps, lr=0.01)."""
    logits = []
    ys     = []
    for r in resolved:
        p = max(0.01, min(0.99, r["arke_pct"] / 100.0))
        logits.append(math.log(p / (1.0 - p)))
        ys.append(1.0 if r["outcome_yes"] else 0.0)
    A, B, lr, n = 1.0, 0.0, 0.01, len(logits)
    for _ in range(2000):
        gA = gB = 0.0
        for x, y in zip(logits, ys):
            p   = 1.0 / (1.0 + math.exp(-(A * x + B)))
            err = p - y
            gA += err * x
            gB += err
        A -= lr * gA / n
        B -= lr * gB / n
    return A, B


def calibrate(p_pct: int,
              resolved_calls: list[dict] | None = None) -> int:
    """
    Apply calibration. With <50 resolved calls uses fixed extremization.
    With >=50 fits Platt scaling on the resolved set.
    resolved_calls: list of {arke_pct: int, outcome_yes: bool}
    """
    if not resolved_calls or len(resolved_calls) < 50:
        return extremize(p_pct)
    try:
        A, B   = _fit_platt(resolved_calls)
        p      = max(0.01, min(0.99, p_pct / 100.0))
        logit  = math.log(p / (1.0 - p))
        cal    = 1.0 / (1.0 + math.exp(-(A * logit + B)))
        result = int(round(cal * 100))
        log.debug(f"[Calibration] Platt: raw={p_pct}% → {result}%")
        return result
    except Exception as e:
        log.debug(f"[Calibration] Platt failed, falling back to extremize: {e}")
        return extremize(p_pct)
