import unittest
import json
from types import SimpleNamespace
from io import BytesIO
from unittest.mock import patch
from PIL import Image
from app.core.preprocessing import detect_language, extract_urls, clean_text, extract_text_from_image
from app.core.claim_extraction import extract_claims
from app.core.style_classifier import style_classifier
from app.core.fact_check_search import fact_check_engine
from app.core.scoring import compute_verdict_and_score
from app.core.pipeline import pipeline
from app.webhook.meta_whatsapp import (
    process_whatsapp_payload,
    send_meta_whatsapp_message,
    verify_meta_signature,
    verify_meta_webhook
)

class TestFactShieldPipeline(unittest.TestCase):

    def setUp(self):
        patcher = patch("app.core.fact_check_search.GOOGLE_FACT_CHECK_API_KEY", "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_preprocessing_language_and_urls(self):
        text_en = "UNESCO has declared the Indian National Anthem as the best in the world. https://factcheck.org"
        lang_en = detect_language(text_en)
        self.assertEqual(lang_en['code'], 'en')
        
        urls = extract_urls(text_en)
        self.assertEqual(len(urls), 1)
        self.assertTrue("factcheck.org" in urls[0])

        # Hindi text detection
        text_hi = "प्रधानमंत्री योजना के तहत मुफ्त रीचार्ज मिल रहा है।"
        lang_hi = detect_language(text_hi)
        self.assertEqual(lang_hi['code'], 'hi')
        self.assertTrue(lang_hi['is_indian_lang'])

    def test_claim_extraction(self):
        noisy_forward = "URGENT MUST SHARE!! Forwarded as received: UNESCO has declared the Indian National Anthem best in the world. Forward to 10 groups immediately!"
        extracted = extract_claims(noisy_forward)
        self.assertNotIn("Forwarded as received", extracted["primary_claim"])
        self.assertNotIn("Forward to 10 groups", extracted["primary_claim"])
        self.assertTrue("UNESCO" in extracted["primary_claim"])

    def test_style_classifier(self):
        fake_style_text = "BREAKING NEWS!! SHARE IMMEDIATELY TO 10 GROUPS!! SECRET REMEDY 100% TRUE!!"
        features = style_classifier.extract_features(fake_style_text)
        self.assertTrue(features["is_sensational"])
        self.assertGreater(features["style_fake_probability"], 0.40)
        self.assertGreater(len(features["flagged_markers"]), 0)

        calm_news = "The meteorological department issued a forecast for seasonal precipitation next week."
        calm_features = style_classifier.extract_features(calm_news)
        self.assertFalse(calm_features["is_sensational"])
        self.assertLess(calm_features["style_fake_probability"], 0.40)

    def test_image_ocr_never_invents_claim_text(self):
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(image_buffer, format="PNG")
        with patch("pytesseract.image_to_string", return_value=""):
            result = extract_text_from_image(image_buffer.getvalue())
        self.assertFalse(result["success"])
        self.assertEqual(result["extracted_text"], "")
        self.assertIn("No readable text", result["error"])

    def test_image_ocr_reports_how_to_configure_missing_tesseract(self):
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(image_buffer, format="PNG")
        with patch(
            "pytesseract.image_to_string",
            side_effect=pytesseract.pytesseract.TesseractNotFoundError()
        ):
            result = extract_text_from_image(image_buffer.getvalue())
        self.assertFalse(result["success"])
        self.assertIn("TESSERACT_CMD", result["error"])
        self.assertIn("tesseract.exe", result["error"])

    def test_image_ocr_finds_default_windows_tesseract_installation(self):
        import pytesseract

        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), "white").save(image_buffer, format="PNG")
        default_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        with (
            patch.dict("os.environ", {"TESSERACT_CMD": ""}),
            patch("shutil.which", return_value=None),
            patch("os.path.isfile", return_value=True),
            patch("pytesseract.image_to_string", return_value="Recognized text"),
            patch.object(pytesseract.pytesseract, "tesseract_cmd", "tesseract"),
        ):
            result = extract_text_from_image(image_buffer.getvalue())
            self.assertEqual(pytesseract.pytesseract.tesseract_cmd, default_path)
        self.assertTrue(result["success"])
        self.assertEqual(result["extracted_text"], "Recognized text")

    def test_fact_check_search(self):
        matches = fact_check_engine.find_matches("UNESCO declared Jana Gana Mana best national anthem")
        self.assertTrue(matches["has_match"])
        top = matches["top_match"]
        self.assertEqual(top["id"], "FC-001")
        self.assertEqual(top["verdict"], "False")

    def test_local_search_discards_zero_similarity_records(self):
        matches = fact_check_engine.find_matches(
            "A newly discovered comet will pass Earth next month.",
            api_key=""
        )
        self.assertFalse(matches["has_match"])
        self.assertIsNone(matches["top_match"])
        self.assertEqual(matches["external_lookup"]["status"], "not_configured")

    def test_google_fact_check_api_parses_rating_and_language(self):
        payload = {
            "claims": [{
                "text": "The claim that water boils at 100 degrees Celsius at sea level.",
                "claimReview": [{
                    "textualRating": "Mostly True",
                    "publisher": {"name": "Example Fact Check"},
                    "url": "https://example.test/review",
                    "reviewDate": "2026-01-01T00:00:00Z",
                    "languageCode": "en"
                }]
            }]
        }
        with patch(
            "app.core.fact_check_search.requests.get",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: payload
            )
        ) as get:
            matches = fact_check_engine.find_matches(
                "The claim that water boils at 100 degrees Celsius at sea level.",
                api_key="test-key",
                language_code="en"
            )

        self.assertTrue(matches["has_match"])
        self.assertEqual(matches["top_match"]["verdict"], "True")
        self.assertEqual(matches["top_match"]["publisher"], "Example Fact Check")
        self.assertEqual(matches["external_lookup"]["status"], "success")
        self.assertEqual(get.call_args.kwargs["params"]["languageCode"], "en")
        self.assertEqual(get.call_args.kwargs["timeout"], 8)

    def test_google_api_unrelated_results_do_not_create_verdict(self):
        payload = {
            "claims": [{
                "text": "A local football team won their match on Saturday.",
                "claimReview": [{
                    "textualRating": "True",
                    "publisher": {"name": "Example"},
                    "url": "https://example.test/review"
                }]
            }]
        }
        with patch(
            "app.core.fact_check_search.requests.get",
            return_value=SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: payload
            )
        ):
            matches = fact_check_engine.find_matches(
                "The moon is made of green cheese.",
                api_key="test-key"
            )

        self.assertFalse(matches["has_match"])
        self.assertIsNone(matches["top_match"])
        self.assertEqual(matches["external_lookup"]["status"], "success")

    def test_google_fact_check_api_errors_are_reported(self):
        import requests
        with patch(
            "app.core.fact_check_search.requests.get",
            side_effect=requests.Timeout()
        ):
            matches = fact_check_engine.find_matches(
                "A well-formed factual claim",
                api_key="test-key"
            )
        self.assertEqual(matches["external_lookup"]["status"], "error")
        self.assertIsNotNone(matches["external_lookup"]["message"])

    def test_google_api_http_errors_give_actionable_diagnostics_without_key(self):
        import requests

        response = SimpleNamespace(status_code=403)
        error = requests.HTTPError(response=response)
        with patch(
            "app.core.fact_check_search.requests.get",
            side_effect=error
        ):
            matches = fact_check_engine.find_matches(
                "A well-formed factual claim",
                api_key="private-test-key"
            )

        lookup = matches["external_lookup"]
        self.assertEqual(lookup["status"], "error")
        self.assertEqual(lookup["http_status"], 403)
        self.assertIn("API is enabled", lookup["message"])
        self.assertNotIn("private-test-key", lookup["message"])

    def test_full_pipeline_verification(self):
        # 1. Known false claim
        result_false = pipeline.verify(text="UNESCO has declared our anthem as the best national anthem in the world!! SHARE MAXIMUM!!")
        self.assertEqual(result_false["verdict"], "Likely False")
        self.assertGreaterEqual(result_false["confidence_score"], 70)
        self.assertTrue("BOOM" in result_false["explanation"] or "fact-check" in result_false["explanation"].lower())
        self.assertIn("whatsapp_reply", result_false)

        # 2. Known true claim
        result_true = pipeline.verify(text="ISRO launched Chandrayaan-3 successfully to lunar south pole")
        self.assertEqual(result_true["verdict"], "Likely True")
        self.assertGreaterEqual(result_true["confidence_score"], 70)

        # 3. Novel unverified claim
        result_novel = pipeline.verify(text="Local library in Springfield added 20 new books yesterday.")
        self.assertEqual(result_novel["verdict"], "Unverified")

    def test_venus_rotation_fact_is_verified_true(self):
        claim = "Fun fact: Venus takes longer to spin once on its axis than to go around the Sun."
        matches = fact_check_engine.find_matches(claim)
        self.assertTrue(matches["has_match"])
        self.assertEqual(matches["top_match"]["id"], "FC-009")

        result = pipeline.verify(text=claim)
        self.assertEqual(result["verdict"], "Likely True")
        self.assertGreaterEqual(result["confidence_score"], 70)
        self.assertIn("NASA", result["explanation"])
        self.assertEqual(result["sources"][0]["url"], "https://science.nasa.gov/venus/venus-facts/")

    def test_bengali_chandrayaan_landing_claim_is_verified_true(self):
        claim = "চন্দ্রযান-৩ ২০২৩ সালের ২৩ আগস্ট চাঁদে সফলভাবে অবতরণ করেছিল।"
        matches = fact_check_engine.find_matches(claim)
        self.assertTrue(matches["has_match"])
        self.assertEqual(matches["top_match"]["id"], "FC-007")

        result = pipeline.verify(text=claim)
        self.assertEqual(result["verdict"], "Likely True")
        self.assertGreaterEqual(result["confidence_score"], 70)
        self.assertIn("ISRO", result["explanation"])

    def test_chandrayaan_landing_date_conflict_is_likely_false(self):
        result = pipeline.verify(
            text="Chandrayaan-3 landed on the Moon on 24 August 2023."
        )
        self.assertEqual(result["verdict"], "Likely False")
        self.assertIn("2023-08-24", result["explanation"])
        self.assertIn("2023-08-23", result["explanation"])
        self.assertEqual(
            result["sources"][0]["url"],
            "https://www.isro.gov.in/Chandrayaan3.html"
        )

    def test_chandrayaan_correct_landing_date_remains_likely_true(self):
        result = pipeline.verify(
            text="Chandrayaan-3 landed on the Moon on 23 August 2023."
        )
        self.assertEqual(result["verdict"], "Likely True")

    def test_meta_webhook(self):
        # Test verification handshake
        with patch("app.webhook.meta_whatsapp.WEBHOOK_VERIFY_TOKEN", "test-token"):
            challenge = verify_meta_webhook("subscribe", "test-token", "123456789")
            bad = verify_meta_webhook("subscribe", "wrong_token", "123456789")
        self.assertEqual(challenge, 123456789)

        # Test invalid token handshake
        self.assertIsNone(bad)
        with patch("app.webhook.meta_whatsapp.WEBHOOK_VERIFY_TOKEN", ""):
            self.assertIsNone(verify_meta_webhook("subscribe", None, "123456789"))

        # Test simulated payload processing
        test_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "919876543210",
                            "type": "text",
                            "text": {"body": "Drinking garlic water cures COVID-19 infection overnight"}
                        }]
                    }
                }]
            }]
        }
        resp = process_whatsapp_payload(test_payload)
        self.assertTrue(resp["success"])
        self.assertEqual(resp["pipeline_result"]["verdict"], "Likely False")
        self.assertIn("Alt News", resp["reply_text"])

    def test_meta_signature_verification(self):
        body = b'{"object":"whatsapp_business_account"}'
        import hashlib
        import hmac
        signature = "sha256=" + hmac.new(
            b"app-secret", body, hashlib.sha256
        ).hexdigest()
        self.assertTrue(verify_meta_signature(body, signature, "app-secret"))
        self.assertFalse(verify_meta_signature(body, "sha256=invalid", "app-secret"))
        self.assertFalse(verify_meta_signature(body, None, "app-secret"))

    def test_video_webhook_returns_clear_media_processing_status(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "919876543210",
                            "type": "video",
                            "video": {"id": "media-id"}
                        }]
                    }
                }]
            }]
        }
        with patch("app.core.preprocessing.shutil.which", return_value=None):
            response = process_whatsapp_payload(
                payload,
                media_downloader=lambda _: (b"video-bytes", "video/mp4")
            )
        self.assertTrue(response["success"])
        self.assertIn("FFmpeg", response["reply_text"])

    def test_whatsapp_send_uses_bearer_token(self):
        class FakeResponse:
            ok = True

        with patch("app.webhook.meta_whatsapp.requests.post", return_value=FakeResponse()) as post:
            sent = send_meta_whatsapp_message(
                "919876543210",
                "Test reply",
                phone_number_id="phone-id",
                access_token="test-access-token"
            )
        self.assertTrue(sent)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-access-token"
        )

if __name__ == '__main__':
    unittest.main()
