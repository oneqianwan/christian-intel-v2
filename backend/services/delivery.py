import asyncio
from typing import List, Dict, Any

from services.llm_client import llm


def _generate_template_content(query: str, results: List[Dict[str, Any]]) -> str:
    content_lines = [f"## 关于「{query}」的情报简报\n"]
    for i, r in enumerate(results, 1):
        content_lines.append(f"\n### {i}. {r['name']}")
        content_lines.append(f"- 类型：{r['type']} | 国家：{r['country']} | 类别：{r['category']}")
        if r.get('data') and isinstance(r['data'], dict):
            for k, v in r['data'].items():
                content_lines.append(f"- {k}：{v}")
        if r.get('source_url'):
            content_lines.append(f"- 来源：[{r.get('source_name', '链接')}]({r['source_url']})")
    return "\n".join(content_lines)


def compose_delivery(query: str, results: List[Dict[str, Any]], intent: str) -> Dict[str, Any]:
    if not results:
        return {
            "status": "no_data",
            "content": f"关于「{query}」，当前知识库暂未录入相关数据。系统已记录该查询，后续将补充。",
            "sources": [],
            "delivery_type": "intelligence_brief",
            "execution_summary": {"intent": intent, "kb_hits": 0},
            "next_actions": ["触发采集补充数据", "换个关键词试试"]
        }

    content = ""
    llm_source = "llm"

    try:
        llm_content = asyncio.run(llm.analyze(query, results, task_type="knowledge_summary"))
        if llm_content:
            content = llm_content
        else:
            llm_source = "template_fallback"
            content = _generate_template_content(query, results)
    except asyncio.TimeoutError:
        llm_source = "timeout_fallback"
        content = f"## 关于「{query}」的情报简报\n\n### ⚠️ 服务响应超时\n\n当前智能摘要服务响应较慢，系统已自动降级为结构化数据展示。\n\n"
        content += _generate_template_content(query, results)
    except Exception as e:
        print(f"LLM compose_delivery fallback: {e}")
        llm_source = "error_fallback"
        content = f"## 关于「{query}」的情报简报\n\n### ⚠️ 摘要生成异常\n\n智能摘要服务暂时不可用，系统已自动降级。以下是原始检索结果：\n\n"
        content += _generate_template_content(query, results)

    return {
        "status": "success",
        "content": content,
        "sources": [{"name": r.get('source_name', ''), "url": r.get('source_url', '')} for r in results if r.get('source_url')],
        "delivery_type": "intelligence_brief",
        "execution_summary": {"intent": intent, "kb_hits": len(results), "source": llm_source},
        "next_actions": ["重试生成摘要", "查看详细数据"]
    }
