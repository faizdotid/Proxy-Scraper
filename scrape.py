#!/usr/bin/env python3
"""
Proxy Scraper — Ultimate Edition

Deep-search proxy scraper & checker with 65+ public sources supporting
HTTP, HTTPS, SOCKS4, and SOCKS5. Sources include GitHub raw lists,
JSON APIs, and HTML table parsers.

Usage:
    python scrape.py --help
    python scrape.py scrape --all
    python scrape.py scrape --list-sources
    python scrape.py check --file proxies.txt
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import re
import sys
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TIMEOUT = 30
CHECK_TIMEOUT = 10
MAX_WORKERS = 100

PROXY_REGEX = re.compile(
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d):\d{2,5}"
)

HTML_TABLE_PROXY_REGEX = re.compile(
    r"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)</td><td>([0-9]+)</td>"
)

CHECK_URL = "https://httpbin.org/ip"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("proxy_scraper")


# ---------------------------------------------------------------------------
# Enums & Data classes
# ---------------------------------------------------------------------------

class ProxyType(Enum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Proxy:
    ip: str
    port: int
    proxy_type: ProxyType = ProxyType.UNKNOWN

    def __str__(self) -> str:
        return f"{self.ip}:{self.port}"

    def to_dict(self) -> dict[str, str]:
        url = f"{self.proxy_type.value}://{self.ip}:{self.port}"
        return {"http": url, "https": url}


@dataclass
class SourceResult:
    source_name: str
    proxies: list[Proxy]
    elapsed: float
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=20, pool_maxsize=100)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
    )
    return session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_domain(url: str) -> str:
    return urlparse(url).netloc


def parse_proxy(raw: str, proxy_type: ProxyType = ProxyType.UNKNOWN) -> Proxy | None:
    match = PROXY_REGEX.search(raw)
    if not match:
        return None
    ip_str, port_str = match.group(0).split(":")
    try:
        ipaddress.ip_address(ip_str)
        port = int(port_str)
        if not 1 <= port <= 65535:
            return None
    except ValueError:
        return None
    return Proxy(ip=ip_str, port=port, proxy_type=proxy_type)


def guess_proxy_type(url: str) -> ProxyType:
    lowered = url.lower()
    if "socks5" in lowered:
        return ProxyType.SOCKS5
    if "socks4" in lowered:
        return ProxyType.SOCKS4
    if "https" in lowered:
        return ProxyType.HTTPS
    if "http" in lowered:
        return ProxyType.HTTP
    return ProxyType.UNKNOWN


# ---------------------------------------------------------------------------
# Source base class
# ---------------------------------------------------------------------------

class BaseSource(ABC):
    """Abstract base for every proxy source."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.session = create_session()

    @abstractmethod
    def scrape(self) -> SourceResult:
        """Return scraped proxies from this source."""
        ...

    def _fetch(self, url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
        resp = self.session.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.text


# ---------------------------------------------------------------------------
# Raw text source
# ---------------------------------------------------------------------------

class RawTextSource(BaseSource):
    def __init__(
        self,
        name: str,
        urls: list[str],
        proxy_type: ProxyType = ProxyType.UNKNOWN,
    ) -> None:
        super().__init__(name)
        self.urls = urls
        self.proxy_type = proxy_type

    def scrape(self) -> SourceResult:
        start = time.perf_counter()
        proxies: list[Proxy] = []
        errors: list[str] = []
        for url in self.urls:
            try:
                ptype = self.proxy_type if self.proxy_type != ProxyType.UNKNOWN else guess_proxy_type(url)
                text = self._fetch(url)
                for line in text.splitlines():
                    p = parse_proxy(line, proxy_type=ptype)
                    if p and p not in proxies:
                        proxies.append(p)
            except Exception as exc:
                errors.append(f"{extract_domain(url)}: {exc}")
        elapsed = time.perf_counter() - start
        return SourceResult(self.name, proxies, elapsed, errors)


# ---------------------------------------------------------------------------
# HTML table source
# ---------------------------------------------------------------------------

class HtmlTableSource(BaseSource):
    def __init__(
        self,
        name: str,
        urls: list[str],
        proxy_type: ProxyType = ProxyType.UNKNOWN,
    ) -> None:
        super().__init__(name)
        self.urls = urls
        self.proxy_type = proxy_type

    def scrape(self) -> SourceResult:
        start = time.perf_counter()
        proxies: list[Proxy] = []
        errors: list[str] = []
        for url in self.urls:
            try:
                text = self._fetch(url)
                matches = HTML_TABLE_PROXY_REGEX.findall(text)
                for ip, port in matches:
                    p = parse_proxy(f"{ip}:{port}", proxy_type=self.proxy_type)
                    if p and p not in proxies:
                        proxies.append(p)
            except Exception as exc:
                errors.append(f"{extract_domain(url)}: {exc}")
        elapsed = time.perf_counter() - start
        return SourceResult(self.name, proxies, elapsed, errors)


# ---------------------------------------------------------------------------
# JSON API source (single page)
# ---------------------------------------------------------------------------

class JsonApiSource(BaseSource):
    def __init__(
        self,
        name: str,
        urls: list[str],
        proxy_type: ProxyType = ProxyType.UNKNOWN,
        ip_key: str = "ip",
        port_key: str = "port",
        root_path: str | None = None,
    ) -> None:
        super().__init__(name)
        self.urls = urls
        self.proxy_type = proxy_type
        self.ip_key = ip_key
        self.port_key = port_key
        self.root_path = root_path

    def scrape(self) -> SourceResult:
        start = time.perf_counter()
        proxies: list[Proxy] = []
        errors: list[str] = []
        for url in self.urls:
            try:
                text = self._fetch(url)
                data = json.loads(text)
                if self.root_path:
                    for part in self.root_path.split("."):
                        data = data.get(part, {}) if isinstance(data, dict) else []
                if isinstance(data, dict):
                    data = [data]
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    ip = str(item.get(self.ip_key, ""))
                    port = item.get(self.port_key)
                    if ip and port:
                        p = parse_proxy(f"{ip}:{port}", proxy_type=self.proxy_type)
                        if p and p not in proxies:
                            proxies.append(p)
            except Exception as exc:
                errors.append(f"{extract_domain(url)}: {exc}")
        elapsed = time.perf_counter() - start
        return SourceResult(self.name, proxies, elapsed, errors)


# ---------------------------------------------------------------------------
# Deep / paginated JSON source
# ---------------------------------------------------------------------------

class DeepJsonSource(BaseSource):
    """Deep-search a paginated JSON API until exhausted or max_pages reached."""

    def __init__(
        self,
        name: str,
        base_url: str,
        proxy_type: ProxyType = ProxyType.UNKNOWN,
        max_pages: int = 10,
        ip_key: str = "ip",
        port_key: str = "port",
        root_path: str | None = "data",
        page_param: str = "page",
    ) -> None:
        super().__init__(name)
        self.base_url = base_url
        self.proxy_type = proxy_type
        self.max_pages = max_pages
        self.ip_key = ip_key
        self.port_key = port_key
        self.root_path = root_path
        self.page_param = page_param

    def scrape(self) -> SourceResult:
        start = time.perf_counter()
        proxies: list[Proxy] = []
        errors: list[str] = []
        for page in range(1, self.max_pages + 1):
            url = self.base_url.replace(f"{{{self.page_param}}}", str(page))
            try:
                text = self._fetch(url)
                data = json.loads(text)
                if self.root_path:
                    for part in self.root_path.split("."):
                        data = data.get(part, {}) if isinstance(data, dict) else []
                if isinstance(data, dict):
                    data = [data]
                if not data:
                    break
                batch: list[Proxy] = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    ip = str(item.get(self.ip_key, ""))
                    port = item.get(self.port_key)
                    if ip and port:
                        p = parse_proxy(f"{ip}:{port}", proxy_type=self.proxy_type)
                        if p and p not in proxies:
                            batch.append(p)
                if not batch:
                    break
                proxies.extend(batch)
            except Exception as exc:
                errors.append(f"page {page}: {exc}")
                break
        elapsed = time.perf_counter() - start
        return SourceResult(self.name, proxies, elapsed, errors)


# ---------------------------------------------------------------------------
# Source factory helpers
# ---------------------------------------------------------------------------

def _raw(name: str, urls: list[str], ptype: ProxyType = ProxyType.UNKNOWN) -> RawTextSource:
    return RawTextSource(name, urls, ptype)


def _html(name: str, urls: list[str], ptype: ProxyType = ProxyType.UNKNOWN) -> HtmlTableSource:
    return HtmlTableSource(name, urls, ptype)


def _json(
    name: str,
    urls: list[str],
    ptype: ProxyType = ProxyType.UNKNOWN,
    ip_key: str = "ip",
    port_key: str = "port",
    root_path: str | None = None,
) -> JsonApiSource:
    return JsonApiSource(name, urls, ptype, ip_key, port_key, root_path)


def _deep_json(
    name: str,
    url: str,
    ptype: ProxyType = ProxyType.UNKNOWN,
    max_pages: int = 10,
    ip_key: str = "ip",
    port_key: str = "port",
    root_path: str | None = "data",
) -> DeepJsonSource:
    return DeepJsonSource(name, url, ptype, max_pages, ip_key, port_key, root_path)


# ---------------------------------------------------------------------------
# Master source registry — 65+ sources
# ---------------------------------------------------------------------------

def build_sources() -> list[BaseSource]:
    s: list[BaseSource] = []
    H = ProxyType.HTTP
    S = ProxyType.HTTPS
    C4 = ProxyType.SOCKS4
    C5 = ProxyType.SOCKS5
    U = ProxyType.UNKNOWN

    # ═══════════════════════════════════════════════════════════════════════
    # GITHUB RAW TEXT SOURCES
    # ═══════════════════════════════════════════════════════════════════════

    # TheSpeedX
    s.append(_raw("github-thespeedx-http", ["https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"], H))
    s.append(_raw("github-thespeedx-socks4", ["https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt"], C4))
    s.append(_raw("github-thespeedx-socks5", ["https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"], C5))

    # clarketm
    s.append(_raw("github-clarketm", ["https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt"], U))

    # jetkai
    s.append(_raw("github-jetkai", ["https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies.txt"], U))

    # monosans
    s.append(_raw("github-monosans-http", ["https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt"], H))
    s.append(_raw("github-monosans-socks4", ["https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt"], C4))
    s.append(_raw("github-monosans-socks5", ["https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"], C5))

    # proxylist-to
    s.append(_raw("github-proxylist-http", ["https://raw.githubusercontent.com/proxylist-to/proxy-list/main/http.txt"], H))
    s.append(_raw("github-proxylist-socks4", ["https://raw.githubusercontent.com/proxylist-to/proxy-list/main/socks4.txt"], C4))
    s.append(_raw("github-proxylist-socks5", ["https://raw.githubusercontent.com/proxylist-to/proxy-list/main/socks5.txt"], C5))

    # iplocate
    s.append(_raw("github-iplocate-http", ["https://raw.githubusercontent.com/iplocate/free-proxy-list/main/http.txt"], H))
    s.append(_raw("github-iplocate-https", ["https://raw.githubusercontent.com/iplocate/free-proxy-list/main/https.txt"], S))
    s.append(_raw("github-iplocate-socks4", ["https://raw.githubusercontent.com/iplocate/free-proxy-list/main/socks4.txt"], C4))
    s.append(_raw("github-iplocate-socks5", ["https://raw.githubusercontent.com/iplocate/free-proxy-list/main/socks5.txt"], C5))

    # proxifly (GitHub raw)
    s.append(_raw("github-proxifly-http", ["https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/http.txt"], H))
    s.append(_raw("github-proxifly-https", ["https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/https.txt"], S))
    s.append(_raw("github-proxifly-socks4", ["https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/socks4.txt"], C4))
    s.append(_raw("github-proxifly-socks5", ["https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/socks5.txt"], C5))

    # gfpcom (GetFreeProxy) — massive lists
    s.append(_raw("github-gfpcom-http", ["https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/http.txt"], H))
    s.append(_raw("github-gfpcom-https", ["https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/https.txt"], S))
    s.append(_raw("github-gfpcom-socks4", ["https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/socks4.txt"], C4))
    s.append(_raw("github-gfpcom-socks5", ["https://raw.githubusercontent.com/wiki/gfpcom/free-proxy-list/lists/socks5.txt"], C5))

    # VPSLab — multiple categories
    s.append(_raw("github-vpslab-http", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_all.txt"], H))
    s.append(_raw("github-vpslab-http-ssl", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_ssl.txt"], S))
    s.append(_raw("github-vpslab-http-nossl", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_nossl.txt"], H))
    s.append(_raw("github-vpslab-http-elite", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_elite.txt"], H))
    s.append(_raw("github-vpslab-http-anonymous", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_anonymous.txt"], H))
    s.append(_raw("github-vpslab-http-transparent", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/http_transparent.txt"], H))
    s.append(_raw("github-vpslab-socks4", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks4_all.txt"], C4))
    s.append(_raw("github-vpslab-socks5", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/socks5_all.txt"], C5))
    s.append(_raw("github-vpslab-all", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_proxies.txt"], U))
    s.append(_raw("github-vpslab-all-elite", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_elite.txt"], U))
    s.append(_raw("github-vpslab-all-anonymous", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_anonymous.txt"], U))
    s.append(_raw("github-vpslab-all-transparent", ["https://raw.githubusercontent.com/VPSLabCloud/VPSLab-Free-Proxy-List/main/all_transparent.txt"], U))

    # Thordata — daily verified
    s.append(_raw("github-thordata-http", ["https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/http.txt"], H))
    s.append(_raw("github-thordata-https", ["https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/https.txt"], S))
    s.append(_raw("github-thordata-socks4", ["https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/socks4.txt"], C4))
    s.append(_raw("github-thordata-socks5", ["https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/socks5.txt"], C5))
    s.append(_raw("github-thordata-all", ["https://raw.githubusercontent.com/Thordata/awesome-free-proxy-list/main/proxies/all.txt"], U))

    # Proxifly via jsDelivr CDN (high availability)
    s.append(_raw("cdn-proxifly-http", ["https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt"], H))
    s.append(_raw("cdn-proxifly-socks4", ["https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks4/data.txt"], C4))
    s.append(_raw("cdn-proxifly-socks5", ["https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.txt"], C5))
    s.append(_raw("cdn-proxifly-all", ["https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/all/data.txt"], U))

    # SevenworksDev
    s.append(_raw("github-sevenworks-http", ["https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/http.txt"], H))
    s.append(_raw("github-sevenworks-socks4", ["https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks4.txt"], C4))
    s.append(_raw("github-sevenworks-socks5", ["https://raw.githubusercontent.com/SevenworksDev/proxy-list/main/proxies/socks5.txt"], C5))

    # MuRongPIG
    s.append(_raw("github-murongpig-http", ["https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt"], H))
    s.append(_raw("github-murongpig-socks4", ["https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks4.txt"], C4))
    s.append(_raw("github-murongpig-socks5", ["https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/socks5.txt"], C5))

    # prxchk
    s.append(_raw("github-prxchk-http", ["https://raw.githubusercontent.com/prxchk/proxy-list/main/http.txt"], H))
    s.append(_raw("github-prxchk-socks4", ["https://raw.githubusercontent.com/prxchk/proxy-list/main/socks4.txt"], C4))
    s.append(_raw("github-prxchk-socks5", ["https://raw.githubusercontent.com/prxchk/proxy-list/main/socks5.txt"], C5))

    # zevtyardt
    s.append(_raw("github-zevtyardt-http", ["https://raw.githubusercontent.com/zevtyardt/proxy-list/main/http.txt"], H))
    s.append(_raw("github-zevtyardt-socks4", ["https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks4.txt"], C4))
    s.append(_raw("github-zevtyardt-socks5", ["https://raw.githubusercontent.com/zevtyardt/proxy-list/main/socks5.txt"], C5))

    # rdavydov
    s.append(_raw("github-rdavydov-http", ["https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/http.txt"], H))
    s.append(_raw("github-rdavydov-socks4", ["https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/socks4.txt"], C4))
    s.append(_raw("github-rdavydov-socks5", ["https://raw.githubusercontent.com/rdavydov/proxy-list/main/proxies/socks5.txt"], C5))

    # proxy4parsing
    s.append(_raw("github-proxy4parsing", ["https://raw.githubusercontent.com/proxy4parsing/proxy-list/main/http.txt"], H))

    # hookzof
    s.append(_raw("github-hookzof-socks5", ["https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt"], C5))

    # ShiftyTR
    s.append(_raw("github-shiftytr-http", ["https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"], H))
    s.append(_raw("github-shiftytr-socks4", ["https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt"], C4))
    s.append(_raw("github-shiftytr-socks5", ["https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt"], C5))

    # zloi-user
    s.append(_raw("github-zloi-hideip", ["https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt"], H))

    # sunny9577
    s.append(_raw("github-sunny9577", ["https://raw.githubusercontent.com/sunny9577/proxy-scraper-checker/master/proxies.txt"], U))

    # mmpx12
    s.append(_raw("github-mmpx12", ["https://raw.githubusercontent.com/mmpx12/proxy-list/master/proxies.txt"], U))

    # Anonym0usWork1221
    s.append(_raw("github-anonym0us-http", ["https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/http_proxies.txt"], H))
    s.append(_raw("github-anonym0us-socks4", ["https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks4_proxies.txt"], C4))
    s.append(_raw("github-anonym0us-socks5", ["https://raw.githubusercontent.com/Anonym0usWork1221/Free-Proxies/main/proxy_files/socks5_proxies.txt"], C5))

    # roosterkid
    s.append(_raw("github-roosterkid", ["https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt"], S))

    # ═══════════════════════════════════════════════════════════════════════
    # APIs — direct endpoints
    # ═══════════════════════════════════════════════════════════════════════

    # proxy-list.download
    s.append(_raw("api-proxylist-http", ["https://www.proxy-list.download/api/v1/get?type=http"], H))
    s.append(_raw("api-proxylist-https", ["https://www.proxy-list.download/api/v1/get?type=https"], S))
    s.append(_raw("api-proxylist-socks4", ["https://www.proxy-list.download/api/v1/get?type=socks4"], C4))
    s.append(_raw("api-proxylist-socks5", ["https://www.proxy-list.download/api/v1/get?type=socks5"], C5))

    # proxyscrape v2
    s.append(_raw("api-proxyscrape-http", ["https://api.proxyscrape.com/?request=getproxies&proxytype=http&timeout=10000&country=all&ssl=all&anonymity=all"], H))
    s.append(_raw("api-proxyscrape-socks4", ["https://api.proxyscrape.com/?request=getproxies&proxytype=socks4&timeout=10000&country=all"], C4))
    s.append(_raw("api-proxyscrape-socks5", ["https://api.proxyscrape.com/?request=getproxies&proxytype=socks5&timeout=10000&country=all"], C5))

    # pubproxy
    s.append(_raw("api-pubproxy", ["http://pubproxy.com/api/proxy?limit=100&format=txt"], U))

    # ═══════════════════════════════════════════════════════════════════════
    # DEEP JSON APIs (paginated)
    # ═══════════════════════════════════════════════════════════════════════

    # GeoNode — deep search up to 20 pages (500 per page = 10k proxies)
    s.append(_deep_json(
        "deep-geonode-http",
        "https://proxylist.geonode.com/api/proxy-list?protocols=http&limit=500&page={page}&sort_by=lastChecked&sort_type=desc",
        H, max_pages=20, ip_key="ip", port_key="port", root_path="data",
    ))
    s.append(_deep_json(
        "deep-geonode-https",
        "https://proxylist.geonode.com/api/proxy-list?protocols=https&limit=500&page={page}&sort_by=lastChecked&sort_type=desc",
        S, max_pages=20, ip_key="ip", port_key="port", root_path="data",
    ))
    s.append(_deep_json(
        "deep-geonode-socks4",
        "https://proxylist.geonode.com/api/proxy-list?protocols=socks4&limit=500&page={page}&sort_by=lastChecked&sort_type=desc",
        C4, max_pages=20, ip_key="ip", port_key="port", root_path="data",
    ))
    s.append(_deep_json(
        "deep-geonode-socks5",
        "https://proxylist.geonode.com/api/proxy-list?protocols=socks5&limit=500&page={page}&sort_by=lastChecked&sort_type=desc",
        C5, max_pages=20, ip_key="ip", port_key="port", root_path="data",
    ))

    # ═══════════════════════════════════════════════════════════════════════
    # WEBSITES — HTML table parsers
    # ═══════════════════════════════════════════════════════════════════════

    s.append(_html("web-free-proxy-list", ["https://free-proxy-list.net/"], H))
    s.append(_html("web-sslproxies", ["https://www.sslproxies.org/"], S))
    s.append(_html("web-us-proxy", ["https://www.us-proxy.org/"], H))
    s.append(_html("web-socks-proxy", ["https://www.socks-proxy.net/"], C5))
    s.append(_html("web-uk-proxy", ["https://free-proxy-list.net/uk-proxy.html"], H))
    s.append(_html("web-anonymous-proxy", ["https://free-proxy-list.net/anonymous-proxy.html"], H))

    # ═══════════════════════════════════════════════════════════════════════
    # OTHER
    # ═══════════════════════════════════════════════════════════════════════

    s.append(_raw("other-spysme", ["https://spys.me/proxy.txt"], U))

    return s


SOURCE_REGISTRY = {src.name: src for src in build_sources()}


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------

class ProxyScraper:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.proxies: set[Proxy] = set()
        self.results: list[SourceResult] = []

    def scrape(
        self,
        sources: Iterable[BaseSource] | None = None,
        max_workers: int = 20,
    ) -> set[Proxy]:
        targets = list(sources) if sources else list(SOURCE_REGISTRY.values())
        logger.info("Deep-search scraping from %d source(s)...", len(targets))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_source = {executor.submit(src.scrape): src for src in targets}
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    result = future.result()
                except Exception as exc:
                    logger.error("[%s] crashed: %s", source.name, exc)
                    continue

                self.results.append(result)
                new_proxies = [p for p in result.proxies if p not in self.proxies]
                self.proxies.update(result.proxies)

                status = "OK" if not result.errors else f"{len(result.errors)} err"
                logger.info(
                    "[%s] %s | +%d new | total %d | %.2fs",
                    source.name,
                    status,
                    len(new_proxies),
                    len(self.proxies),
                    result.elapsed,
                )
                if result.errors:
                    for err in result.errors[:2]:
                        logger.debug("  ! %s", err)

        logger.info("Scraping finished. Total unique proxies: %d", len(self.proxies))
        return self.proxies

    def save(
        self,
        path: str | Path = "proxies.txt",
        by_type: bool = False,
    ) -> None:
        path = Path(path)
        if by_type:
            grouped: dict[ProxyType, list[Proxy]] = {}
            for p in self.proxies:
                grouped.setdefault(p.proxy_type, []).append(p)
            for ptype, proxies in grouped.items():
                out = path.with_suffix(f".{ptype.value}.txt")
                out.write_text("\n".join(str(p) for p in proxies) + "\n", encoding="utf-8")
                logger.info("Saved %s proxies to %s", ptype.value.upper(), out)
        else:
            path.write_text("\n".join(str(p) for p in self.proxies) + "\n", encoding="utf-8")
            logger.info("Saved all proxies to %s", path)

    def print_summary(self) -> None:
        grouped: dict[ProxyType, int] = {}
        for p in self.proxies:
            grouped[p.proxy_type] = grouped.get(p.proxy_type, 0) + 1
        print("\n" + "=" * 52)
        print(" PROXY SCRAPE SUMMARY")
        print("=" * 52)
        for ptype in ProxyType:
            count = grouped.get(ptype, 0)
            if count:
                print(f"  {ptype.value.upper():10s}: {count:>8,}")
        print("-" * 52)
        print(f"  {'TOTAL':10s}: {len(self.proxies):>8,}")
        print("=" * 52 + "\n")


# ---------------------------------------------------------------------------
# Proxy checker
# ---------------------------------------------------------------------------

class ProxyChecker:
    def __init__(
        self,
        timeout: int = CHECK_TIMEOUT,
        max_workers: int = MAX_WORKERS,
        check_url: str = CHECK_URL,
    ) -> None:
        self.timeout = timeout
        self.max_workers = max_workers
        self.check_url = check_url
        self.live: set[Proxy] = set()
        self.dead: set[Proxy] = set()

    def _check_single(self, proxy: Proxy) -> bool:
        try:
            with create_session() as session:
                session.get(
                    self.check_url,
                    proxies=proxy.to_dict(),
                    timeout=self.timeout,
                )
            return True
        except Exception:
            return False

    def check(self, proxies: Iterable[Proxy]) -> tuple[set[Proxy], set[Proxy]]:
        proxy_list = list(proxies)
        total = len(proxy_list)
        logger.info("Checking %d proxies with %d workers...", total, self.max_workers)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_proxy = {
                executor.submit(self._check_single, p): p for p in proxy_list
            }
            for i, future in enumerate(as_completed(future_to_proxy), 1):
                proxy = future_to_proxy[future]
                try:
                    alive = future.result()
                except Exception:
                    alive = False

                if alive:
                    self.live.add(proxy)
                else:
                    self.dead.add(proxy)

                if i % 100 == 0 or i == total:
                    logger.info(
                        "Progress: %d/%d | Live: %d | Dead: %d",
                        i, total, len(self.live), len(self.dead),
                    )

        logger.info("Check complete. Live: %d | Dead: %d", len(self.live), len(self.dead))
        return self.live, self.dead

    def save(
        self,
        live_path: str | Path = "live_proxies.txt",
        dead_path: str | Path = "dead_proxies.txt",
    ) -> None:
        Path(live_path).write_text(
            "\n".join(str(p) for p in self.live) + "\n", encoding="utf-8"
        )
        Path(dead_path).write_text(
            "\n".join(str(p) for p in self.dead) + "\n", encoding="utf-8"
        )
        logger.info("Results saved to %s and %s", live_path, dead_path)

    def print_summary(self) -> None:
        print("\n" + "=" * 52)
        print(" PROXY CHECK SUMMARY")
        print("=" * 52)
        print(f"  Live: {len(self.live):>8,}")
        print(f"  Dead: {len(self.dead):>8,}")
        print("=" * 52 + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proxy-scraper",
        description="Scrape and check public proxy lists (ultimate edition).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  %(prog)s scrape --all
  %(prog)s scrape --source github-gfpcom deep-geonode-http
  %(prog)s check --file proxies.txt --workers 200
  %(prog)s check --file proxies.txt --output live.txt dead.txt
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scrape_parser = sub.add_parser("scrape", help="Scrape proxies from public sources")
    scrape_parser.add_argument(
        "--all", action="store_true", help="Scrape from every built-in source"
    )
    scrape_parser.add_argument(
        "--source",
        nargs="+",
        choices=list(SOURCE_REGISTRY.keys()),
        metavar="NAME",
        help="One or more source names to scrape",
    )
    scrape_parser.add_argument(
        "-o", "--output", default="proxies.txt", help="Output file (default: proxies.txt)"
    )
    scrape_parser.add_argument(
        "--by-type", action="store_true", help="Split output into separate files per proxy type"
    )
    scrape_parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout in seconds"
    )
    scrape_parser.add_argument(
        "--workers", type=int, default=20, help="Concurrent source workers"
    )
    scrape_parser.add_argument(
        "--list-sources", action="store_true", help="List all available sources and exit"
    )

    check_parser = sub.add_parser("check", help="Check proxy list for liveness")
    check_parser.add_argument("--file", required=True, help="Path to proxy list file")
    check_parser.add_argument(
        "--workers", type=int, default=MAX_WORKERS, help="Concurrent checker workers"
    )
    check_parser.add_argument(
        "--timeout", type=int, default=CHECK_TIMEOUT, help="Check timeout in seconds"
    )
    check_parser.add_argument(
        "--output",
        nargs=2,
        metavar=("LIVE", "DEAD"),
        default=["live_proxies.txt", "dead_proxies.txt"],
        help="Output files for live and dead proxies",
    )

    return parser


def _list_sources() -> None:
    print("\nAvailable sources:\n")
    current_category = ""
    for name in sorted(SOURCE_REGISTRY.keys()):
        category = name.split("-")[0]
        if category != current_category:
            current_category = category
            print(f"\n  [{category.upper()}]")
        print(f"    {name}")
    print(f"\n  Total: {len(SOURCE_REGISTRY)} sources\n")


def _cmd_scrape(args: argparse.Namespace) -> None:
    if args.list_sources:
        _list_sources()
        return

    scraper = ProxyScraper(timeout=args.timeout)

    if args.all:
        sources = list(SOURCE_REGISTRY.values())
    elif args.source:
        sources = [SOURCE_REGISTRY[name] for name in args.source]
    else:
        logger.error("No sources specified. Use --all or --source <name> ...")
        sys.exit(1)

    scraper.scrape(sources=sources, max_workers=args.workers)
    scraper.save(path=args.output, by_type=args.by_type)
    scraper.print_summary()


def _cmd_check(args: argparse.Namespace) -> None:
    file_path = Path(args.file)
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        sys.exit(1)

    raw = file_path.read_text(encoding="utf-8")
    proxies = {p for line in raw.splitlines() if (p := parse_proxy(line))}
    if not proxies:
        logger.error("No valid proxies found in %s", file_path)
        sys.exit(1)

    checker = ProxyChecker(timeout=args.timeout, max_workers=args.workers)
    checker.check(proxies)
    checker.save(live_path=args.output[0], dead_path=args.output[1])
    checker.print_summary()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "scrape":
        _cmd_scrape(args)
    elif args.command == "check":
        _cmd_check(args)
    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
