import re
from dataclasses import dataclass

STOP = set('the and or for with from that this are you your our will have has into using use a an to of in on is be as at by we it'.split())

@dataclass
class MatchResult:
    score: float
    matched: list[str]
    gaps: list[str]
    rationale: str

def tokens(text: str):
    return {x for x in re.findall(r"[a-zA-Z0-9+#.-]{2,}", text.lower()) if x not in STOP}

def match_job(job_text: str, profile_text: str, preferences: str = "") -> MatchResult:
    jt, pt = tokens(job_text), tokens(profile_text)
    overlap = sorted(jt & pt)
    # Weighted evidence score; transparent and deterministic without an LLM.
    score = min(96.0, 28 + (len(overlap) / max(1, min(len(jt), 40))) * 68)
    exp_terms = {"senior", "lead", "manager", "principal", "director"}
    if jt & exp_terms:
        score -= 25
    gaps = sorted(jt - pt)[:12]
    rationale = f"Matched {len(overlap)} relevant terms. {len(gaps)} notable terms were not found in the supplied profile."
    return MatchResult(round(max(0, score), 1), overlap[:30], gaps, rationale)
