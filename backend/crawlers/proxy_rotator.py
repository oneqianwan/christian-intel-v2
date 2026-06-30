"""
代理池模块 — 自动轮换IP，防封禁
"""

from typing import List, Optional


class ProxyRotator:
    """代理池管理器"""

    def __init__(self, proxies: Optional[List[str]] = None):
        # 默认免费代理池（生产环境应接入付费代理服务）
        self.proxies = proxies or []
        self.failed_proxies = set()
        self.proxy_index = 0

        # 如果没有传入代理，尝试获取免费代理
        if not self.proxies:
            self._load_default_proxies()

    def _load_default_proxies(self):
        """加载默认代理列表（可替换为付费代理API）"""
        # 注意：免费代理不稳定，生产环境建议用付费服务
        # 如：Bright Data, Smartproxy, Oxylabs 等
        self.proxies = [
            # 占位，实际从配置文件或API读取
        ]
        print(f"[Proxy] 加载了 {len(self.proxies)} 个代理")

    def get_proxy(self) -> Optional[str]:
        """获取一个可用代理"""
        if not self.proxies:
            return None

        # 轮询获取，跳过失败代理
        attempts = 0
        while attempts < len(self.proxies):
            proxy = self.proxies[self.proxy_index % len(self.proxies)]
            self.proxy_index += 1

            if proxy not in self.failed_proxies:
                return proxy

            attempts += 1

        # 所有代理都失败了，重置失败记录
        print("[Proxy] 所有代理都标记为失败，重置失败记录")
        self.failed_proxies.clear()
        return self.proxies[0] if self.proxies else None

    def mark_failed(self, proxy: str):
        """标记代理为失败"""
        self.failed_proxies.add(proxy)
        preview = proxy[:30] + "..." if len(proxy) > 30 else proxy
        print(f"[Proxy] 标记失败: {preview}")

    def get_proxy_dict(self) -> Optional[dict]:
        """获取代理字典格式（requests兼容）"""
        proxy_url = self.get_proxy()
        if not proxy_url:
            return None

        return {
            "http": proxy_url,
            "https": proxy_url,
        }

    @classmethod
    def from_config(cls, proxy_list: List[str]):
        """从配置创建"""
        return cls(proxies=proxy_list)
