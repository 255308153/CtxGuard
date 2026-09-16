"""LLM-based Session Analyzer for deep causality extraction and rule recommendations.
Inspired by Headroom's LLM session analyzer replacing all static regex patterns.
"""

from dataclasses import dataclass
from typing import List, Optional
import json

@dataclass
class RecommendedRule:
    category: str
    trigger: str
    directive: str
    rationale: str

class LLMSessionAnalyzer:
    """Invokes LLM in standalone batch process to analyze trajectories and extract rules."""

    SYSTEM_PROMPT = (
        "You are an expert software engineering workflow analyzer. "
        "Analyze the provided agent trajectory digest to discover project conventions, "
        "file path corrections, command patterns, large file cautions, and build directives. "
        "Return recommendations strictly in JSON format as a list of objects with fields: "
        "category, trigger, directive, rationale."
    )

    def __init__(self, model: str = "claude-3-5-sonnet", api_key: Optional[str] = None):
        self.model = model
        self.api_key = api_key

    def build_prompt_payload(self, digest_summary: str) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze this conversation digest:\n\n{digest_summary}"}
            ],
            "temperature": 0.1
        }
