import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

_template = None


def load_template() -> str:
    global _template
    if _template is None:
        _template = config.PROMPT_PATH.read_text(encoding="utf-8")
    return _template


def render(job_description: str, detailed_resume_text: str) -> str:
    # .replace(), not .format() -- the prompt's JSON example contains literal
    # { } braces that would break str.format().
    text = load_template()
    text = text.replace("{job_description}", job_description)
    text = text.replace("{detailed_resume_text}", detailed_resume_text)
    return text


def build_messages(job_description: str, detailed_resume_text: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": "You are an expert resume matcher and ATS optimizer. You always respond with strictly valid JSON when asked to.",
        },
        {"role": "user", "content": render(job_description, detailed_resume_text)},
    ]
