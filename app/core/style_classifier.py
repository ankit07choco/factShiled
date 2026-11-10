import re
import os
import joblib
from typing import Dict, Any

URGENCY_WORDS = [
    r'\burgent\b', r'\bbreaking\b', r'\bwarning\b', r'\bimportant\b',
    r'\bimmediate(ly)?\b', r'\balert\b', r'\battention\b', r'\bmust\s+read\b',
    r'\bज़रूरी\b', r'\bचेतावनी\b', r'\bজরুরি\b', r'\bসাবধান\b'
]

FORWARDING_WORDS = [
    r'forward\s+to', r'share\s+(with|to|maximum)', r'send\s+to\s+\d+',
    r'forward\s+this', r'share\s+before', r'don\'?t\s+ignore',
    r'शेयर\s+करें', r'भेजें', r'ফরওয়ার্ড', r'শেয়ার\s+করুন'
]

SENSATIONAL_WORDS = [
    r'\bsecret\b', r'\bshocking\b', r'\bmiracle\b', r'\b100%\s+true\b',
    r'\bcure\s+overnight\b', r'\bpharma\s+companies\b', r'\bproof\b',
    r'\bfree\s+recharge\b', r'\bclaim\s+now\b', r'\bhackers\b',
    r'\bचमत्कार\b', r'\bरहस्य\b', r'\bযাদুকরী\b'
]

AUTHORITY_INVOCATIONS = [
    r'\bunesco\b', r'\bnasa\b', r'\bwho\b', r'\brbi\b', r'\bisro\b',
    r'\bsupreme\s+court\b', r'\bgovernment\b', r'\bप्रधानमंत्री\b'
]

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'style_model.joblib')
VEC_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'style_vectorizer.joblib')

class StyleClassifier:
    """
    Analyzes WhatsApp forward text for linguistic markers of misinformation:
    - Sensationalism & Clickbait
    - ALL CAPS ratio
    - Exclamation & Question marks density
    - Forwarding pressure & Urgency
    - Authority hijacking
    - Pre-trained ML Logistic Regression classifier
    """
    def __init__(self):
        self.model = None
        self.vectorizer = None
        self._load_ml_model()

    def _load_ml_model(self):
        try:
            if os.path.exists(MODEL_PATH) and os.path.exists(VEC_PATH):
                self.model = joblib.load(MODEL_PATH)
                self.vectorizer = joblib.load(VEC_PATH)
        except Exception:
            self.model = None
            self.vectorizer = None

    def extract_features(self, text: str) -> Dict[str, Any]:
        if not text:
            return {
                "caps_ratio": 0.0,
                "exclamation_count": 0,
                "urgency_matches": 0,
                "forwarding_matches": 0,
                "sensational_matches": 0,
                "authority_matches": 0,
                "style_fake_probability": 0.0,
                "is_sensational": False,
                "flagged_markers": []
            }

        length = len(text)
        alpha_chars = [c for c in text if c.isalpha()]
        upper_chars = [c for c in alpha_chars if c.isupper()]
        caps_ratio = len(upper_chars) / max(len(alpha_chars), 1)

        excl_count = text.count('!')
        ques_count = text.count('?')

        flagged = []
        urgency_matches = 0
        for pattern in URGENCY_WORDS:
            if re.search(pattern, text, re.IGNORECASE):
                urgency_matches += 1
                flagged.append("Urgency/Alert tone")
                break

        forwarding_matches = 0
        for pattern in FORWARDING_WORDS:
            if re.search(pattern, text, re.IGNORECASE):
                forwarding_matches += 1
                flagged.append("Forwarding pressure ('Share/Forward')")
                break

        sensational_matches = 0
        for pattern in SENSATIONAL_WORDS:
            if re.search(pattern, text, re.IGNORECASE):
                sensational_matches += 1
                flagged.append("Sensational language ('Secret/Miracle/100%')")
                break

        authority_matches = 0
        for pattern in AUTHORITY_INVOCATIONS:
            if re.search(pattern, text, re.IGNORECASE):
                authority_matches += 1
                flagged.append("High-profile authority named (UNESCO/NASA/RBI)")
                break

        if caps_ratio > 0.40:
            flagged.append(f"Excessive ALL-CAPS text ({int(caps_ratio*100)}%)")

        if excl_count >= 3:
            flagged.append(f"Multiple exclamation marks ({excl_count})")

        # Heuristic style fake score (0.0 to 1.0)
        heuristic_score = 0.0
        heuristic_score += min(caps_ratio * 0.35, 0.35)
        heuristic_score += min((excl_count / 5.0) * 0.20, 0.20)
        heuristic_score += min(urgency_matches * 0.15, 0.15)
        heuristic_score += min(forwarding_matches * 0.20, 0.20)
        heuristic_score += min(sensational_matches * 0.15, 0.15)

        # ML prediction score
        ml_score = 0.5
        if self.model and self.vectorizer:
            try:
                vec = self.vectorizer.transform([text])
                probs = self.model.predict_proba(vec)[0]
                ml_score = float(probs[1]) if len(probs) > 1 else 0.5
            except Exception:
                ml_score = heuristic_score

        # Blended style score
        combined_score = (heuristic_score * 0.6) + (ml_score * 0.4)
        combined_score = min(max(combined_score, 0.05), 0.95)

        return {
            "caps_ratio": round(caps_ratio, 2),
            "exclamation_count": excl_count,
            "question_count": ques_count,
            "urgency_matches": urgency_matches,
            "forwarding_matches": forwarding_matches,
            "sensational_matches": sensational_matches,
            "authority_matches": authority_matches,
            "style_fake_probability": round(combined_score, 2),
            "is_sensational": combined_score >= 0.45,
            "flagged_markers": list(set(flagged))
        }

style_classifier = StyleClassifier()
