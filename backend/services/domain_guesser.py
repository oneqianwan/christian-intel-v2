import asyncio
import logging
from typing import List, Optional

import httpx


logger = logging.getLogger(__name__)


class DomainGuesser:
    """
    基于机构名猜测官网域名。
    仅作为 Wikidata / Wikipedia 都失败后的第三来源，必须经过可达性验证。
    """

    COMMON_TLDS = [".org", ".com", ".net", ".edu", ".foundation", ".church", ".ministries"]

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=10.0,
            follow_redirects=True,
            headers={"User-Agent": "CIO-Bot/1.0 (christian-intel-v2; domain guesser)"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    def generate_candidates(self, org_name: str, country: str = None) -> List[str]:
        if not org_name:
            return []

        candidates: List[str] = []
        name_lower = org_name.lower().strip()

        clean_name = name_lower
        suffixes = [
            " international",
            " global",
            " inc",
            " ltd",
            " limited",
            " foundation",
            " ministry",
            " ministries",
            " church",
            " association",
            " council",
            " union",
            " college",
            " university",
            " institute",
        ]
        for suffix in suffixes:
            clean_name = clean_name.replace(suffix, "").strip()

        direct = (
            clean_name.replace(" ", "")
            .replace("'", "")
            .replace(",", "")
            .replace(".", "")
            .replace("&", "and")
        )
        if not direct:
            return []

        candidates.append(f"https://www.{direct}.org")
        candidates.append(f"https://{direct}.org")
        candidates.append(f"https://www.{direct}.com")
        candidates.append(f"https://{direct}.com")

        words = [w for w in clean_name.replace("&", " ").split() if w]
        if len(words) >= 2:
            acronym = "".join([w[0] for w in words if w[0].isalpha()])
            if len(acronym) >= 2:
                candidates.append(f"https://www.{acronym}.org")
                candidates.append(f"https://{acronym}.org")
                candidates.append(f"https://www.{acronym}.com")

        if len(words) >= 2:
            two_words = f"{words[0]}{words[1]}"
            candidates.append(f"https://www.{two_words}.org")
            candidates.append(f"https://{two_words}.org")

        if country:
            country_tld_map = {
                "philippines": ".ph",
                "united kingdom": ".org.uk",
                "south korea": ".or.kr",
                "australia": ".org.au",
                "canada": ".ca",
                "germany": ".de",
                "france": ".fr",
            }
            country_lower = country.lower().strip()
            tld = country_tld_map.get(country_lower)
            if tld:
                candidates.append(f"https://www.{direct}{tld}")
                if len(words) >= 2:
                    candidates.append(f"https://www.{words[0]}{tld}")

        seen = set()
        unique: List[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique.append(candidate)
        return unique[:8]

    async def verify_url(self, url: str) -> bool:
        try:
            response = await self.client.head(url, timeout=8.0)
            if response.status_code == 200:
                return True
            if response.status_code in [403, 405]:
                response = await self.client.get(url, timeout=8.0)
                return response.status_code == 200
        except Exception:
            return False
        return False

    async def guess_and_verify(self, org_name: str, country: str = None) -> Optional[str]:
        candidates = self.generate_candidates(org_name, country)
        for url in candidates:
            if await self.verify_url(url):
                logger.info("域名猜测成功: %s -> %s", org_name, url)
                return url
        return None


def guess_url_sync(org_name: str, country: str = None) -> Optional[str]:
    async def _runner() -> Optional[str]:
        guesser = DomainGuesser()
        try:
            return await guesser.guess_and_verify(org_name, country)
        finally:
            await guesser.close()

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_runner())
        except Exception as e:
            logger.error("域名猜测失败 %s: %s", org_name, str(e)[:200])
            return None
        finally:
            loop.close()
    except Exception as e:
        logger.error("域名猜测失败 %s: %s", org_name, str(e)[:200])
        return None
