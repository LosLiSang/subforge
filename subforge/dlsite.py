from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DlsiteMetadata:
    rj_code: str
    title: str
    circle: str | None = None
    voice_actors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cover_url: str | None = None
    release_date: str | None = None
    description: str | None = None


def normalize_rj_code(val: str) -> str:
    cleaned = val.strip().upper()
    match = re.search(r"RJ\d{6,8}", cleaned, re.IGNORECASE)
    if match:
        return match.group(0).upper()
    match_digits = re.search(r"^\d{6,8}$", cleaned)
    if match_digits:
        return f"RJ{match_digits.group(0)}"
    return cleaned


def _format_date(val: str) -> str:
    m = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", val)
    if m:
        year, month, day = m.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    m2 = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", val)
    if m2:
        year, month, day = m2.groups()
        return f"{year}-{int(month):02d}-{int(day):02d}"
    return val.strip()


def _clean_text(html_fragment: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", html_fragment)
    return html.unescape(" ".join(clean.split())).strip()


def _create_opener(proxy: str = "") -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy and proxy.strip():
        handlers.append(urllib.request.ProxyHandler({"http": proxy.strip(), "https": proxy.strip()}))
    return urllib.request.build_opener(*handlers)


def parse_dlsite_html(html: str, rj_code: str) -> DlsiteMetadata:
    title = ""
    title_match = re.search(r'id=["\']work_name["\'][^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
    if title_match:
        title = _clean_text(title_match.group(1))
    if not title:
        og_title = re.search(r'<meta property=["\']og:title["\'] content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if og_title:
            title = _clean_text(og_title.group(1).split("|")[0].split(" - ")[0])
    if not title:
        title = rj_code

    circle = None
    maker_match = re.search(r'class=["\']maker_name["\'][^>]*>(.*?)</span>', html, re.DOTALL | re.IGNORECASE)
    if maker_match:
        circle = _clean_text(maker_match.group(1))

    cover_url = None
    og_image = re.search(r'<meta property=["\']og:image["\'] content=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if og_image:
        cover_url = og_image.group(1).strip()
        if cover_url.startswith("//"):
            cover_url = "https:" + cover_url

    voice_actors: list[str] = []
    tags: list[str] = []
    release_date: str | None = None

    tr_regex = re.compile(r'<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>\s*</tr>', re.DOTALL | re.IGNORECASE)
    for th, td in tr_regex.findall(html):
        clean_th = _clean_text(th)
        if not circle and any(k in clean_th for k in ("サークル名", "ブランド名", "作者")):
            circle = _clean_text(td)
        if any(k in clean_th for k in ("声優", "CV", "ボイス")):
            cv_links = re.findall(r'<a[^>]*>(.*?)</a>', td, re.DOTALL | re.IGNORECASE)
            if cv_links:
                for link in cv_links:
                    cv_name = _clean_text(link)
                    if cv_name and cv_name not in voice_actors:
                        voice_actors.append(cv_name)
            else:
                for part in re.split(r"[,/、，\s]+", _clean_text(td)):
                    part = part.strip()
                    if part and part not in voice_actors:
                        voice_actors.append(part)
        if "ジャンル" in clean_th:
            tag_links = re.findall(r'<a[^>]*>(.*?)</a>', td, re.DOTALL | re.IGNORECASE)
            if tag_links:
                for link in tag_links:
                    tag_name = _clean_text(link)
                    if tag_name and tag_name not in tags:
                        tags.append(tag_name)
            else:
                for part in re.split(r"[,/、，\s]+", _clean_text(td)):
                    part = part.strip()
                    if part and part not in tags:
                        tags.append(part)
        if "販売日" in clean_th and not release_date:
            release_date = _format_date(_clean_text(td))

    genre_matches = re.findall(r'/genre/(\d+)[^>]*>([^<]+)</a>', html, re.IGNORECASE)
    for _, gname in genre_matches:
        gclean = gname.strip()
        if gclean and gclean not in tags:
            tags.append(gclean)

    return DlsiteMetadata(
        rj_code=rj_code,
        title=title,
        circle=circle,
        voice_actors=voice_actors,
        tags=tags,
        cover_url=cover_url,
        release_date=release_date,
    )


def resolve_dlsite_proxy(proxy: str = "") -> str:
    """Resolve the proxy for DLsite scraping.

    DLsite scraping must go through a proxy whenever configured or locally available.
    Priority:
    1. Explicit proxy passed (e.g. from settings).
    2. Environment variables: HTTPS_PROXY, HTTP_PROXY, ALL_PROXY.
    3. Default local proxy 127.0.0.1:7890 if open/listening.
    """
    if proxy and proxy.strip():
        return proxy.strip()
    import os
    for env_var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            if sock.connect_ex(("127.0.0.1", 7890)) == 0:
                return "http://127.0.0.1:7890"
    except Exception:
        pass
    return ""


def fetch_dlsite_metadata(rj_code: str, proxy: str = "", timeout: int = 15) -> DlsiteMetadata | None:
    normalized = normalize_rj_code(rj_code)
    if not re.match(r"^RJ\d{6,8}$", normalized):
        logger.warning(f"Invalid RJ code format: {rj_code}")
        return None

    urls = [
        f"https://www.dlsite.com/maniax/work/=/product_id/{normalized}.html",
        f"https://www.dlsite.com/home/work/=/product_id/{normalized}.html",
        f"https://www.dlsite.com/girls/work/=/product_id/{normalized}.html",
        f"https://www.dlsite.com/pro/work/=/product_id/{normalized}.html",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ja-JP,ja;q=0.9,zh-CN;q=0.8,zh;q=0.7,en;q=0.6",
        "Cookie": "adultchecked=1; age_check_done=1; locale=ja_JP;",
    }

    active_proxy = resolve_dlsite_proxy(proxy)
    proxies_to_try = [active_proxy] if active_proxy else [""]

    for current_proxy in proxies_to_try:
        opener = _create_opener(current_proxy)
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=timeout) as resp:
                    if resp.status == 200:
                        content = resp.read().decode("utf-8", errors="ignore")
                        meta = parse_dlsite_html(content, normalized)
                        if meta and meta.title:
                            return meta
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                logger.debug(f"HTTPError {exc.code} for {url} with proxy {current_proxy}: {exc}")
            except Exception as exc:
                logger.debug(f"Request failed for {url} with proxy {current_proxy}: {exc}")
                break

    return None


def fetch_dlsite_cover(cover_url: str, proxy: str = "", timeout: int = 15) -> bytes | None:
    if not cover_url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.dlsite.com/",
    }
    active_proxy = resolve_dlsite_proxy(proxy)
    proxies_to_try = [active_proxy] if active_proxy else [""]

    for current_proxy in proxies_to_try:
        opener = _create_opener(current_proxy)
        try:
            req = urllib.request.Request(cover_url, headers=headers)
            with opener.open(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = resp.read()
                    if len(data) > 1024:
                        return data
        except Exception as exc:
            logger.debug(f"Cover download failed with proxy {current_proxy}: {exc}")
            continue
    return None
