"""
Unit tests for utils/scraping.py.

All HTTP calls are intercepted by httpx.MockTransport so no real network
requests are made. Tests operate on the utility function directly — no
database, no FastAPI client.
"""

import pytest
import httpx

from app.utils.scraping import scrape_url


# ---------------------------------------------------------------------------
# Helpers — build mock httpx transports
# ---------------------------------------------------------------------------

def _mock_transport(
    html: str = "",
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
) -> httpx.MockTransport:
    """Return a transport that always responds with the given parameters."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            headers={"content-type": content_type},
            text=html,
        )
    return httpx.MockTransport(handler)


def _html(body: str, title: str = "Test Page") -> str:
    return f"""<!DOCTYPE html>
<html>
<head><title>{title}</title></head>
<body>{body}</body>
</html>"""


# Patch httpx.get to use our mock transport during tests
@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch):
    """Replace httpx.get with a version that accepts an extra transport kwarg."""
    original_get = httpx.get

    def mock_get(url, **kwargs):
        transport = kwargs.pop("_transport", None)
        if transport:
            with httpx.Client(transport=transport) as client:
                return client.get(url, **kwargs)
        return original_get(url, **kwargs)

    monkeypatch.setattr(httpx, "get", mock_get)


# ---------------------------------------------------------------------------
# Use a simpler approach: monkeypatch scrape_url's internal httpx.get call
# ---------------------------------------------------------------------------

def _make_response(html: str, status_code: int = 200, content_type: str = "text/html; charset=utf-8") -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": content_type},
        text=html,
    )


@pytest.fixture()
def mock_get(monkeypatch):
    """Fixture that lets tests control what httpx.get returns."""
    responses: list[httpx.Response] = []
    errors: list[Exception] = []

    def fake_get(url, **kwargs):
        if errors:
            raise errors.pop(0)
        if responses:
            return responses.pop(0)
        return _make_response(_html("Default content"))

    monkeypatch.setattr(httpx, "get", fake_get)
    return responses, errors


# ---------------------------------------------------------------------------
# Successful scraping
# ---------------------------------------------------------------------------

def test_returns_title_and_content(mock_get):
    responses, _ = mock_get
    responses.append(_make_response(_html("<p>Main article text here.</p>", title="My Article")))
    title, content = scrape_url("http://example.com")
    assert title == "My Article"
    assert "Main article text here" in content


def test_returns_tuple_of_two_strings(mock_get):
    responses, _ = mock_get
    responses.append(_make_response(_html("<p>Content.</p>")))
    result = scrape_url("http://example.com")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(v, str) for v in result)


def test_strips_script_tags(mock_get):
    responses, _ = mock_get
    html = _html("<p>Visible text.</p><script>alert('xss')</script>")
    responses.append(_make_response(html))
    _, content = scrape_url("http://example.com")
    assert "alert" not in content
    assert "Visible text" in content


def test_strips_style_tags(mock_get):
    responses, _ = mock_get
    html = _html("<p>Real content.</p><style>body { color: red; }</style>")
    responses.append(_make_response(html))
    _, content = scrape_url("http://example.com")
    assert "color: red" not in content
    assert "Real content" in content


def test_strips_nav_tags(mock_get):
    responses, _ = mock_get
    html = _html("<nav>Home About Contact</nav><p>Article body.</p>")
    responses.append(_make_response(html))
    _, content = scrape_url("http://example.com")
    assert "Home About Contact" not in content
    assert "Article body" in content


def test_strips_header_and_footer(mock_get):
    responses, _ = mock_get
    html = _html("<header>Site Header</header><p>Content.</p><footer>Site Footer</footer>")
    responses.append(_make_response(html))
    _, content = scrape_url("http://example.com")
    assert "Site Header" not in content
    assert "Site Footer" not in content
    assert "Content" in content


def test_collapses_excessive_whitespace(mock_get):
    responses, _ = mock_get
    html = _html("<p>First.</p><p>Second.</p><p>Third.</p>")
    responses.append(_make_response(html))
    _, content = scrape_url("http://example.com")
    assert "\n\n\n" not in content


def test_content_is_stripped(mock_get):
    responses, _ = mock_get
    responses.append(_make_response(_html("<p>Content.</p>")))
    _, content = scrape_url("http://example.com")
    assert content == content.strip()


# ---------------------------------------------------------------------------
# Title edge cases
# ---------------------------------------------------------------------------

def test_missing_title_falls_back_to_url(mock_get):
    responses, _ = mock_get
    html = "<!DOCTYPE html><html><head></head><body><p>No title here.</p></body></html>"
    responses.append(_make_response(html))
    title, _ = scrape_url("http://example.com/article")
    assert title == "http://example.com/article"


def test_empty_title_falls_back_to_url(mock_get):
    responses, _ = mock_get
    html = "<!DOCTYPE html><html><head><title></title></head><body><p>Content.</p></body></html>"
    responses.append(_make_response(html))
    title, _ = scrape_url("http://example.com/page")
    assert title == "http://example.com/page"


def test_title_is_stripped(mock_get):
    responses, _ = mock_get
    html = _html("<p>Content.</p>", title="  Padded Title  ")
    responses.append(_make_response(html))
    title, _ = scrape_url("http://example.com")
    assert title == "Padded Title"


# ---------------------------------------------------------------------------
# HTTP error cases
# ---------------------------------------------------------------------------

def test_404_raises_value_error(mock_get):
    responses, _ = mock_get
    responses.append(_make_response("Not found", status_code=404))
    with pytest.raises(ValueError, match="HTTP 404"):
        scrape_url("http://example.com/missing")


def test_500_raises_value_error(mock_get):
    responses, _ = mock_get
    responses.append(_make_response("Server error", status_code=500))
    with pytest.raises(ValueError, match="HTTP 500"):
        scrape_url("http://example.com")


def test_non_html_content_type_raises_value_error(mock_get):
    responses, _ = mock_get
    responses.append(_make_response("%PDF-1.4 fake pdf content", content_type="application/pdf"))
    with pytest.raises(ValueError, match="Expected HTML"):
        scrape_url("http://example.com/doc.pdf")


def test_timeout_raises_value_error(mock_get):
    _, errors = mock_get
    errors.append(httpx.TimeoutException("timed out"))
    with pytest.raises(ValueError, match="timed out"):
        scrape_url("http://example.com")


def test_connection_error_raises_value_error(mock_get):
    _, errors = mock_get
    errors.append(httpx.ConnectError("connection refused"))
    with pytest.raises(ValueError, match="Could not connect"):
        scrape_url("http://example.com")
