"""
动态渲染爬虫 — Playwright + 代理 + 指纹伪装
核心采集引擎
"""

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

try:
    from playwright.async_api import Browser, Page, async_playwright
except ImportError:
    print("[Crawler] Playwright未安装，执行: pip install playwright && playwright install chromium")
    raise

try:
    from .fingerprint_spoofer import FingerprintSpoofer
    from .proxy_rotator import ProxyRotator
    from .rate_limiter import DomainRateLimiter
    from .smart_retry import SmartRetry
except ImportError:
    from fingerprint_spoofer import FingerprintSpoofer
    from proxy_rotator import ProxyRotator
    from rate_limiter import DomainRateLimiter
    from smart_retry import SmartRetry


class DynamicCrawler:
    """
    动态渲染爬虫
    支持：JavaScript渲染、代理轮换、指纹伪装、智能重试
    """

    def __init__(
        self,
        proxy_rotator: Optional[ProxyRotator] = None,
        rate_limiter: Optional[DomainRateLimiter] = None,
        headless: bool = True,
    ):
        self.proxy_rotator = proxy_rotator or ProxyRotator()
        self.rate_limiter = rate_limiter or DomainRateLimiter(default_rps=2.0)
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.playwright = None
        self.active_proxy: Optional[str] = None

    async def start(self):
        """启动浏览器"""
        if self.browser:
            return

        self.playwright = await async_playwright().start()
        args = FingerprintSpoofer.get_playwright_args()
        args["headless"] = self.headless

        self.active_proxy = self.proxy_rotator.get_proxy()
        if self.active_proxy:
            args["proxy"] = {"server": self.active_proxy}
            print(f"[Crawler] 使用代理: {self.active_proxy}")

        try:
            self.browser = await self.playwright.chromium.launch(**args)
        except Exception:
            if self.active_proxy:
                self.proxy_rotator.mark_failed(self.active_proxy)
                print("[Crawler] 代理启动失败，回退直连模式重试")
                self.active_proxy = None
                args.pop("proxy", None)
                self.browser = await self.playwright.chromium.launch(**args)
            else:
                raise

        print("[Crawler] 浏览器已启动")

    async def stop(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
            self.browser = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        print("[Crawler] 浏览器已关闭")

    async def fetch_page(
        self,
        url: str,
        wait_for: str = "networkidle",
        timeout: int = 30000,
        max_retries: int = 3,
        extract_text: bool = True,
    ) -> Dict[str, Any]:
        """
        获取页面内容
        """
        if not self.browser:
            await self.start()

        domain = urlparse(url).netloc
        await self.rate_limiter.acquire(domain)

        retry_handler = SmartRetry(
            max_retries=max(0, int(max_retries)),
            base_delay=2.0,
            retry_exceptions=(Exception,),
        )

        return await retry_handler.execute(
            self._fetch_page_internal,
            url,
            wait_for,
            timeout,
            extract_text,
        )

    async def _fetch_page_internal(
        self,
        url: str,
        wait_for: str,
        timeout: int,
        extract_text: bool,
    ) -> Dict[str, Any]:
        """内部获取逻辑（被重试执行）"""
        context = None
        page: Optional[Page] = None
        try:
            context = await self.browser.new_context(
                viewport=FingerprintSpoofer.get_random_viewport(),
                user_agent=FingerprintSpoofer.get_random_user_agent(),
            )
            page = await context.new_page()

            await FingerprintSpoofer.apply_stealth_scripts(page)

            response = await page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout,
            )

            await asyncio.sleep(2)

            title = await page.title()
            html = await page.content()

            text = ""
            if extract_text:
                text = await page.evaluate(
                    """() => document.body ? document.body.innerText : ''"""
                )

            status = response.status if response else 0
            if status >= 400 or status == 0:
                raise RuntimeError(f"HTTP {status} for {url}")

            return {
                "url": url,
                "title": title,
                "html": html[:50000],
                "text": text[:20000],
                "status": status,
                "success": 200 <= status < 300,
                "error": None,
                "proxy": self.active_proxy,
            }
        finally:
            if context:
                await context.close()

    async def fetch_multiple(
        self,
        urls: List[str],
        max_concurrent: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        批量获取多个页面（带并发控制）
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def fetch_with_semaphore(url: str):
            async with semaphore:
                try:
                    return await self.fetch_page(url)
                except Exception as exc:
                    return {
                        "url": url,
                        "title": "",
                        "html": "",
                        "text": "",
                        "status": 0,
                        "success": False,
                        "error": str(exc),
                        "proxy": self.active_proxy,
                    }

        tasks = [fetch_with_semaphore(url) for url in urls]
        return await asyncio.gather(*tasks)


async def fetch_url(url: str, headless: bool = True) -> Dict[str, Any]:
    """便捷函数：获取单个页面"""
    crawler = DynamicCrawler(headless=headless)
    try:
        return await crawler.fetch_page(url)
    finally:
        await crawler.stop()


if __name__ == "__main__":

    async def test():
        crawler = DynamicCrawler()
        try:
            await crawler.start()
            result = await crawler.fetch_page("https://www.christianitytoday.com")
            print(f"URL: {result['url']}")
            print(f"Status: {result['status']}")
            print(f"Title: {result['title'][:100]}")
            print(f"Text length: {len(result['text'])}")
            print(f"Success: {result['success']}")
        finally:
            await crawler.stop()

    asyncio.run(test())
