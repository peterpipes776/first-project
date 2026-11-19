"""Turn extracted facts into a trust score and a priority score."""

from __future__ import annotations

import math
from datetime import date

from .extract import PageInfo


def legitimacy(info: PageInfo) -> int:
    """0-100. Starts neutral, rewards UK CAP Code basics, punishes scam signs hard."""
    score = 45 + 8 * len(info.good_signs) - 25 * len(info.red_flags)
    if info.paid_entry:
        score -= 10
    return max(0, min(100, score))


def verdict(score: int) -> str:
    if score >= 70:
        return "looks legit"
    if score >= 40:
        return "check the T&Cs"
    return "avoid"


# Rough competition multipliers: fewer people bother with skill or postal entries.
METHOD_FACTOR = {"skill": 3.0, "post": 2.5, "email": 1.5, "form": 1.0, "social": 0.6}


def priority(value_gbp: float | None, winners: int | None, method: str,
             closes_on: date | None, legit: int, today: date | None = None) -> float:
    """Higher is better. A transparent heuristic, not a probability."""
    today = today or date.today()
    value = value_gbp or 0
    score = math.log10(max(value, 1)) * 10
    score *= METHOD_FACTOR.get(method, 1.0)
    score *= 1 + math.log10(max(winners or 1, 1))
    if closes_on:
        days = (closes_on - today).days
        if days <= 7:
            score *= 1.3  # short windows draw fewer entrants
    score *= legit / 100
    return round(score, 1)
