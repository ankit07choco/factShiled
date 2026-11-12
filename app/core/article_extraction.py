import ipaddress
import socket
from html.parser import HTMLParser
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse

import requests

MAX_ARTICLE_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
BLOCKED_TAGS = {
    "aside", "button", "footer", "form", "iframe", "nav", "noscript",
    "object", "script", "style", "svg",
}


class ArticleExtractionError(ValueError):
    pass


class _ArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._title_depth = 0
        self._skip_depth = 0
        self._content_depth = 0
        self._all_text: list[str] = []
        self._article_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            content = (attributes.get("content") or "").strip()
            if name in {"description", "og:description"} and content and not self.description:
                self.description = content
            elif name == "og:title" and content and not self.title:
                self.title = content
        if tag in BLOCKED_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._title_depth += 1
        if tag in {"article", "main"}:
            self._content_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in BLOCKED_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag in {"article", "main"} and self._content_depth:
            self._content_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._title_depth and not self.title:
            self.title = text
        if self._skip_depth or self._title_depth:
            return
        self._all_text.append(text)
        if self._content_depth:
            self._article_text.append(text)

    def article_text(self) -> str:
        preferred = " ".join(self._article_text).strip()
        fallback = " ".join(self._all_text).strip()
        return preferred if len(preferred) >= 80 else fallback


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ArticleExtractionError("Use a public HTTP or HTTPS article link.")
    if parsed.username or parsed.password:
        raise ArticleExtractionError("Article links must not contain login credentials.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ArticleExtractionError("The article link has an invalid port.") from exc
    if port not in {None, 80, 443}:
        raise ArticleExtractionError("Only standard HTTP and HTTPS article links are supported.")

    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ArticleExtractionError("Private and local network addresses cannot be fetched.")
    try:
        addresses = {ipaddress.ip_address(hostname)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(info[4][0])
                for info in socket.getaddrinfo(
                    hostname,
                    port or (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except (OSError, ValueError) as exc:
            raise ArticleExtractionError("The article host could not be resolved.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ArticleExtractionError("Private and local network addresses cannot be fetched.")


def fetch_article(url: str) -> Dict[str, str]:
    """Fetches a small public HTML article with bounded redirects and response size."""
    current_url = url
    response = None
    for redirect_count in range(MAX_REDIRECTS + 1):
        _validate_public_url(current_url)
        try:
            response = requests.get(
                current_url,
                headers={"User-Agent": "FactShield/1.0 (article verification)"},
                timeout=(4, 10),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException as exc:
            raise ArticleExtractionError(
                "Could not fetch the article. Check the URL and try again."
            ) from exc

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location or redirect_count == MAX_REDIRECTS:
                raise ArticleExtractionError("The article link redirected too many times.")
            current_url = urljoin(current_url, location)
            continue
        if response.status_code >= 400:
            response.close()
            if response.status_code in {401, 403}:
                raise ArticleExtractionError(
                    "This publisher blocks automated article access. Paste the article text in Text mode, or try a link that allows public access."
                )
            raise ArticleExtractionError(
                f"The article server returned HTTP {response.status_code}."
            )
        break
    else:
        raise ArticleExtractionError("The article link redirected too many times.")

    try:
        content_type = response.headers.get("Content-Type", "").casefold()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ArticleExtractionError("That link does not return an HTML article.")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_ARTICLE_BYTES:
            raise ArticleExtractionError("The article page is larger than the 2 MB limit.")

        content = bytearray()
        for chunk in response.iter_content(chunk_size=16_384):
            content.extend(chunk)
            if len(content) > MAX_ARTICLE_BYTES:
                raise ArticleExtractionError("The article page is larger than the 2 MB limit.")
        page = bytes(content).decode(response.encoding or "utf-8", errors="replace")
    except ArticleExtractionError:
        raise
    except requests.RequestException as exc:
        raise ArticleExtractionError(
            "The article download was interrupted. Try again."
        ) from exc
    except ValueError as exc:
        raise ArticleExtractionError("The article page has an invalid content length.") from exc
    finally:
        response.close()

    parser = _ArticleParser()
    parser.feed(page)
    article_text = parser.article_text()
    text = " ".join(part for part in (parser.title, parser.description, article_text) if part)
    if len(text.strip()) < 40:
        raise ArticleExtractionError(
            "The article page did not contain enough readable text to verify."
        )
    return {
        "url": current_url,
        "title": parser.title[:300],
        "description": parser.description[:1000],
        "text": text[:15_000],
    }
