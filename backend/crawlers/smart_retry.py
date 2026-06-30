"""
智能重试模块 — 指数退避，自动处理常见错误
"""

import asyncio
import random
from functools import wraps
from typing import Callable, Optional, Tuple, Type


class SmartRetry:
    """智能重试装饰器"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
        on_retry: Optional[Callable] = None,
    ):
        """
        Args:
            max_retries: 最大重试次数
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
            exponential_base: 指数退避基数
            retry_exceptions: 需要重试的异常类型
            on_retry: 重试时的回调函数
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retry_exceptions = retry_exceptions
        self.on_retry = on_retry

    def calculate_delay(self, attempt: int) -> float:
        """计算第attempt次重试的延迟时间（指数退避+抖动）"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        jitter = delay * random.uniform(0, 0.3)
        return min(delay + jitter, self.max_delay)

    async def execute(self, func: Callable, *args, **kwargs):
        """执行函数，失败时自动重试"""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except self.retry_exceptions as exc:
                last_exception = exc

                if attempt >= self.max_retries:
                    print(f"[SmartRetry] 最终失败（已重试{self.max_retries}次）: {exc}")
                    raise last_exception

                delay = self.calculate_delay(attempt)
                print(f"[SmartRetry] 第{attempt + 1}次失败: {exc}，{delay:.1f}s后重试...")

                if self.on_retry:
                    self.on_retry(attempt, exc, delay)

                await asyncio.sleep(delay)

        raise last_exception

    def __call__(self, func: Callable):
        """装饰器模式"""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.execute(func, *args, **kwargs)

        return wrapper


def retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    retry_exceptions: Tuple[Type[Exception], ...] = (Exception,),
):
    """快速重试装饰器"""

    def decorator(func: Callable):
        replayer = SmartRetry(
            max_retries=max_retries,
            base_delay=base_delay,
            retry_exceptions=retry_exceptions,
        )
        return replayer(func)

    return decorator
