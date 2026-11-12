import io
import socket
from unittest.mock import patch

import pytest
import requests

from app.core.article_extraction import ArticleExtractionError, fetch_article


def test_fetch_article_extracts_readable_main_content():
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.encoding = "utf-8"
    response._content = (
        b"<html><head><title>River report</title>"
        b"<meta name='description' content='The annual report is now available.'>"
        b"</head><body><nav>Navigation should be ignored.</nav><main><article>"
        b"<p>The city released its annual river-water quality report on Tuesday "
        b"after a six-month environmental review.</p>"
        b"</article></main></body></html>"
    )
    response.raw = io.BytesIO(response._content)
    with patch(
        "app.core.article_extraction.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    ), patch("app.core.article_extraction.requests.get", return_value=response):
        article = fetch_article("https://news.example/article")

    assert article["title"] == "River report"
    assert article["description"] == "The annual report is now available."
    assert "annual river-water quality report" in article["text"]
    assert "Navigation should be ignored" not in article["text"]


def test_fetch_article_rejects_private_network_addresses():
    with patch("app.core.article_extraction.requests.get") as get:
        with pytest.raises(ArticleExtractionError, match="Private and local"):
            fetch_article("http://127.0.0.1/")

    get.assert_not_called()


def test_fetch_article_explains_publisher_access_denial():
    response = requests.Response()
    response.status_code = 403
    response.headers["Content-Type"] = "text/html"
    response.raw = io.BytesIO()
    with patch(
        "app.core.article_extraction.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    ), patch("app.core.article_extraction.requests.get", return_value=response):
        with pytest.raises(ArticleExtractionError, match="blocks automated article access"):
            fetch_article("https://news.example/article")
