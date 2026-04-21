# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Extract sensitive values from skill content."""

from dataclasses import dataclass

from openviking.prompts import render_prompt
from openviking_cli.utils.config import get_openviking_config
from openviking_cli.utils.llm import parse_json_from_response


@dataclass
class SkillPrivacyExtractionResult:
    values: dict[str, str]
    sanitized_content: str


async def extract_skill_privacy_values(
    *,
    skill_name: str,
    skill_description: str,
    content: str,
) -> dict[str, str]:
    prompt = render_prompt(
        "skill.privacy_extraction",
        {
            "skill_name": skill_name,
            "skill_description": skill_description,
            "skill_content": content,
        },
    )
    response = await get_openviking_config().vlm.get_completion_async(prompt)
    data = parse_json_from_response(response) or {}
    if not isinstance(data, dict):
        return {}
    values = data.get("values", {})
    if not isinstance(values, dict):
        return {}
    return {
        str(key): "" if value is None else str(value)
        for key, value in values.items()
        if str(key).strip()
    }
