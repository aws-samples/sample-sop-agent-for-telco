# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Detect and reject prompt-injection attempts."""

import re

INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous|above|prior) instructions",
    r"disregard (your |the )?(system )?prompt",
    r"you are (now|actually) ",
    r"new instructions:",
    r"forget (everything|what i said)",
    r"act as (?!an? (network|telco|5g|core|ran|telecom|operator|engineer|sre)\b)",
]


def is_injection_attempt(text: str) -> tuple[bool, str]:
    """Return (is_attempt, matched_pattern_or_empty)."""
    text_lower = text.lower()
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text_lower):
            return True, pattern
    return False, ""


def sanitize_or_reject(text: str) -> tuple[str, dict]:
    """Either return sanitized text, or a rejection notice."""
    is_attempt, pattern = is_injection_attempt(text)
    if is_attempt:
        return "", {
            "rejected": True,
            "reason": "prompt_injection_detected",
            "matched_pattern": pattern,
        }
    return text, {"rejected": False}
