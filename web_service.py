"""
web_service.py - Lightweight Web Search & Web Page Fetching module.
Provides:
- SearchProvider abstraction & DuckDuckGo Lite provider
- web_search(query) with SQLite caching & audit logging
- web_fetch(url) with security checks (anti-SSRF), script stripping, and caching
- Pure Python standard library (urllib, html.parser, socket, ipaddress), zero heavy dependencies
"""
import urllib.request
import urllib.parse
import ipaddress
import socket
import json
import re
from html.parser import HTMLParser

from config import (
    WEB_SEARCH_RESULTS_LIMIT,
    WEB_SEARCH_TIMEOUT,
    WEB_FETCH_TIMEOUT,
    WEB_FETCH_MAX_CHARS,
    WEB_SEARCH_CACHE_TTL_MINUTES,
    WEB_FETCH_CACHE_TTL_MINUTES
)
import database

# ============================================================
# SEARCH PROVIDER ABSTRACTION (STEP 3 & 4)
# ============================================================

class SearchProvider:
    """Base interface for search providers."""
    def search(self, query: str, max_results: int = WEB_SEARCH_RESULTS_LIMIT) -> list:
        raise NotImplementedError


class DuckDuckGoHTMLParser(HTMLParser):
    """Lightweight streaming parser for DuckDuckGo search results."""
    def __init__(self):
        super().__init__()
        self.results = []
        self.current_result = None
        self.in_result_link = False
        self.in_snippet = False
        self.snippet_chunks = []
        self.title_chunks = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        classes = attrs_dict.get('class', '')

        # Result title & link
        if tag == 'a' and ('result__a' in classes or 'result-link' in classes):
            href = attrs_dict.get('href', '')
            if 'uddg=' in href:
                m = re.search(r'uddg=([^&]+)', href)
                if m:
                    href = urllib.parse.unquote(m.group(1))

            self.current_result = {'url': href, 'title': '', 'snippet': '', 'domain': ''}
            try:
                self.current_result['domain'] = urllib.parse.urlparse(href).netloc
            except Exception:
                pass
            self.in_result_link = True
            self.title_chunks = []

        # Result snippet
        if tag in ['a', 'td', 'div'] and ('result__snippet' in classes or 'result-snippet' in classes):
            self.in_snippet = True
            self.snippet_chunks = []

    def handle_endtag(self, tag):
        if tag == 'a' and self.in_result_link:
            self.in_result_link = False
            if self.current_result:
                self.current_result['title'] = ''.join(self.title_chunks).strip()

        if self.in_snippet and tag in ['a', 'td', 'div']:
            self.in_snippet = False
            if self.current_result:
                self.current_result['snippet'] = ''.join(self.snippet_chunks).strip()
                if self.current_result['url'] and self.current_result['title']:
                    self.results.append(self.current_result)
                self.current_result = None

    def handle_data(self, data):
        if self.in_result_link:
            self.title_chunks.append(data)
        elif self.in_snippet:
            self.snippet_chunks.append(data)


class DuckDuckGoLiteProvider(SearchProvider):
    """Zero-dependency DuckDuckGo HTML search provider."""
    def search(self, query: str, max_results: int = WEB_SEARCH_RESULTS_LIMIT) -> list:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'vi,en-US;q=0.9,en;q=0.8',
        }
        data = urllib.parse.urlencode({'q': query}).encode('utf-8')
        req = urllib.request.Request(
            'https://html.duckduckgo.com/html/',
            data=data,
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=WEB_SEARCH_TIMEOUT) as resp:
            html = resp.read().decode('utf-8', errors='ignore')

        parser = DuckDuckGoHTMLParser()
        parser.feed(html)
        return parser.results[:max_results]


# Active search provider instance
_active_provider = DuckDuckGoLiteProvider()


# ============================================================
# SECURITY / SAFETY LIMITS (STEP 6)
# ============================================================

def is_safe_url(url: str):
    """
    Validate that url is safe to fetch:
    - Only http/https
    - Blocks localhost, 127.0.0.1, 0.0.0.0, ::1
    - Resolves IP and blocks loopback, private, link-local CIDRs (anti-SSRF)
    - Blocks file:// and invalid URLs
    """
    if not url:
        return False, "URL rỗng."

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as e:
        return False, f"URL không hợp lệ: {e}"

    if parsed.scheme.lower() not in ('http', 'https'):
        return False, f"Chỉ cho phép giao thức http hoặc https, từ chối '{parsed.scheme}'."

    hostname = parsed.hostname
    if not hostname:
        return False, "URL không hợp lệ (thiếu hostname)."

    lowered = hostname.lower()
    if lowered in ('localhost', '127.0.0.1', '0.0.0.0', '::1'):
        return False, f"Bị chặn: Truy cập địa chỉ máy cục bộ '{hostname}' bị từ chối."

    try:
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
            return False, f"Bị chặn: Địa chỉ IP '{ip_str}' thuộc mạng nội bộ/riêng tư."
    except Exception as e:
        return False, f"Không thể giải giải tên miền '{hostname}': {e}"

    return True, "OK"


# ============================================================
# WEB PAGE TEXT EXTRACTOR (STEP 5)
# ============================================================

