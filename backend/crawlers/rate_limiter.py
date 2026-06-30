"""
并发控制模块 — 限制请求频率，防封禁
"""

import asyncio
import time


class RateLimiter:
    """请求频率限制器"""

    def __init__(self, requests_per_second: float = 2.0, burst: int = 3):
        """
        Args:
            requests_per_second: 每秒最大请求数
            burst: 突发请求数（允许短时间内超过限制）
        """
        self.requests_per_second = max(requests_per_second, 0.1)
        self.min_interval = 1.0 / self.requests_per_second
        self.burst = max(burst, 1)
        self.last_request_time = 0.0
        self.request_count = 0
        self.lock = asyncio.Lock()

    async def acquire(self):
        """获取请求许可，如果超限则等待"""
        async with self.lock:
            now = time.time()

            # 每秒窗口重置
            if now - self.last_request_time >= 1.0:
                self.request_count = 0

            if self.request_count >= self.burst:
                wait_time = self.min_interval - (now - self.last_request_time)
                if wait_time > 0:
                    print(f"[RateLimiter] 等待 {wait_time:.2f}s")
                    await asyncio.sleep(wait_time)
                    now = time.time()
                    if now - self.last_request_time >= 1.0:
                        self.request_count = 0

            self.last_request_time = now
            self.request_count += 1

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False


class DomainRateLimiter:
    """按域名分别限流"""

    def __init__(self, default_rps: float = 2.0):
        self.default_rps = default_rps
        self.limiters = {}

    def get_limiter(self, domain: str) -> RateLimiter:
        """获取指定域名的限流器"""
        if domain not in self.limiters:
            self.limiters[domain] = RateLimiter(self.default_rps)
        return self.limiters[domain]

    async def acquire(self, domain: str):
        """对指定域名获取请求许可"""
        limiter = self.get_limiter(domain)
        await limiter.acquire()
