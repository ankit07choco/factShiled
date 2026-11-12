from fastapi.testclient import TestClient
from app.main import app
import hashlib
import hmac
import json
import pytest
from unittest.mock import patch

client = TestClient(app)

@pytest.fixture(autouse=True)
def isolate_verification_database(tmp_path, monkeypatch):
    from app.core.verification_store import VerificationStore

    store = VerificationStore(tmp_path / "test-verifications.sqlite3")
    monkeypatch.setattr("app.main.verification_store", store)
    monkeypatch.setattr("app.webhook.meta_whatsapp.verification_store", store)


def test_home_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "FactShield" in resp.text
    assert 'id="analytics-pane"' in resp.text
    assert 'id="history-pane"' in resp.text
    assert 'id="db-pane"' in resp.text
    assert 'id="adminLoginModal"' in resp.text
    assert 'href="/downloads/android"' in resp.text
    assert client.get("/api/session").json()["role"] == "user"
    print("✅ Home Page returns 200 OK")

def test_android_app_download_headers():
    resp = client.head("/downloads/android")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.android.package-archive"
    assert "attachment" in resp.headers["content-disposition"]
    assert int(resp.headers["content-length"]) > 0

def test_verify_endpoint_text():
    with patch(
        "app.core.pipeline.search_and_assess_claim",
        return_value={
            "status": "not_configured",
            "message": "Live search disabled in endpoint tests.",
            "verdict": "Unverified",
            "explanation": "",
            "sources": [],
        },
    ):
        resp = client.post("/api/verify", data={"text": "UNESCO has declared Indian National Anthem best in the world"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "Likely False"
    assert data["confidence_score"] >= 70
    assert "BOOM" in data["explanation"]
    print("✅ POST /api/verify correctly classified false claim with explanation")

def test_guest_verification_is_saved_and_matching_claim_is_updated():
    first_result = {
        "primary_claim": "The Sun rises in the east!",
        "verdict": "Likely True",
        "confidence_score": 91,
        "explanation": "Supported by a published fact-check.",
        "sources": [{"publisher": "Example", "url": "https://example.test/source"}],
        "signals": {"source_evidence": {"score": 90}},
    }
    second_result = {
        **first_result,
        "primary_claim": "THE SUN rises in the east.",
        "confidence_score": 94,
        "explanation": "The latest assessment still supports this claim.",
    }
    with patch(
        "app.main.pipeline.verify",
        side_effect=[first_result, second_result],
    ):
        first = client.post("/api/verify", data={"text": first_result["primary_claim"]})
        second = client.post("/api/verify", data={"text": second_result["primary_claim"]})

    assert first.status_code == second.status_code == 200
    assert first.json()["saved_to_database"] is True
    assert first.json()["database_record_id"] == second.json()["database_record_id"]
    records = client.get("/api/verifications").json()
    assert records["total"] == 1
    record = records["data"][0]
    assert record["verification_count"] == 2
    assert record["confidence_score"] == 94
    assert record["sources"][0]["publisher"] == "Example"

def test_unverified_result_is_not_saved():
    with patch(
        "app.main.pipeline.verify",
        return_value={
            "primary_claim": "A claim with no decisive evidence.",
            "verdict": "Unverified",
            "confidence_score": 0,
            "explanation": "No decisive evidence was found.",
        },
    ):
        response = client.post("/api/verify", data={"text": "A claim with no decisive evidence."})

    assert response.status_code == 200
    assert response.json()["saved_to_database"] is False
    assert client.get("/api/verifications").json()["total"] == 0

def test_image_verification_saves_result_without_retaining_image_bytes():
    with patch(
        "app.main.pipeline.verify",
        return_value={
            "primary_claim": "A verified claim extracted from an image.",
            "verdict": "Likely True",
            "confidence_score": 86,
            "explanation": "The claim matched reliable evidence.",
            "image_origin": {
                "status": "success",
                "verdict": "Inconclusive",
                "explanation": "No clear visual evidence.",
            },
        },
    ):
        response = client.post(
            "/api/verify",
            data={"text": "A claim from an image."},
            files={"image": ("forward.png", b"private-image-bytes", "image/png")},
        )

    assert response.status_code == 200
    record = client.get("/api/verifications").json()["data"][0]
    assert record["claim"] == "A verified claim extracted from an image."
    assert "image" not in record
    assert b"private-image-bytes" not in json.dumps(record).encode()

def test_admin_login_edit_delete_and_guest_access(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "ADMIN_USERNAME", "site-admin")
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "strong-test-password")
    monkeypatch.setattr(main_module, "SESSION_SECRET_CONFIGURED", True)
    monkeypatch.setattr(main_module, "ADMIN_LOGIN_ENABLED", True)
    test_client = TestClient(app, base_url="https://testserver")

    with patch(
        "app.main.pipeline.verify",
        return_value={
            "primary_claim": "A verified example claim.",
            "verdict": "Likely True",
            "confidence_score": 88,
            "explanation": "Evidence supports this claim.",
            "sources": [],
        },
    ):
        response = test_client.post("/api/verify", data={"text": "A verified example claim."})
    record_id = response.json()["database_record_id"]
    changes = {
        "claim": "An admin-corrected verified example claim.",
        "verdict": "Likely False",
        "confidence_score": 97,
        "explanation": "The administrator reviewed the cited evidence.",
        "sources": [],
    }

    assert test_client.get("/api/session").json()["role"] == "user"
    assert test_client.put(f"/api/verifications/{record_id}", json=changes).status_code == 403
    login = test_client.post(
        "/api/admin/login",
        json={"username": "site-admin", "password": "strong-test-password"},
    )
    assert login.status_code == 200
    csrf_token = login.json()["csrf_token"]
    assert test_client.get("/api/session").json()["role"] == "admin"
    assert test_client.put(
        f"/api/verifications/{record_id}", json=changes
    ).status_code == 403

    updated = test_client.put(
        f"/api/verifications/{record_id}",
        json=changes,
        headers={"X-CSRF-Token": csrf_token},
    )
    assert updated.status_code == 200
    saved = test_client.get("/api/verifications").json()["data"][0]
    assert saved["verdict"] == "Likely False"
    assert saved["claim"] == changes["claim"]

    deleted = test_client.delete(
        f"/api/verifications/{record_id}",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert deleted.status_code == 200
    assert test_client.get("/api/verifications").json()["total"] == 0
    assert test_client.post(
        "/api/admin/logout", headers={"X-CSRF-Token": csrf_token}
    ).json()["role"] == "user"

def test_admin_login_is_disabled_without_explicit_configuration(monkeypatch):
    import app.main as main_module

    monkeypatch.setattr(main_module, "ADMIN_USERNAME", "")
    monkeypatch.setattr(main_module, "ADMIN_PASSWORD", "")
    monkeypatch.setattr(main_module, "SESSION_SECRET_CONFIGURED", False)
    monkeypatch.setattr(main_module, "ADMIN_LOGIN_ENABLED", False)
    response = client.post(
        "/api/admin/login",
        json={"username": "admin", "password": "anything"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]

def test_verify_bengali_chandrayaan_claim():
    claim = "চন্দ্রযান-৩ ২০২৩ সালের ২৩ আগস্ট চাঁদে সফলভাবে অবতরণ করেছিল।"
    with patch(
        "app.core.pipeline.search_and_assess_claim",
        return_value={
            "status": "not_configured",
            "message": "Live search disabled in endpoint tests.",
            "verdict": "Unverified",
            "explanation": "",
            "sources": [],
        },
    ):
        resp = client.post("/api/verify", data={"text": claim})
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "Likely True"
    assert data["confidence_score"] >= 70
    assert "ISRO" in data["explanation"]
    assert data["sources"][0]["url"] == "https://www.isro.gov.in/Chandrayaan3.html"

def test_fact_checks_api():
    resp = client.get("/api/fact-checks?query=garlic")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert "COVID" in data["data"][0]["claim"]
    print("✅ GET /api/fact-checks search filter works")

def test_analytics_api():
    resp = client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "verdict_distribution" in data
    assert "pipeline_weights" in data
    print("✅ GET /api/analytics returns distribution stats")

def test_viva_api():
    resp = client.get("/api/viva-info")
    assert resp.status_code == 200
    data = resp.json()
    assert "evaluation_metrics" in data
    assert "limitations" in data
    print("✅ GET /api/viva-info returns viva defense metrics")

def test_viva_api_does_not_invent_perfect_metrics_when_file_missing():
    with patch("app.main.os.path.exists", return_value=False):
        resp = client.get("/api/viva-info")
    assert resp.status_code == 200
    assert resp.json()["evaluation_metrics"] == {}

def test_integrations_status_reports_local_model_without_api_keys():
    with patch(
        "app.main.get_local_model_status",
        return_value={
            "available": True,
            "model": "qwen3:4b",
            "message": "Local model is ready.",
        },
    ), patch(
        "app.main.get_image_origin_model_status",
        return_value={
            "available": True,
            "model": "qwen2.5vl:3b",
            "message": "Local image-origin model is ready.",
        },
    ):
        resp = client.get("/api/integrations-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["web_search_requires_api_key"] is False
    assert data["web_search_provider"] == "Bing public search page with Wikipedia fallback"
    assert data["local_model_provider"] == "Ollama"
    assert data["local_model_available"] is True
    assert data["image_origin_model_available"] is True
    assert data["image_origin_model"] == "qwen2.5vl:3b"
    assert data["local_fact_check_records"] >= 1
    assert "api_key" not in data

def test_image_only_verification_returns_image_origin_result_without_ocr_text():
    result = {
        "error": "No readable text was found in the image.",
        "verdict": "Unverified",
        "image_origin": {
            "status": "success",
            "verdict": "Inconclusive",
            "explanation": "No reliable visual provenance clues were found.",
        },
    }
    with patch("app.main.pipeline.verify", return_value=result):
        response = client.post(
            "/api/verify",
            files={"image": ("image.png", b"image-bytes", "image/png")},
        )

    assert response.status_code == 200
    assert response.json()["image_origin"]["verdict"] == "Inconclusive"

def test_fever_benchmark_endpoints_keep_research_labels_separate():
    status = {
        "available": True,
        "record_count": 145449,
        "dataset": "FEVER v1.0 training split",
        "attribution": "FEVER dataset authors",
        "license": "CC BY-SA 3.0",
        "license_url": "https://fever.ai/download/fever/license.html",
        "source_url": "https://fever.ai/download/fever/train.jsonl",
        "note": "Research benchmark only",
    }
    results = [{
        "id": 62037,
        "claim": "Oliver Reed was a film actor.",
        "label": "SUPPORTS",
        "dataset": "FEVER v1.0 research benchmark",
        "evidence_articles": [{
            "title": "Oliver Reed",
            "url": "https://en.wikipedia.org/wiki/Oliver_Reed",
        }],
    }]
    with patch("app.main.get_fever_status", return_value=status), \
         patch("app.main.search_fever_claims", return_value=results):
        status_response = client.get("/api/benchmark/status")
        search_response = client.get(
            "/api/benchmark/search",
            params={"q": "Oliver Reed actor"}
        )

    assert status_response.status_code == 200
    assert status_response.json()["record_count"] >= 100000
    assert search_response.status_code == 200
    data = search_response.json()
    assert "not published fact-check verdicts" in data["warning"]
    assert data["data"][0]["label"] == "SUPPORTS"
    assert data["attribution"] == "FEVER dataset authors"

def test_whatsapp_status_does_not_expose_credentials():
    with patch("app.main.WEBHOOK_VERIFY_TOKEN", "verify-token"), \
         patch("app.main.META_APP_SECRET", "app-secret"), \
         patch("app.main.WHATSAPP_API_TOKEN", "private-access-token"), \
         patch("app.main.META_PHONE_NUMBER_ID", "phone-id"):
        resp = client.get("/api/whatsapp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "live_messaging_ready" in data
    assert data["provider"] == "Meta WhatsApp Cloud API"
    assert data["live_messaging_ready"] is True
    assert "access_token_configured" in data
    assert "private-access-token" not in resp.text

def test_verify_rejects_empty_request():
    resp = client.post("/api/verify")
    assert resp.status_code == 400
    assert "error" in resp.json()

def test_video_upload_is_rejected():
    resp = client.post(
        "/api/verify",
        files={"video": ("forward.mp4", b"video-data", "video/mp4")}
    )
    assert resp.status_code == 415
    assert "not supported" in resp.json()["error"]

def test_video_is_absent_from_verification_api_schema():
    schema = client.get("/openapi.json").json()
    request_schema = schema["paths"]["/api/verify"]["post"]["requestBody"]["content"][
        "multipart/form-data"
    ]["schema"]
    schema_name = request_schema["$ref"].rsplit("/", 1)[-1]
    fields = schema["components"]["schemas"][schema_name]["properties"]
    assert set(fields) == {"text", "image", "input_mode"}

def test_live_webhook_requires_signature_secret():
    payload = {"object": "whatsapp_business_account", "entry": []}
    with patch("app.main.META_APP_SECRET", ""):
        resp = client.post("/webhook/whatsapp", json=payload)
    assert resp.status_code == 503

def test_signed_live_webhook_sends_reply():
    payload = {"object": "whatsapp_business_account", "entry": []}
    body = json.dumps(payload).encode("utf-8")
    signature = "sha256=" + hmac.new(
        b"test-app-secret", body, hashlib.sha256
    ).hexdigest()
    processed = {
        "success": True,
        "messages": [{"sender_id": "919876543210", "reply_text": "Verified reply"}]
    }
    with patch("app.main.META_APP_SECRET", "test-app-secret"), \
         patch("app.main.META_PHONE_NUMBER_ID", "test-phone-id"), \
         patch("app.main.WHATSAPP_API_TOKEN", "test-access-token"), \
         patch("app.main.process_whatsapp_payload", return_value=processed), \
         patch("app.main.send_meta_whatsapp_message", return_value=True) as send:
        resp = client.post(
            "/webhook/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": signature
            }
        )
    assert resp.status_code == 200
    assert resp.json()["messages"][0]["delivered"] is True
    send.assert_called_once_with(
        "919876543210",
        "Verified reply",
        phone_number_id="test-phone-id",
        access_token="test-access-token"
    )

def test_webhook_simulator():
    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919876543210",
                        "type": "text",
                        "text": {"body": "Drink boiled garlic water to cure covid overnight"}
                    }]
                }
            }]
        }]
    }
    resp = client.post("/webhook/whatsapp", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "reply_text" in data
    assert "Alt News" in data["reply_text"]
    assert client.get("/api/verifications").json()["total"] >= 1
    print("✅ POST /webhook/whatsapp processes Meta Cloud API payload and creates reply")

if __name__ == "__main__":
    test_home_page()
    test_verify_endpoint_text()
    test_fact_checks_api()
    test_analytics_api()
    test_viva_api()
    test_webhook_simulator()
    print("\n🎉 All 6 API endpoints tested and functioning 100%!")
