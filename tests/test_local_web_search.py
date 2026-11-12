import base64
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.core.local_web_search import (
    _assess_with_local_model,
    _decode_bing_url,
    _search_results,
    _search_wikipedia_results,
    get_local_model_status,
    search_and_assess_claim,
)
from app.core.fact_check_search import fact_check_engine
from app.core.pipeline import pipeline


def _bing_page(url="https://example.test/brain-fact"):
    return f"""
    <ol id="b_results">
      <li class="b_algo">
        <h2><a href="{url}">Brain myth: only 10 percent?</a></h2>
        <div class="b_caption"><div><p>
          The claim that people use only 10 percent of their brains is a myth.
        </p></div></div>
      </li>
    </ol>
    """


def test_search_results_parses_bing_titles_snippets_and_links():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        text=_bing_page(),
    )
    with patch("app.core.local_web_search.requests.get", return_value=response):
        results = _search_results("Humans use only 10% of their brains")

    assert results == [{
        "title": "Brain myth: only 10 percent?",
        "url": "https://example.test/brain-fact",
        "publisher": "example.test",
        "source_type": "Bing web search",
        "snippet": "The claim that people use only 10 percent of their brains is a myth.",
    }]


def test_search_results_decode_bing_redirect_links():
    target = "https://example.test/review"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    assert _decode_bing_url(f"https://www.bing.com/ck/a?u=a1{encoded}") == target


def test_local_assessment_uses_ollama_without_api_key():
    search_response = SimpleNamespace(
        raise_for_status=lambda: None,
        text=_bing_page(),
    )
    model_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "response": (
                '{"verdict":"Likely False",'
                '"explanation":"The search result identifies the claim as a myth."}'
            )
        },
    )
    with patch(
        "app.core.local_web_search.requests.get",
        return_value=search_response,
    ), patch(
        "app.core.local_web_search.requests.post",
        return_value=model_response,
    ) as post:
        result = search_and_assess_claim("Humans use only 10% of their brains")

    assert result["status"] == "success"
    assert result["verdict"] == "Likely False"
    assert result["sources"][0]["url"] == "https://example.test/brain-fact"
    assert "Bing" in result["message"]
    assert post.call_args.kwargs["json"]["think"] is False
    assert "do not treat a title mention as evidence" in post.call_args.kwargs["json"]["prompt"]
    assert "one-sentence explanation must agree" in post.call_args.kwargs["json"]["prompt"]
    assert "example.test/brain-fact" not in post.call_args.kwargs["json"]["prompt"]
    assert "api_key" not in post.call_args.kwargs
    assert "headers" not in post.call_args.kwargs
    assert post.call_args.args[0] == "http://localhost:11434/api/generate"
    assert post.call_args.kwargs["json"]["model"] == "qwen3:4b"


def test_local_assessment_ignores_snippets_that_only_echo_the_claim():
    model_response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "response": (
                '{"verdict":"Likely True",'
                '"explanation":"The Sun rises due east at the equinox."}'
            )
        },
    )
    sources = [
        {
            "title": "The Sun Rises in the East",
            "url": "https://example.test/album",
            "snippet": "The Sun Rises in the East is the debut album of a rapper.",
        },
        {
            "title": "Sun path",
            "url": "https://example.test/sun-path",
            "snippet": "Except for the poles, the Sun rises due east at the equinox.",
        },
    ]

    with patch(
        "app.core.local_web_search.requests.post",
        return_value=model_response,
    ) as post:
        result = _assess_with_local_model("The Sun rises in the east", sources)

    assert result["verdict"] == "Likely True"
    prompt = post.call_args.kwargs["json"]["prompt"]
    assert "Sun path" in prompt
    assert "debut album" not in prompt
    assert post.call_args.kwargs["json"]["options"]["num_predict"] == 256


def test_irrelevant_search_results_do_not_get_sent_to_the_model():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        text="""
        <li class="b_algo"><h2><a href="https://example.test/">Gardening tips</a></h2>
        <div class="b_caption"><p>How to grow tomatoes at home.</p></div></li>
        """,
    )
    with patch(
        "app.core.local_web_search.requests.get",
        return_value=response,
    ), patch(
        "app.core.local_web_search._search_wikipedia_results",
        return_value=[],
    ), patch("app.core.local_web_search.requests.post") as post:
        result = search_and_assess_claim("Humans use only 10% of their brains")

    assert result["status"] == "no_relevant_sources"
    assert result["verdict"] == "Unverified"
    post.assert_not_called()


def test_wikipedia_search_fallback_returns_relevant_source():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "query": {
                "search": [{
                    "title": "Ten-percent-of-the-brain myth",
                    "snippet": (
                        "The ten-percent-of-the-brain myth states that humans "
                        "generally use only one-tenth of their brains."
                    ),
                }]
            }
        },
    )
    with patch(
        "app.core.local_web_search.requests.get",
        return_value=response,
    ):
        fallback_results = _search_wikipedia_results(
            "Humans use only 10% of their brains"
        )

    assert fallback_results[0]["title"] == "Ten-percent-of-the-brain myth"
    assert fallback_results[0]["url"] == (
        "https://en.wikipedia.org/wiki/Ten-percent-of-the-brain_myth"
    )
    assert "<span>" not in fallback_results[0]["snippet"]
    assert "Wikipedia" == fallback_results[0]["publisher"]


def test_missing_local_ollama_returns_actionable_message():
    with patch(
        "app.core.local_web_search._search_results",
        return_value=[{
            "title": "Brain fact",
            "url": "https://example.test/brain",
            "publisher": "example.test",
            "source_type": "Bing web search",
            "snippet": "Brains are active.",
        }],
    ), patch(
        "app.core.local_web_search._search_wikipedia_results",
        return_value=[],
    ), patch(
        "app.core.local_web_search._assess_with_local_model",
        side_effect=requests.ConnectionError(),
    ):
        result = search_and_assess_claim("A claim about brains")

    assert result["status"] == "model_unavailable"
    assert "pull the qwen3:4b model" in result["message"]
    assert result["sources"][0]["url"] == "https://example.test/brain"


def test_local_model_status_reports_installed_model():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"models": [{"name": "qwen3:4b"}]},
    )
    with patch("app.core.local_web_search.requests.get", return_value=response):
        status = get_local_model_status()

    assert status["available"] is True
    assert status["model"] == "qwen3:4b"


def test_pipeline_ignores_external_fact_check_keys_in_local_mode():
    with patch.dict("os.environ", {"GOOGLE_FACT_CHECK_API_KEY": "unused-key"}), patch(
        "app.core.pipeline.fact_check_engine.find_matches",
        wraps=fact_check_engine.find_matches,
    ) as find_matches, patch(
        "app.core.pipeline.search_and_assess_claim",
        return_value={
            "status": "model_unavailable",
            "message": "Ollama is not running.",
            "verdict": "Unverified",
            "explanation": "",
            "sources": [],
        },
    ):
        pipeline.verify(text="A new claim that is not in the local database.")

    assert find_matches.call_args.kwargs["api_key"] == ""
