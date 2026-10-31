"""DeepSeek OpenAI-compatible API 异步获取层。"""

from __future__ import annotations

import httpx

from .config import settings

API_URL = "https://api.deepseek.com/chat/completions"


async def chat(messages: list[dict[str, str]]) -> str:
    """调用 DeepSeek 并将异常转换为用户可读的提示。"""
    if not settings.api_key or settings.api_key.startswith("<"):
        return "DeepSeek API Key 尚未配置，请在 .env 中填写 DEEPSEEK_API_KEY。"

    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            return "DeepSeek 返回了空内容，请稍后重试。"
        return content.strip()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        return f"DeepSeek 请求失败（HTTP {status}），请检查 API Key、模型配置或稍后重试。"
    except (httpx.HTTPError, TimeoutError):
        return "DeepSeek 网络请求失败或超时，请稍后重试。"
    except (KeyError, IndexError, TypeError, ValueError):
        return "DeepSeek 返回格式异常，请稍后重试。"