class WebPageTextExtractor(HTMLParser):
    """Extract clean, readable text from HTML, stripping scripts/styles/tags."""
    def __init__(self):
        super().__init__()
        self.text_chunks = []
        # Only container tags that have </tag> end tags should increment depth
        self.container_ignore_tags = {'script', 'style', 'noscript', 'svg', 'iframe'}
        self.current_ignore_depth = 0
        self.title = ""
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.container_ignore_tags:
            self.current_ignore_depth += 1
        elif tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in self.container_ignore_tags:
            self.current_ignore_depth = max(0, self.current_ignore_depth - 1)
        elif tag == 'title':
            self.in_title = False
        elif tag in ['p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'br', 'tr', 'article', 'section']:
            if self.current_ignore_depth == 0:
                self.text_chunks.append("\n")

    def handle_data(self, data):
        if self.in_title:
            self.title += data.strip()
        elif self.current_ignore_depth == 0:
            cleaned = data.strip()
            if cleaned:
                self.text_chunks.append(cleaned + " ")

    def get_text(self, max_chars=WEB_FETCH_MAX_CHARS):
        raw = "".join(self.text_chunks)
        # Normalize multiple spaces and repeated newlines
        normalized = re.sub(r'[ \t]+', ' ', raw)
        normalized = re.sub(r'\n\s*\n+', '\n\n', normalized).strip()
        if len(normalized) > max_chars:
            return normalized[:max_chars] + f"\n\n[...Nội dung trang đã được rút gọn do vượt giới hạn {max_chars} ký tự...]"
        return normalized


# ============================================================
# PUBLIC EXPORTED FUNCTIONS (STEP 2, 8, 16)
# ============================================================

def web_search(query: str, project_id=None, conversation_id=None) -> list:
    """
    Search the web for query using active search provider.
    Checks SQLite web_cache first. Caches results for WEB_SEARCH_CACHE_TTL_MINUTES.
    Logs metadata to web_retrieval_log.
    """
    if not query or not query.strip():
        return [{"error": "Truy vấn tìm kiếm không được để trống."}]

    cleaned_query = query.strip()
    cache_key = f"search:{cleaned_query.lower()}"

    # 1. Check SQLite Cache
    cached = database.get_web_cache(cache_key)
    if cached is not None:
        print(f"[WebCache] Hit for search query: '{cleaned_query}'")
        return cached

    # 2. Execute live search
    print(f"[WebSearch] Executing live search: '{cleaned_query}'")
    try:
        results = _active_provider.search(cleaned_query, max_results=WEB_SEARCH_RESULTS_LIMIT)
        if not results:
            results = [{"message": f"Không tìm thấy kết quả nào cho truy vấn: '{cleaned_query}'."}]

        # Save to Cache
        database.set_web_cache(
            cache_key=cache_key,
            cache_type="search",
            content=results,
            ttl_minutes=WEB_SEARCH_CACHE_TTL_MINUTES,
            query=cleaned_query
        )

        # Audit Log
        if results and isinstance(results, list) and "url" in results[0]:
            database.log_web_retrieval(
                project_id=project_id,
                conversation_id=conversation_id,
                query=cleaned_query,
                url=results[0].get("url"),
                source_title=results[0].get("title")
            )

        return results

    except Exception as e:
        print(f"[WebSearch Error]: {e}")
        return [{"error": f"Tìm kiếm web không khả dụng hoặc bị timeout: {str(e)}"}]


def web_fetch(url: str, project_id=None, conversation_id=None) -> dict:
    """
    Fetch and extract clean text from a web page URL.
    Validates URL safety (anti-SSRF).
    Checks SQLite web_cache first. Caches content for WEB_FETCH_CACHE_TTL_MINUTES.
    Logs metadata to web_retrieval_log.
    """
    if not url or not url.strip():
        return {"error": "URL không được để trống."}

    cleaned_url = url.strip()

    # 1. Security Check (Anti-SSRF)
    safe, reason = is_safe_url(cleaned_url)
    if not safe:
        return {"error": f"Truy cập URL bị từ chối: {reason}"}

    cache_key = f"fetch:{cleaned_url}"

    # 2. Check SQLite Cache
    cached = database.get_web_cache(cache_key)
    if cached is not None:
        print(f"[WebCache] Hit for fetch URL: '{cleaned_url}'")
        if isinstance(cached, dict):
            cached["from_cache"] = True
            return cached
        return {"url": cleaned_url, "content": cached, "from_cache": True}

    # 3. Live Fetch
    print(f"[WebFetch] Fetching page: '{cleaned_url}'")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }
    req = urllib.request.Request(cleaned_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=WEB_FETCH_TIMEOUT) as resp:
            # Read max 500 KB to avoid memory explosion on huge downloads
            raw_bytes = resp.read(500000)
            content_type = resp.headers.get('Content-Type', '')
            charset = 'utf-8'
            if 'charset=' in content_type:
                charset = content_type.split('charset=')[-1].split(';')[0].strip()

            html = raw_bytes.decode(charset, errors='ignore')

        extractor = WebPageTextExtractor()
        extractor.feed(html)
        text = extractor.get_text(max_chars=WEB_FETCH_MAX_CHARS)
        title = extractor.title or cleaned_url

        result_data = {
            "url": cleaned_url,
            "title": title,
            "content": text,
            "from_cache": False
        }

        # Save to Cache
        database.set_web_cache(
            cache_key=cache_key,
            cache_type="fetch",
            content=result_data,
            ttl_minutes=WEB_FETCH_CACHE_TTL_MINUTES,
            url=cleaned_url
        )

        # Audit Log
        database.log_web_retrieval(
            project_id=project_id,
            conversation_id=conversation_id,
            url=cleaned_url,
            source_title=title
        )

        return result_data

    except Exception as e:
        print(f"[WebFetch Error]: {e}")
        return {"error": f"Không thể tải trang web: {str(e)}", "url": cleaned_url}


def get_search_tools_definition():
    import ollama_client
    return ollama_client.TOOLS_SPEC
