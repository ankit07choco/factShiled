from typing import Optional, Dict, Any
from app.core.preprocessing import detect_language, extract_urls, clean_text, extract_text_from_image
from app.core.image_origin import assess_image_origin
from app.core.claim_extraction import extract_claims
from app.core.style_classifier import style_classifier
from app.core.fact_check_search import fact_check_engine
from app.core.local_web_search import search_and_assess_claim
from app.core.scoring import compute_verdict_and_score

class VerificationPipeline:
    def __init__(self):
        pass

    def verify(
        self,
        text: Optional[str] = None,
        image_bytes: Optional[bytes] = None
    ) -> Dict[str, Any]:
        """
        Runs the end-to-end verification pipeline on text or image WhatsApp forwards.
        """
        ocr_result = None
        input_text = text or ""
        image_origin_result = None

        # Step 1: Preprocess (OCR if image forward)
        if image_bytes:
            ocr_result = extract_text_from_image(image_bytes)
            image_origin_result = assess_image_origin(image_bytes)
            if ocr_result.get("success") and ocr_result.get("extracted_text"):
                input_text = f"{input_text} {ocr_result['extracted_text']}".strip()

        if not input_text:
            return {
                "error": (
                    ocr_result.get("error")
                    if ocr_result and ocr_result.get("error")
                    else "No readable text or image content was provided for verification."
                ),
                "verdict": "Unverified",
                "confidence_score": 0,
                "ocr_result": ocr_result,
                "image_origin": image_origin_result,
                "whatsapp_reply": (
                    "I could not read text from the image.\n\n"
                    f"🖼️ *Image origin assessment:* {image_origin_result['verdict']}.\n"
                    f"{image_origin_result['explanation']}\n\n"
                    f"_{image_origin_result['disclaimer']}_"
                    if image_origin_result else None
                ),
            }

        cleaned = clean_text(input_text)
        urls = extract_urls(input_text)
        lang_info = detect_language(input_text)

        # Step 2: Claim Extraction
        claim_data = extract_claims(cleaned)
        primary_claim = claim_data.get("primary_claim") or cleaned

        # Step 3: Multi-signal evaluation
        # Signal 1 & 2: Fact-Check API & Semantic vector DB search
        fact_check_result = fact_check_engine.find_matches(
            primary_claim,
            api_key="",
            language_code=lang_info["code"]
        )
        top_match = fact_check_result.get("top_match") or {}
        matched_verdict = str(top_match.get("verdict", "")).casefold()
        has_decisive_published_match = fact_check_result.get("has_match") and any(
            verdict in matched_verdict
            for verdict in ("false", "true", "scam", "misleading")
        )
        if has_decisive_published_match:
            web_search_result = {
                "status": "skipped",
                "message": (
                    "Public search was skipped because a relevant published "
                    "fact-check already provides a verdict."
                ),
                "verdict": "Unverified",
                "explanation": "",
                "sources": [],
            }
        else:
            web_search_result = search_and_assess_claim(primary_claim)

        # Signal 3: Style & Sensationalism classifier
        style_features = style_classifier.extract_features(input_text)

        # Step 4: Scoring Engine
        verdict_data = compute_verdict_and_score(
            fact_check_result=fact_check_result,
            web_search_result=web_search_result,
            style_features=style_features,
            claim_text=primary_claim,
            urls=urls
        )

        # Step 5: Format WhatsApp-ready reply
        whatsapp_reply = self.format_whatsapp_reply(
            verdict=verdict_data["verdict"],
            confidence=verdict_data["confidence_score"],
            primary_claim=primary_claim,
            explanation=verdict_data["explanation"],
            sources=verdict_data["sources"],
            signals=verdict_data["signals"],
            language=lang_info["name"]
        )
        if image_origin_result:
            whatsapp_reply += (
                f"\n\n🖼️ *Image origin assessment:* {image_origin_result['verdict']}.\n"
                f"{image_origin_result['explanation']}\n\n"
                f"_{image_origin_result['disclaimer']}_"
            )

        return {
            "input_text": input_text,
            "primary_claim": primary_claim,
            "language": lang_info,
            "urls_detected": urls,
            "ocr_result": ocr_result,
            "image_origin": image_origin_result,
            "verdict": verdict_data["verdict"],
            "confidence_score": verdict_data["confidence_score"],
            "explanation": verdict_data["explanation"],
            "signals": verdict_data["signals"],
            "sources": verdict_data["sources"],
            "fact_check_lookup": fact_check_result["external_lookup"],
            "web_search": web_search_result,
            "whatsapp_reply": whatsapp_reply,
            "disclaimer": verdict_data["disclaimer"]
        }

    def format_whatsapp_reply(
        self,
        verdict: str,
        confidence: int,
        primary_claim: str,
        explanation: str,
        sources: list,
        signals: dict,
        language: str
    ) -> str:
        """
        Creates a clean, human-readable WhatsApp message formatted with Markdown.
        """
        icon_map = {
            "Likely False": "❌ *LIKELY FALSE*",
            "Disputed": "⚠️ *DISPUTED*",
            "Unverified": "❓ *UNVERIFIED*",
            "Likely True": "✅ *LIKELY TRUE*"
        }
        verdict_str = icon_map.get(verdict, verdict)

        lines = [
            f"🔍 *FactShield Claim Verification*",
            f"━━━━━━━━━━━━━━━━━━━",
            f"*Verdict:* {verdict_str} ({confidence}% confidence)",
            f"*Language:* {language}",
            f"",
            f"📌 *Checked Claim:*",
            f"\"{primary_claim[:140]}...\"",
            f"",
            f"💡 *Why this verdict?*",
            f"{explanation}",
            f"",
            f"📊 *Signal Breakdown:*",
            f"• Fact-Check Match: {signals['fact_check_match']['rating']} ({signals['fact_check_match']['source']})",
            f"• Sensationalism: {'High' if signals['style_classifier']['sensational'] else 'Normal'} (Caps: {signals['style_classifier']['caps_ratio']})"
        ]

        if sources:
            lines.append("")
            lines.append("🔗 *Sources consulted:*")
            for s in sources:
                source_type = s.get("source_type", "Published fact-check")
                lines.append(f"• {source_type} — {s['publisher']}: {s['url']}")

        lines.append("")
        lines.append("⚠️ _Note: Automated estimate, not absolute truth. Always verify with official news outlets._")
        return "\n".join(lines)

pipeline = VerificationPipeline()
