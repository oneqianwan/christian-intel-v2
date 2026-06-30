"""
浏览器指纹伪装模块 — 绕过headless检测
"""

import random


class FingerprintSpoofer:
    """浏览器指纹伪装器"""

    # 真实浏览器User-Agent池
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    ]

    # 常见viewport尺寸
    VIEWPORTS = [
        {"width": 1920, "height": 1080},
        {"width": 1366, "height": 768},
        {"width": 1440, "height": 900},
        {"width": 1536, "height": 864},
        {"width": 1280, "height": 720},
    ]

    @classmethod
    def get_random_user_agent(cls) -> str:
        return random.choice(cls.USER_AGENTS)

    @classmethod
    def get_random_viewport(cls) -> dict:
        return random.choice(cls.VIEWPORTS)

    @classmethod
    def get_playwright_args(cls) -> dict:
        """
        获取Playwright启动参数（绕过headless检测）
        """
        viewport = cls.get_random_viewport()

        return {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                f"--window-size={viewport['width']},{viewport['height']}",
                "--start-maximized",
                "--disable-extensions",
                "--disable-default-apps",
                "--lang=en-US,en",
            ],
        }

    @classmethod
    async def apply_stealth_scripts(cls, page):
        """
        在Playwright页面中注入反检测脚本
        需要在page.goto()之前调用
        """
        await page.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            window.chrome = {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            """
        )
        return page
