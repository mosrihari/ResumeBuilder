import json
import re

REQUIRED_KEYS = ("resume_bullets", "cover_letter", "referral_request")

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


class ResponseParseError(Exception):
    pass


def strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text.strip()).strip()


def parse_response(raw_text: str) -> dict:
    cleaned = strip_code_fence(raw_text)

    parsed = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                parsed = None

    if parsed is None:
        raise ResponseParseError(f"Could not parse JSON from Sarvam response: {raw_text[:500]!r}")

    missing = [k for k in REQUIRED_KEYS if k not in parsed]
    if missing:
        raise ResponseParseError(f"Sarvam response JSON missing keys {missing}: {raw_text[:500]!r}")

    return parsed
