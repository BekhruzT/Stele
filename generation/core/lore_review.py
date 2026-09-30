"""Mechanical observations, not proxies for engagement or automatic prose rewrites."""
import re
from collections import Counter


def diagnostics(text: str) -> dict:
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n+", text) if p.strip()]
    words = text.split()
    normalized = re.findall(r"\b\w+\b", text.lower())
    grams = Counter(tuple(normalized[i:i + 12]) for i in range(max(0, len(normalized) - 11)))
    return {"word_count": len(words), "paragraph_count": len(paragraphs),
            "estimated_minutes_at_120_to_135_wpm": [round(len(words) / 135, 1), round(len(words) / 120, 1)],
            "duplicate_paragraphs": [p for p, n in Counter(paragraphs).items() if n > 1],
            "repeated_12_word_sequences": [{"text": " ".join(g), "count": n}
                                            for g, n in grams.items() if n > 1],
            "interpretation": "Duplication diagnostics require editorial interpretation; no sentence or hook length quota."}
