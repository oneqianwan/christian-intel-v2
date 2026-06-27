import time
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from models.database import Source


def check_source_health(source: Source) -> dict:
    """检查单个来源的健康状态"""
    result = {
        "source_id": source.id,
        "name": source.name,
        "url": source.url,
        "status": "unknown",
        "http_code": None,
        "response_time_ms": None,
        "error": None,
        "recommendation": None,
    }

    try:
        start = time.time()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        resp = httpx.get(
            source.url,
            headers=headers,
            timeout=15,
            follow_redirects=True,
            verify=False,
        )

        result["response_time_ms"] = int((time.time() - start) * 1000)
        result["http_code"] = resp.status_code

        if resp.status_code == 200:
            result["status"] = "healthy"
            source.success_rate = min(1.0, (source.success_rate or 1.0) * 0.9 + 0.1)
        elif resp.status_code in [301, 302, 307, 308]:
            result["status"] = "redirected"
            result["recommendation"] = f"返回{resp.status_code}重定向，检查最终URL"
        elif resp.status_code == 404:
            result["status"] = "not_found"
            result["recommendation"] = "页面不存在，建议停用或更新URL"
            source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.5)
        elif resp.status_code == 403:
            result["status"] = "forbidden"
            result["recommendation"] = "访问被拒绝，可能需要更换请求头或使用代理"
            source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.7)
        elif resp.status_code >= 500:
            result["status"] = "server_error"
            result["recommendation"] = "服务器错误，可能是临时问题，建议稍后重试"
            source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.6)
        else:
            result["status"] = f"http_{resp.status_code}"
            source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.8)

    except httpx.TimeoutException:
        result["status"] = "timeout"
        result["error"] = "请求超时（15秒）"
        result["recommendation"] = "响应过慢，可能需要降低采集频率或更换源"
        source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.5)
    except httpx.ConnectError:
        result["status"] = "connection_error"
        result["error"] = "无法连接"
        result["recommendation"] = "域名解析失败或服务器下线，建议停用"
        source.success_rate = 0.0
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]
        result["recommendation"] = "未知错误，需要人工检查"
        source.success_rate = max(0.0, (source.success_rate or 1.0) * 0.5)

    source.last_scan_at = datetime.utcnow()

    # 自动停用连续失败的来源
    if source.success_rate is not None and source.success_rate < 0.3:
        source.is_active = False
        result["recommendation"] = "成功率低于30%，已自动停用"

    return result


def run_health_check(db: Session, country: str = None) -> list:
    """对所有活跃来源执行健康检查"""
    query = db.query(Source).filter(Source.is_active == True)
    if country:
        query = query.filter(Source.country == country)
    sources = query.all()

    results = []
    for source in sources:
        result = check_source_health(source)
        results.append(result)

    db.commit()
    return results
