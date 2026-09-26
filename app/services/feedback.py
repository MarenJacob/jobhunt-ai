from collections import Counter

def outcome_insight(feedback_rows):
    counts = Counter(x.outcome for x in feedback_rows)
    total = sum(counts.values()) or 1
    return {"counts": dict(counts), "response_rate": round(100*(total-counts.get('rejected',0))/total,1)}
