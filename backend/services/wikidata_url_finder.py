import asyncio
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import httpx
from urllib.parse import unquote, urlparse


logger = logging.getLogger(__name__)


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
DEFAULT_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
DEFAULT_USER_AGENT = "CIO-Bot/1.0 (christian-intel-v2; wikidata P856 fetch)"


def _normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _escape_sparql_string(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


def _chunk(items: List[str], size: int) -> List[List[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass(frozen=True)
class WikidataURLResult:
    name: str
    official_website: str
    wikidata_id: Optional[str] = None
    wikidata_label: Optional[str] = None


class WikidataURLFinder:
    def __init__(
        self,
        timeout_seconds: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
        max_retries: int = 3,
        sparql_batch_size: int = 25,
        api_fallback_limit: int = 10,
    ):
        self._timeout = httpx.Timeout(timeout_seconds)
        self._user_agent = user_agent
        self._max_retries = max_retries
        self._sparql_batch_size = max(1, min(int(sparql_batch_size), 50))
        self._api_fallback_limit = max(0, int(api_fallback_limit))
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    def _build_sparql_query(self, org_names: List[str]) -> str:
        escaped = [_escape_sparql_string(n) for n in org_names if n]
        values_clause = " ".join([f'"{n}"' for n in escaped])

        return f"""
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX bd: <http://www.bigdata.com/rdf#>
PREFIX mwapi: <https://www.mediawiki.org/ontology#API/>

SELECT ?orgName ?item ?itemLabel ?officialWebsite
WHERE {{
  VALUES ?orgName {{ {values_clause} }}

  SERVICE wikibase:mwapi {{
    bd:serviceParam wikibase:endpoint "www.wikidata.org" .
    bd:serviceParam wikibase:api "EntitySearch" .
    bd:serviceParam mwapi:search ?orgName .
    bd:serviceParam mwapi:language "en" .
    bd:serviceParam mwapi:limit "3" .
    ?item wikibase:apiOutputItem mwapi:item .
  }}

  ?item wdt:P31/wdt:P279* wd:Q43229 .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
  OPTIONAL {{ ?item wdt:P856 ?officialWebsite . }}
}}
LIMIT 500
""".strip()

    async def find_urls_batch(self, org_names: List[str]) -> Dict[str, str]:
        names = [n for n in org_names if n and n.strip()]
        if not names:
            return {}

        results: Dict[str, str] = {}
        norm_to_original: Dict[str, str] = {}
        for name in names:
            norm_to_original.setdefault(_normalize_name(name), name)

        for idx, batch in enumerate(_chunk(list(norm_to_original.values()), self._sparql_batch_size), 1):
            batch_results = await self._query_batch(batch)
            results.update(batch_results)
            logger.info("Wikidata查询进度: %s/%s", min(idx * self._sparql_batch_size, len(norm_to_original)), len(norm_to_original))

        return results

    async def find_urls_from_wikipedia_urls(self, org_wikipedia_urls: Dict[str, str]) -> Dict[str, str]:
        items = [(name, url) for name, url in (org_wikipedia_urls or {}).items() if name and url]
        if not items:
            return {}

        host_to_titles: Dict[str, Dict[str, List[str]]] = {}
        name_to_page_key: Dict[str, str] = {}
        for name, wiki_url in items:
            parsed = urlparse(wiki_url)
            if not parsed.netloc:
                continue
            host = parsed.netloc.lower()
            path = parsed.path or ""
            if "/wiki/" not in path:
                continue
            title = unquote(path.split("/wiki/", 1)[1]).replace("_", " ").strip()
            if not title:
                continue
            page_key = f"{host}::{title}"
            name_to_page_key[name] = page_key
            host_to_titles.setdefault(host, {}).setdefault(title, [])

        page_key_to_qid: Dict[str, str] = {}
        for host, titles_dict in host_to_titles.items():
            titles = list(titles_dict.keys())
            api_url = f"https://{host}/w/api.php" if host.endswith("wikipedia.org") else DEFAULT_WIKIPEDIA_API
            for batch in _chunk(titles, 50):
                data = await self._request_json_with_retry(
                    "GET",
                    api_url,
                    params={
                        "action": "query",
                        "format": "json",
                        "prop": "pageprops",
                        "ppprop": "wikibase_item",
                        "redirects": 1,
                        "titles": "|".join(batch),
                    },
                    headers={"User-Agent": self._user_agent},
                )
                if not data:
                    continue

                pages = (data.get("query") or {}).get("pages") or {}
                for page in pages.values():
                    title = (page or {}).get("title") or ""
                    props = (page or {}).get("pageprops") or {}
                    qid = props.get("wikibase_item") or ""
                    if not title or not qid:
                        continue
                    page_key_to_qid[f"{host}::{title}"] = qid

        qids = list({qid for qid in page_key_to_qid.values() if qid})
        if not qids:
            return {}

        qid_to_url: Dict[str, str] = {}
        for qid_batch in _chunk(qids, 50):
            qid_to_url.update(await self._get_p856_bulk(qid_batch))

        results: Dict[str, str] = {}
        for name, page_key in name_to_page_key.items():
            qid = page_key_to_qid.get(page_key)
            if not qid:
                continue
            url = qid_to_url.get(qid)
            if url:
                results[name] = url

        return results

    async def _request_json_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        headers: Optional[dict] = None,
    ) -> Optional[dict]:
        merged_headers = {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
        }
        if headers:
            merged_headers.update(headers)

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.request(
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=merged_headers,
                )

                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = min(30.0, 1.5 * (2**attempt))
                    await asyncio.sleep(wait)
                    continue

                if resp.status_code != 200:
                    return None

                return resp.json()
            except (asyncio.TimeoutError, httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                wait = min(30.0, 1.5 * (2**attempt))
                await asyncio.sleep(wait)
            except Exception as e:
                last_error = e
                break

        if last_error:
            logger.warning("Wikidata请求失败: %s", str(last_error)[:200])
        return None

    async def _query_batch(self, names: List[str]) -> Dict[str, str]:
        results: Dict[str, str] = {}

        sparql_query = self._build_sparql_query(names)
        data = await self._request_json_with_retry(
            "POST",
            WIKIDATA_SPARQL,
            params={"format": "json"},
            data={"query": sparql_query},
            headers={"Accept": "application/sparql-results+json"},
        )

        if data:
            bindings = (data.get("results") or {}).get("bindings") or []
            for binding in bindings:
                org_name = (binding.get("orgName") or {}).get("value") or ""
                website = (binding.get("officialWebsite") or {}).get("value") or ""
                if not org_name or not website:
                    continue
                results.setdefault(org_name, website)

        unmatched = [n for n in names if n and n not in results]
        if not unmatched:
            return results

        limit = min(len(unmatched), self._api_fallback_limit)
        for name in unmatched[:limit]:
            url = await self._search_wikidata_api(name)
            if url:
                results[name] = url

        return results

    async def _search_wikidata_api(self, name: str) -> Optional[str]:
        search_data = await self._request_json_with_retry(
            "GET",
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "search": name,
                "type": "item",
                "limit": 10,
            },
        )
        if not search_data:
            return None

        entity_ids = []
        for result in (search_data.get("search") or [])[:10]:
            entity_id = result.get("id") or ""
            if entity_id:
                entity_ids.append(entity_id)

        if not entity_ids:
            return None

        p856_map = await self._get_p856_bulk(entity_ids)
        for entity_id in entity_ids:
            url = p856_map.get(entity_id)
            if url:
                return url
        return None

    async def _get_p856(self, entity_id: str) -> Optional[str]:
        data = await self._request_json_with_retry(
            "GET",
            WIKIDATA_API,
            params={
                "action": "wbgetclaims",
                "format": "json",
                "entity": entity_id,
                "property": "P856",
            },
        )
        if not data:
            return None

        claims = (data.get("claims") or {}).get("P856") or []
        if not claims:
            return None

        try:
            return (
                claims[0]
                .get("mainsnak", {})
                .get("datavalue", {})
                .get("value", "")
            ) or None
        except Exception:
            return None

    async def _get_p856_bulk(self, entity_ids: List[str]) -> Dict[str, str]:
        ids = [eid for eid in entity_ids if eid]
        if not ids:
            return {}

        data = await self._request_json_with_retry(
            "GET",
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": "|".join(ids[:50]),
                "props": "claims",
            },
        )
        if not data:
            return {}

        entities = data.get("entities") or {}
        results: Dict[str, str] = {}
        for entity_id, payload in entities.items():
            claims = (payload or {}).get("claims") or {}
            p856_claims = claims.get("P856") or []
            if not p856_claims:
                continue
            try:
                url = (
                    p856_claims[0]
                    .get("mainsnak", {})
                    .get("datavalue", {})
                    .get("value", "")
                )
                if url:
                    results[entity_id] = url
            except Exception:
                continue
        return results


def find_urls_sync(org_names: List[str]) -> Dict[str, str]:
    async def _runner() -> Dict[str, str]:
        async with WikidataURLFinder() as finder:
            return await finder.find_urls_batch(org_names)

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_runner())
        finally:
            loop.close()


def find_urls_from_wikipedia_sync(org_wikipedia_urls: Dict[str, str]) -> Dict[str, str]:
    async def _runner() -> Dict[str, str]:
        async with WikidataURLFinder() as finder:
            return await finder.find_urls_from_wikipedia_urls(org_wikipedia_urls)

    try:
        return asyncio.run(_runner())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(_runner())
        finally:
            loop.close()
