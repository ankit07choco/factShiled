from fastapi.testclient import TestClient
from app.main import app
import hashlib
import hmac
import json
from unittest.mock import patch

client = TestClient(app)

def test_home_page():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "FactShield" in resp.text
    assert 'id="analytics-pane"' in resp.text
    assert 'id="db-pane"' in resp.text
    print("✅ Home Page returns 200 OK")

def test_verify_endpoint_text():
    resp = client.post("/api/verify", data={"text": "UNESCO has declared Indian National Anthem best in the world"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["verdict"] == "Likely False"
    assert data["confidence_score"] >= 70
    assert "BOOM" in data["explanation"]
    print("✅ POST /api/verify correctly classified false claim with explanation")

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

def test_whatsapp_status_does_not_expose_credentials():
    resp = client.get("/api/whatsapp-status")
    assert resp.status_code == 200
    data = resp.json()
    assert "live_messaging_ready" in data
    assert "access_token_configured" in data
    assert "access_token" not in data

def test_verify_rejects_empty_request():
    resp = client.post("/api/verify")
    assert resp.status_code == 400
    assert "error" in resp.json()

def test_video_upload_reports_missing_video_support():
    with patch(
        "app.main.extract_text_from_video",
        return_value={
            "success": False,
            "extracted_text": "",
            "error": "Video frame extraction is unavailable. Install FFmpeg."
        }
    ):
        resp = client.post(
            "/api/verify",
            files={"video": ("forward.mp4", b"video-data", "video/mp4")}
        )
    assert resp.status_code == 503
    assert "FFmpeg" in resp.json()["error"]

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
    print("✅ POST /webhook/whatsapp processes Meta Cloud API payload and creates reply")

if __name__ == "__main__":
    test_home_page()
    test_verify_endpoint_text()
    test_fact_checks_api()
    test_analytics_api()
    test_viva_api()
    test_webhook_simulator()
    print("\n🎉 All 6 API endpoints tested and functioning 100%!")
