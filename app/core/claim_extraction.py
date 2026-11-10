import re

NOISE_PATTERNS = [
    r'forwarded\s+as\s+received',
    r'forward\s+to\s+\d+\s+(groups|people|friends|everyone)',
    r'must\s+share',
    r'urgent\s+notice',
    r'breaking\s+news',
    r'100%\s+true',
    r'please\s+forward',
    r'share\s+maximum',
    r'dont\s+ignore',
    r'कृपया\s+शेयर\s+करें',
    r'आगे\s+भेजें',
    r'সকলকে\s+শেয়ার\s+করুন',
]

def extract_claims(text: str) -> dict:
    """
    Strips WhatsApp noise, greetings, and forward markers to extract
    the core factual checkable sentence(s).
    """
    if not text:
        return {"primary_claim": "", "all_claims": [], "cleaned_text": ""}
    
    cleaned = text
    for pattern in NOISE_PATTERNS:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
    
    # Remove leading/trailing symbols, exclamations, emojis
    cleaned = re.sub(r'^[!\?\:\-\*\s]+', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # Split into sentences
    sentences = re.split(r'[\.\!\?\n]+', cleaned)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

    if not sentences:
        primary_claim = cleaned if len(cleaned) > 5 else text
        sentences = [primary_claim]
    else:
        # Pick sentence with highest density of entity / verb / subject
        primary_claim = max(sentences, key=len)

    return {
        "primary_claim": primary_claim,
        "all_claims": sentences,
        "cleaned_text": cleaned
    }

