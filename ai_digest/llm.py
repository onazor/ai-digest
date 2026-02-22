from __future__ import annotations

import json
from typing import Any, Dict

from openai import OpenAI  # type: ignore[import-error]

from .config import get_settings


_settings = get_settings()
_client = OpenAI(api_key=_settings.openai_api_key)


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
) -> str:
    """
    Simple helper for non-JSON chat completions.
    """
    response = _client.chat.completions.create(
        model=_settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    message = response.choices[0].message
    return (message.content or "").strip()


def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    """
    Helper that asks the model to return a JSON object and parses it.
    """
    response = _client.chat.completions.create(
        model=_settings.openai_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    message = response.choices[0].message
    text = (message.content or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # As a fallback, try to repair obvious issues (e.g., trailing text).
        # For an MVP, we simply raise; you can harden this later.
        raise RuntimeError(f"Failed to parse JSON from model response: {text}")

