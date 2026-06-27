import asyncio

from fastapi import APIRouter

from services.llm_client import llm
from services.url_analyzer import analyze_url

router = APIRouter()


@router.post("/analyze-url")
async def analyze_url_endpoint(data: dict):
    url = (data or {}).get("url", "")
    if not url or not isinstance(url, str) or not url.startswith("http"):
        return {"error": "无效的URL"}

    result = analyze_url(url)

    if result.get("status") == "success" and result.get("title"):
        prompt_data = [
            {
                "name": result.get("title", ""),
                "type": result.get("platform", ""),
                "data": {
                    "description": result.get("description", ""),
                    "author": result.get("author", ""),
                    "platform": result.get("platform", ""),
                },
                "source_url": url,
                "source_name": result.get("site_name", result.get("platform", "")),
            }
        ]
        llm_summary = None
        try:
            llm_summary = await llm.analyze_url("分析链接内容", prompt_data)
        except asyncio.TimeoutError:
            llm_summary = None
        except Exception:
            llm_summary = None

        if llm_summary:
            result["llm_analysis"] = llm_summary

    return result
