import base64
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.core.image_origin import (
    IMAGE_ORIGIN_MODEL,
    assess_image_origin,
    get_image_origin_model_status,
)


def test_image_origin_assessment_sends_image_to_local_vision_model():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "response": (
                '{"verdict":"Inconclusive",'
                '"explanation":"The image has no reliable visual provenance clues."}'
            )
        },
    )
    image_bytes = b"test-image-bytes"

    with patch(
        "app.core.image_origin.requests.post",
        return_value=response,
    ) as post:
        result = assess_image_origin(image_bytes)

    payload = post.call_args.kwargs["json"]
    assert result["status"] == "success"
    assert result["verdict"] == "Inconclusive"
    assert payload["model"] == IMAGE_ORIGIN_MODEL
    assert payload["images"] == [base64.b64encode(image_bytes).decode("ascii")]
    assert payload["think"] is False
    assert "not proof" in result["disclaimer"]


def test_image_origin_reports_missing_vision_model():
    error = requests.HTTPError(
        response=SimpleNamespace(status_code=404),
    )
    with patch(
        "app.core.image_origin.requests.post",
        side_effect=error,
    ):
        result = assess_image_origin(b"test-image-bytes")

    assert result["status"] == "model_missing"
    assert result["verdict"] == "Inconclusive"
    assert f"ollama pull {IMAGE_ORIGIN_MODEL}" in result["message"]


def test_image_origin_rejects_unrecognized_model_verdicts():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "response": '{"verdict":"Definitely AI","explanation":"It looks unusual."}'
        },
    )
    with patch(
        "app.core.image_origin.requests.post",
        return_value=response,
    ):
        result = assess_image_origin(b"test-image-bytes")

    assert result["status"] == "model_error"
    assert result["verdict"] == "Inconclusive"


def test_image_origin_reports_when_ollama_is_unreachable():
    with patch(
        "app.core.image_origin.requests.post",
        side_effect=requests.ConnectionError(),
    ):
        result = assess_image_origin(b"test-image-bytes")

    assert result["status"] == "model_unavailable"
    assert result["verdict"] == "Inconclusive"
    assert "start it" in result["explanation"]


def test_image_origin_model_status_requires_exact_installed_model():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"models": [{"name": "qwen3:4b"}]},
    )
    with patch(
        "app.core.image_origin.requests.get",
        return_value=response,
    ):
        status = get_image_origin_model_status()

    assert status["available"] is False
    assert status["model"] == IMAGE_ORIGIN_MODEL
    assert f"ollama pull {IMAGE_ORIGIN_MODEL}" in status["message"]


def test_image_origin_model_status_reports_installed_model():
    response = SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {"models": [{"name": IMAGE_ORIGIN_MODEL}]},
    )
    with patch(
        "app.core.image_origin.requests.get",
        return_value=response,
    ):
        status = get_image_origin_model_status()

    assert status["available"] is True
    assert status["model"] == IMAGE_ORIGIN_MODEL
