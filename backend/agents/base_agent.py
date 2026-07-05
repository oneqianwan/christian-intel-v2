import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from services.llm_client import call_llm

logger = logging.getLogger(__name__)

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


class BaseAgent:
    """Agent基类，封装共享的 LLM 调用和上下文管理。"""

    def __init__(self, name: str, system_prompt: str, max_tokens: int = 1000):
        self.name = name
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.context: List[Dict[str, str]] = []

    def call(self, user_message: str, temperature: float = 0.3) -> str:
        """调用 LLM，并自动维护最近 6 轮上下文。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            *self.context,
            {"role": "user", "content": user_message},
        ]

        try:
            response = call_llm(
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=temperature,
                model=DEEPSEEK_MODEL,
            )
            self.context.append({"role": "user", "content": user_message})
            self.context.append({"role": "assistant", "content": response})
            if len(self.context) > 12:
                self.context = self.context[-12:]
            return response
        except Exception as exc:
            logger.error("[%s] LLM调用失败: %s", self.name, exc)
            return f"ERROR: {exc}"

    def reset_context(self):
        """重置对话上下文。"""
        self.context = []

    def parse_json(self, response: str) -> Optional[Dict[str, Any]]:
        """从 LLM 响应中提取 JSON。"""
        if not response:
            return None

        cleaned = response.strip()
        try:
            return json.loads(cleaned)
        except Exception:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass
        return None
