import os
import shutil
from datetime import datetime
from html import escape
from typing import Any, Dict, List


def generate_pdf_content(query: str, country: str, items: List[Dict[str, Any]], execution_summary: Dict[str, Any]) -> str:
    html_parts: List[str] = []

    q = escape(query or "")
    c = escape(country or "")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    sources_scanned = escape(str(execution_summary.get("sources_scanned", "N/A")))
    items_found = escape(str(execution_summary.get("items_found", len(items))))
    countries = escape(str(execution_summary.get("countries", "菲律宾/美国/韩国/尼日利亚")))

    html_parts.append(
        f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>基督教情报简报 - {c}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 40px;
        }}
        .header {{
            border-bottom: 3px solid #f59e0b;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            color: #1a1a1a;
            font-size: 28px;
            margin: 0;
        }}
        .meta {{
            color: #666;
            font-size: 14px;
            margin-top: 10px;
        }}
        .summary {{
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            padding: 20px;
            margin: 20px 0;
            border-radius: 8px;
        }}
        .item {{
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 20px;
            margin: 15px 0;
            background: #fafafa;
        }}
        .item-title {{
            font-size: 18px;
            font-weight: 600;
            color: #1a1a1a;
            margin-bottom: 8px;
        }}
        .item-meta {{
            color: #666;
            font-size: 13px;
            margin-bottom: 10px;
        }}
        .item-source {{
            color: #4f46e5;
            font-size: 13px;
        }}
        .score {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }}
        .score-high {{ background: #fee2e2; color: #dc2626; }}
        .score-medium {{ background: #fef3c7; color: #d97706; }}
        .footer {{
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e5e7eb;
            color: #999;
            font-size: 12px;
            text-align: center;
        }}
    </style>
</head>
<body>
"""
    )

    html_parts.append(
        f"""
    <div class="header">
        <h1>基督教情报简报</h1>
        <div class="meta">
            查询：{q} | 国家：{c} |
            生成时间：{now_str} |
            来源：Christian Intel v2
        </div>
    </div>
"""
    )

    html_parts.append(
        f"""
    <div class="summary">
        <strong>执行摘要</strong><br>
        本次共扫描 {sources_scanned} 个来源，
        发现 {items_found} 条相关情报。
        按质量评分筛选出TOP {len(items)} 条高价值情报。
    </div>
"""
    )

    for i, item in enumerate(items or [], 1):
        title = escape(str(item.get("title") or "无标题"))
        source_name = escape(str(item.get("source_name") or "N/A"))
        source_url = str(item.get("source_url") or "#")
        published_at = str(item.get("published_at") or "")
        published_date = escape(published_at[:10]) if published_at else "N/A"

        score_val = item.get("score", 0)
        try:
            score_int = int(score_val)
        except Exception:
            score_int = 0

        score_class = "score-high" if score_int >= 70 else "score-medium"
        score_label = escape(f"{score_int}分" if score_val is not None else "N/A")

        safe_href = escape(source_url, quote=True)

        html_parts.append(
            f"""
    <div class="item">
        <div class="item-title">{i}. {title}</div>
        <div class="item-meta">
            <span class="score {score_class}">{score_label}</span> |
            来源：{source_name} |
            时间：{published_date}
        </div>
        <div class="item-source">
            <a href="{safe_href}">查看原文 →</a>
        </div>
    </div>
"""
        )

    html_parts.append(
        f"""
    <div class="footer">
        本简报由 Christian Intel v2 自动生成 |
        数据覆盖：{countries} |
        系统版本：v0.2.0
    </div>
</body>
</html>
"""
    )

    return "\n".join(html_parts)


def _resolve_wkhtmltopdf_path() -> str | None:
    candidates = [
        shutil.which("wkhtmltopdf"),
        r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe",
        r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def html_to_pdf(html_content: str, output_path: str | None = None) -> str:
    """将HTML简报转为PDF；失败时自动降级为HTML文件。"""

    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "exports"))
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"brief_{timestamp}.pdf")
    else:
        output_path = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

    try:
        import pdfkit

        wkhtmltopdf_path = _resolve_wkhtmltopdf_path()
        config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path) if wkhtmltopdf_path else None
        options = {
            "encoding": "UTF-8",
            "enable-local-file-access": None,
            "quiet": "",
        }
        pdfkit.from_string(html_content, output_path, configuration=config, options=options)
        return output_path
    except Exception:
        try:
            from weasyprint import HTML

            HTML(string=html_content).write_pdf(output_path)
            return output_path
        except Exception:
            html_path = output_path.replace(".pdf", ".html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            return html_path
