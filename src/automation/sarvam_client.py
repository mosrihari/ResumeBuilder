import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

from sarvamai import SarvamAI


class SarvamCallError(Exception):
    pass


def get_client() -> SarvamAI:
    if not config.SARVAM_API_KEY:
        raise ValueError("Missing environment variable: 'SARVAM_API_KEY' not found in .env")
    return SarvamAI(api_subscription_key=config.SARVAM_API_KEY)


def call_sarvam(client: SarvamAI, messages: list[dict]) -> str:
    last_error = None
    for attempt in range(config.SARVAM_MAX_ATTEMPTS):
        try:
            response = client.chat.completions(
                model=config.SARVAM_MODEL,
                messages=messages,
                reasoning_effort=config.SARVAM_REASONING_EFFORT,
                max_tokens=config.SARVAM_MAX_TOKENS,
            )
            content = response.choices[0].message.content
            if content is not None:
                return content
            # sarvam-105b is a reasoning model: even at reasoning_effort="low" it
            # sometimes spends the whole max_tokens budget on chain-of-thought before
            # answering (observed ~1-in-3 calls). This is sampling variance, not a
            # real error or rate limit, so retry immediately with no backoff delay.
            last_error = SarvamCallError(
                f"Sarvam returned empty content (finish_reason={response.choices[0].finish_reason})"
            )
        except Exception as e:
            last_error = e
            if attempt < len(config.SARVAM_BACKOFF_SECONDS):
                time.sleep(config.SARVAM_BACKOFF_SECONDS[attempt])
    raise SarvamCallError(f"Sarvam call failed after {config.SARVAM_MAX_ATTEMPTS} attempts: {last_error}")
