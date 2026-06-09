import re

import httpx
import structlog
from bs4 import BeautifulSoup

logger = structlog.get_logger()

# Tags that contribute no readable content
_NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "noscript"]

_TIMEOUT = 10  # seconds


def scrape_url(url: str) -> tuple[str, str]:
    """Fetch a URL and return (title, content) as plain text.

    Raises ValueError for network errors, non-200 responses, or non-HTML content.
    """
    try:
        response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    except httpx.TimeoutException as exc:
        raise ValueError(f"Request timed out after {_TIMEOUT}s: {url}") from exc
    except httpx.RequestError as exc:
        raise ValueError(f"Could not connect to {url}: {exc}") from exc

    if response.status_code != 200:
        raise ValueError(f"Received HTTP {response.status_code} from {url}")

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        raise ValueError(
            f"Expected HTML content but got '{content_type}' from {url}"
        )

    soup = BeautifulSoup(response.text, "lxml")

    title = _extract_title(soup, fallback=url)

    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    body = soup.find("body") or soup
    raw = body.get_text(separator="\n")
    content = _clean_whitespace(raw)

    logger.info("url_scraped", url=url, title=title, content_length=len(content))
    return title, content


def _extract_title(soup: BeautifulSoup, fallback: str) -> str:
    """Return the page <title> text, stripped. Falls back to the URL."""
    tag = soup.find("title")
    if tag and tag.get_text(strip=True):
        return tag.get_text(strip=True)
    return fallback


def _clean_whitespace(text: str) -> str:
    """Collapse runs of blank lines and strip leading/trailing whitespace."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
