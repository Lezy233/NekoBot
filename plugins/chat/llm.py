"""DeepSeek OpenAI-compatible API 异步获取层。"""

from __future__ import annotations

import httpx

from .config import settings

API_URL = "https://api.deepseek.com/chat/completions"


async def _request(payload: dict, api_key: str) -> str:
    """发起一次 chat completions 请求并返回正文，失败时抛出异常。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty content")
    return content.strip()


async def chat(
    messages: list[dict],
    *,
    api_key: str | None = None,
    model: str | None = None,
) -> str:
    """调用 chatAPI 并将异常转换为用户可读的提示。

    api_key / model 缺省使用聊天配置；传入其他 OpenAI 兼容服务的密钥与模型
    即可复用本函数发起多模态（vision）请求。
    """
    key = api_key if api_key is not None else settings.chat_api
    if not key or key.startswith("<"):
        return "模型 API Key 尚未配置，请在 .env 中填写相应配置。"

    payload = {
        "model": model or settings.chat_model,
        "messages": messages,
        "temperature": settings.temperature,
    }

    try:
        return await _request(payload, key)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        return f"模型请求失败（HTTP {status}），请检查 API Key、模型配置或稍后重试。"
    except (httpx.HTTPError, TimeoutError):
        return "模型网络请求失败或超时，请稍后重试。"
    except (KeyError, IndexError, TypeError, ValueError):
        return "模型返回格式异常，请稍后重试。"


SUMMARY_SYSTEM_PROMPT = (
    "你在为聊天机器人压缩会话历史。把提供的对话压缩为一份简洁的中文摘要，"
    "保留用户明确告知的称呼、偏好、正在处理的事情、重要约定与未完结话题，"
    "以及能体现双方关系的事实；丢弃寒暄、重复与无关细节。"
    "复读、表情包刷屏、无信息量的网络用语等低信息量内容直接忽略，不占用摘要篇幅。"
    "如果提供了已有摘要，将其与新增对话合并更新，不要分节罗列原文。"
    "直接输出摘要正文，不超过300字，不添加标题或说明。"
)


async def summarize(existing_summary: str, history: list[dict]) -> str:
    """把历史消息压缩为摘要，失败时抛出异常由调用方处理。"""
    lines = [f"{'用户' if m['role'] == 'user' else '角色'}：{m['content']}" for m in history]
    content = "\n".join(lines)
    if existing_summary:
        content = f"已有摘要：\n{existing_summary}\n\n新增对话：\n{content}"
    payload = {
        "model": settings.summary_model or settings.chat_model,
        "messages": [
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0.3,
    }
    api_key = settings.summary_api or settings.chat_api
    return await _request(payload, api_key)
