"""
Shared prompt-injection / jailbreak pattern set, used by both the input
gate (security/scanner.py) and the output gate (workflows/graph.py's
node_detect_injection_in_response) so a jailbreak attempt is scored the
same way whether it's found in the prompt or in the model's response.

This replaces a flat list of exact-substring keywords with regex
patterns that tolerate filler words and simple rewording (e.g. "please
ignore any of the prior instructions" still matches, where an exact
substring list would not). It is still a heuristic, not a trained
classifier — novel phrasing outside these pattern families, or
obfuscation via character-spacing/homoglyphs, can still slip through.
That residual risk is called out in docs/threat-model.md.
"""
import re
import unicodedata

# (?:\S+\s+){0,3} between an anchor verb and its target tolerates short filler
# ("any of the", "you were given") that a tight adjacency match would miss.
_GAP = r"(?:\S+\s+){0,3}"

INJECTION_PATTERNS = {
    "override_instructions": [
        rf"ignore\s+{_GAP}(previous|prior|above|earlier)\s+{_GAP}(instructions?|rules?|prompts?|guidelines?|directives?)",
        rf"(disregard|forget)\s+{_GAP}(previous|prior|above|earlier|everything)\b",
        r"new\s+instructions?\s*[:\-]",
        r"override\s+(your\s+)?(previous\s+)?(instructions?|programming|rules|settings|configuration)",
    ],
    "persona_hijack": [
        r"you\s+are\s+now\s+\w+",
        r"act\s+as\s+(if\s+you\s+(are|have)|an?)\s+\w+",
        r"pretend\s+(to\s+be|you\s+are)\s+\w+",
        r"roleplay\s+as\s+\w+",
        r"\bdan\b[\s\S]{0,20}(mode|do anything now)",
        r"developer\s+mode",
        r"jailbreak(ed|ing)?",
        r"no\s+(restrictions|rules|filters|limitations)\b",
        r"without\s+(any\s+)?(restrictions|limitations|filters|censorship)",
    ],
    "exfiltrate_system_prompt": [
        rf"(reveal|print|show|output|repeat|leak|tell|give|share)\s+{_GAP}(your|the)\s+(system\s+prompt|initial\s+prompt|instructions|hidden\s+prompt)",
        r"what\s+(is|was|are)\s+your\s+(system\s+prompt|initial\s+instructions?)",
        r"repeat\s+(the\s+)?(words|text|instructions)\s+above",
    ],
    "safety_bypass": [
        r"bypass\s+(your\s+)?(safety|guidelines|restrictions|filters|rules)",
        r"disable\s+(your\s+)?(safety|filters|restrictions|guardrails)",
        r"unlock(ed)?\s+mode",
    ],
}

_COMPILED = {
    category: [re.compile(p, re.IGNORECASE) for p in patterns]
    for category, patterns in INJECTION_PATTERNS.items()
}

# Common leetspeak/homoglyph substitutions used to dodge naive keyword matching.
_LEET_MAP = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_ZERO_WIDTH = re.compile(r"[​‌‍﻿]")


def normalize_for_matching(text: str) -> str:
    """Undo cheap obfuscation (unicode tricks, leetspeak) before pattern matching."""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH.sub("", text)
    return text.lower().translate(_LEET_MAP)


def score_injection(text: str) -> "tuple[float, list[str]]":
    """
    Returns (score 0-1, matched_categories). Scoring counts distinct matched
    PATTERN RULES (not occurrences, and not deduped by category — a message
    that trips two different override-instruction phrasings is just as
    corroborated as one that trips override + persona-hijack): one matched
    rule → 0.4 (flagged, not blocked); two or more → 0.9+ (blocked at the
    >=0.7 policy threshold). This mirrors the original keyword-count
    bucketing so a single incidental phrase doesn't trip a hard block, but
    any corroborated combination does.
    """
    normalized = normalize_for_matching(text)
    matched_categories = set()
    rule_hits = 0
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            if pattern.search(normalized):
                rule_hits += 1
                matched_categories.add(category)

    if rule_hits == 0:
        return 0.0, []
    if rule_hits == 1:
        return 0.4, sorted(matched_categories)
    return min(0.9 + 0.05 * (rule_hits - 2), 1.0), sorted(matched_categories)
