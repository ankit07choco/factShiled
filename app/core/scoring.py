from typing import Dict, Any, List

VERDICT_LIKELY_FALSE = "Likely False"
VERDICT_DISPUTED = "Disputed"
VERDICT_UNVERIFIED = "Unverified"
VERDICT_LIKELY_TRUE = "Likely True"

def compute_verdict_and_score(
    fact_check_result: Dict[str, Any],
    web_search_result: Dict[str, Any],
    style_features: Dict[str, Any],
    claim_text: str,
    urls: List[str]
) -> Dict[str, Any]:
    """
    Computes multi-signal weighted verdict, 0-100 confidence score,
    and structured explainability.
    """
    top_match = fact_check_result.get("top_match")
    has_strong_fc = fact_check_result.get("has_match", False)
    fc_sim = top_match.get("similarity_score", 0.0) if top_match else 0.0

    style_fake_prob = style_features.get("style_fake_probability", 0.1)
    is_sensational = style_features.get("is_sensational", False)

    # Weights
    w_fc = 0.40
    w_sem = 0.25
    w_style = 0.20
    w_evid = 0.15

    evidence_score = 0.8 if urls else 0.3

    # Baseline fake score (0 to 100)
    fake_score = 50.0

    has_web_assessment = (
        web_search_result.get("status") == "success"
        and web_search_result.get("sources")
    )

    if has_strong_fc and top_match:
        fc_verdict = str(top_match.get("verdict", "")).lower()
        if "false" in fc_verdict or "scam" in fc_verdict or "misleading" in fc_verdict:
            # Fact check says false
            fake_score = (
                (fc_sim * 100 * w_fc) +
                (85 * w_sem) +
                (style_fake_prob * 100 * w_style) +
                (20 * w_evid)
            )
            fake_score = max(fake_score, 78.0)
            verdict = VERDICT_LIKELY_FALSE
            confidence = min(round(fake_score), 98)
            date_mismatch = top_match.get("date_mismatch")
            if date_mismatch:
                explanation = (
                    f"The claim gives {date_mismatch['claimed_date']}, but "
                    f"{top_match.get('publisher', 'the source')} records the event "
                    f"date as {date_mismatch['verified_date']}."
                )
            else:
                explanation = (
                    f"A closely matching claim was previously debunked as FALSE by "
                    f"{top_match.get('publisher', 'independent fact-checkers')}."
                )
        elif "true" in fc_verdict:
            # Fact check says true
            fake_score = (1.0 - fc_sim) * 30 + (style_fake_prob * 20)
            fake_score = min(fake_score, 25.0)
            verdict = VERDICT_LIKELY_TRUE
            confidence = min(round(100 - fake_score), 95)
            explanation = (
                f"A verified official source ({top_match.get('publisher', 'official agency')}) "
                f"confirms this claim is genuine."
            )
        else:
            verdict = VERDICT_UNVERIFIED
            confidence = 35
            explanation = (
                "A related published review was found, but it does not provide a clear "
                "true/false rating for this claim."
            )
    elif has_web_assessment:
        verdict = web_search_result.get("verdict", VERDICT_UNVERIFIED)
        if verdict not in {
            VERDICT_LIKELY_FALSE,
            VERDICT_LIKELY_TRUE,
            VERDICT_DISPUTED,
            VERDICT_UNVERIFIED,
        }:
            verdict = VERDICT_UNVERIFIED
        web_explanation = web_search_result.get("explanation") or (
            "Web search did not provide enough direct evidence to assess this claim."
        )
        explanation = (
            "AI assessment grounded in Bing search results using a local model "
            "(not a published fact-check): "
            f"{web_explanation}"
        )
        confidence = {
            VERDICT_LIKELY_FALSE: 65,
            VERDICT_LIKELY_TRUE: 65,
            VERDICT_DISPUTED: 50,
            VERDICT_UNVERIFIED: 35,
        }[verdict]
    else:
        # No direct fact check found in database
        if is_sensational or style_fake_prob >= 0.50:
            verdict = VERDICT_UNVERIFIED
            fake_score = 45.0 + (style_fake_prob * 30.0)
            confidence = round(fake_score)
            explanation = (
                "No published fact-check was found for this specific claim, "
                "but the message displays high sensationalism, forwarding pressure, or viral hoax patterns."
            )
        else:
            verdict = VERDICT_UNVERIFIED
            fake_score = 30.0
            confidence = 35
            explanation = (
                "Unverified: No matching fact-check found in the database. "
                "Brand-new claims require independent journalistic confirmation."
            )

    # Signal breakdown for dashboard & viva presentation
    signals = {
        "fact_check_match": {
            "score": round(fc_sim * 100, 1),
            "weight": "40%",
            "source": top_match.get("publisher", "None") if top_match else "None",
            "rating": top_match.get("rating", "N/A") if top_match else "No match"
        },
        "semantic_similarity": {
            "score": round(fc_sim * 100, 1),
            "weight": "25%",
            "detail": f"Matched index with cosine similarity {fc_sim:.2f}"
        },
        "style_classifier": {
            "score": round(style_fake_prob * 100, 1),
            "weight": "20%",
            "sensational": is_sensational,
            "caps_ratio": f"{int(style_features.get('caps_ratio', 0) * 100)}%",
            "flagged": style_features.get("flagged_markers", [])
        },
        "source_evidence": {
            "score": round(evidence_score * 100, 1),
            "weight": "15%",
            "urls_detected": urls
        }
    }

    # WhatsApp-ready formatted message
    sources = []
    if top_match and top_match.get("url"):
        sources.append({
            "title": f"{top_match.get('publisher', 'Source')}: {top_match.get('claim', '')[:60]}...",
            "url": top_match.get("url"),
            "publisher": top_match.get("publisher", ""),
            "source_type": "Published fact-check"
        })
    for source in web_search_result.get("sources", []):
        if source.get("url") not in {item["url"] for item in sources}:
            sources.append(source)

    return {
        "verdict": verdict,
        "confidence_score": confidence,
        "explanation": explanation,
        "signals": signals,
        "top_source": top_match.get("url") if top_match else None,
        "sources": sources,
        "disclaimer": (
            "The score is an automated estimate, not absolute ground truth. "
            "Web-search assessments are AI-generated and are not published fact-checks."
        )
    }
