import json
import logging
import os
import re
from datetime import date
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'fact_checks_db.json')
GOOGLE_FACT_CHECK_API_KEY = os.getenv("GOOGLE_FACT_CHECK_API_KEY", "")
GOOGLE_FACT_CHECK_ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
MIN_MATCH_SCORE = 0.25
logger = logging.getLogger(__name__)

ENGLISH_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "did", "do",
    "does", "for", "from", "has", "have", "in", "is", "it", "of", "on",
    "or", "that", "the", "their", "there", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "with"
}
MONTH_NUMBERS = {
    month.casefold(): number
    for number, month in enumerate(
        ("January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"),
        start=1
    )
}

class FactCheckSearchEngine:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = os.path.abspath(db_path)
        self.fact_checks = []
        self.vectorizer = None
        self.tfidf_matrix = None
        self.corpus = []
        self.load_database()

    def load_database(self):
        """Loads fact checks from JSON and initializes the TF-IDF search index."""
        if os.path.exists(self.db_path):
            with open(self.db_path, 'r', encoding='utf-8') as f:
                self.fact_checks = json.load(f)
        else:
            self.fact_checks = []

        # Include every translated record field and source text in the local index.
        self.corpus = []
        for fc in self.fact_checks:
            text_tokens = [
                value for key, value in fc.items()
                if key.startswith("claim_") and isinstance(value, str)
            ]
            text_tokens.extend([
                fc.get('claim', ''),
                fc.get('summary', ''),
                ' '.join(fc.get('keywords', [])),
                fc.get('category', '')
            ])
            self.corpus.append(' '.join(filter(None, text_tokens)))

        if self.corpus:
            self.vectorizer = TfidfVectorizer(
                ngram_range=(1, 2),
                stop_words='english',
                token_pattern=r'(?u)\b\w+\b'
            )
            self.tfidf_matrix = self.vectorizer.fit_transform(self.corpus)

    def search_local_db(self, query: str, top_k: int = 3, min_score: float = 0.20) -> List[Dict[str, Any]]:
        """
        Performs semantic vector search against local fact-check database.
        """
        if not self.corpus or not self.vectorizer or not query.strip():
            return []

        query_vec = self.vectorizer.transform([query])
        sim_scores = cosine_similarity(query_vec, self.tfidf_matrix)[0]

        ranked_indices = sim_scores.argsort()[::-1]
        results = []

        for idx in ranked_indices:
            score = float(sim_scores[idx])
            if score < min_score:
                break
            item = dict(self.fact_checks[idx])
            item['similarity_score'] = round(score, 3)
            expected_date = item.get("event_date")
            claimed_date = self._extract_english_date(query)
            if expected_date and claimed_date and claimed_date != expected_date:
                item["verdict"] = "False"
                item["rating"] = "FALSE"
                item["date_mismatch"] = {
                    "claimed_date": claimed_date,
                    "verified_date": expected_date
                }
            results.append(item)
            if len(results) >= top_k:
                break

        return results

    @staticmethod
    def _extract_english_date(text: str) -> Optional[str]:
        month_pattern = "|".join(MONTH_NUMBERS)
        patterns = (
            re.compile(
                rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+"
                rf"(?P<month>{month_pattern})\s+(?P<year>\d{{4}})\b",
                re.IGNORECASE
            ),
            re.compile(
                rf"\b(?P<month>{month_pattern})\s+"
                rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?[,]?\s+"
                rf"(?P<year>\d{{4}})\b",
                re.IGNORECASE
            ),
            re.compile(
                r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b"
            )
        )
        for pattern in patterns:
            match = pattern.search(text)
            if not match:
                continue
            values = match.groupdict()
            month = values["month"]
            month_number = (
                MONTH_NUMBERS[month.casefold()]
                if not month.isdigit() else int(month)
            )
            try:
                return date(
                    int(values["year"]), month_number, int(values["day"])
                ).isoformat()
            except ValueError:
                return None
        return None

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token for token in re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
            if len(token) > 1 and token not in ENGLISH_STOP_WORDS
        }

    @classmethod
    def _relevance_score(cls, query: str, candidate: str) -> float:
        query_text = " ".join(query.casefold().split())
        candidate_text = " ".join(candidate.casefold().split())
        if not query_text or not candidate_text:
            return 0.0

        query_tokens = cls._tokens(query)
        candidate_tokens = cls._tokens(candidate)
        if (
            len(query_tokens) >= 3
            and (query_text in candidate_text or candidate_text in query_text)
        ):
            return 1.0
        if not query_tokens or not candidate_tokens:
            return SequenceMatcher(None, query_text, candidate_text).ratio()

        overlap = len(query_tokens & candidate_tokens)
        precision = overlap / len(query_tokens)
        recall = overlap / len(candidate_tokens)
        token_f1 = (
            2 * precision * recall / (precision + recall)
            if precision + recall else 0.0
        )
        return token_f1

    def query_google_fact_check_api(
        self,
        query: str,
        api_key: Optional[str] = None,
        language_code: Optional[str] = None
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Queries Google's published fact-check index; results are not general web search.
        """
        api_key = GOOGLE_FACT_CHECK_API_KEY if api_key is None else api_key
        if not api_key:
            return [], {
                "status": "not_configured",
                "message": "Google Fact Check API is not used in local-only mode; local records were checked."
            }

        params = {
            'query': query,
            'key': api_key,
            'pageSize': 5
        }
        if language_code:
            params["languageCode"] = language_code

        try:
            response = requests.get(GOOGLE_FACT_CHECK_ENDPOINT, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            logger.warning(
                "Google Fact Check API returned HTTP %s.",
                status_code or "error"
            )
            if status_code in (400, 401, 403):
                message = (
                    f"Google Fact Check rejected the request (HTTP {status_code}). "
                    "Check that the Fact Check Tools API is enabled for the key's "
                    "Google Cloud project and that the key restrictions allow it."
                )
            elif status_code == 429:
                message = (
                    "Google Fact Check quota or rate limit was reached (HTTP 429). "
                    "Check the API quota in Google Cloud Console."
                )
            else:
                message = (
                    f"Google Fact Check returned HTTP {status_code or 'error'}; "
                    "local records were checked."
                )
            return [], {
                "status": "error",
                "http_status": status_code,
                "message": message
            }
        except requests.RequestException as exc:
            logger.warning("Google Fact Check API request failed (%s).", type(exc).__name__)
            return [], {
                "status": "error",
                "message": "Google Fact Check search is temporarily unavailable; local records were checked."
            }
        except ValueError:
            logger.warning("Google Fact Check API returned invalid JSON.")
            return [], {
                "status": "error",
                "message": "Google Fact Check search returned an invalid response; local records were checked."
            }

        claims = data.get("claims", []) if isinstance(data, dict) else None
        if not isinstance(claims, list):
            logger.warning("Google Fact Check API response did not contain a claims list.")
            return [], {
                "status": "error",
                "message": "Google Fact Check search returned an invalid response; local records were checked."
            }

        parsed = []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            claim_text = claim.get("text", "")
            reviews = claim.get("claimReview", [])
            if not isinstance(reviews, list):
                continue
            for review in reviews:
                if not isinstance(review, dict):
                    continue
                rating = str(review.get("textualRating", "")).strip()
                normalized_rating = rating.casefold()
                if re.search(r"\bnot\b.{0,20}\b(true|false|misleading|wrong|incorrect|accurate)\b", normalized_rating):
                    verdict = "Disputed"
                elif any(term in normalized_rating for term in ("false", "misleading", "scam", "fabricated", "incorrect", "wrong")):
                    verdict = "False"
                elif any(term in normalized_rating for term in ("true", "correct", "accurate")):
                    verdict = "True"
                elif any(term in normalized_rating for term in ("half", "mixed", "disputed", "context")):
                    verdict = "Disputed"
                else:
                    verdict = "Unverified"

                similarity = self._relevance_score(query, claim_text)
                parsed.append({
                    "claim": claim_text,
                    "verdict": verdict,
                    "publisher": review.get("publisher", {}).get("name", "Fact-check publisher"),
                    "rating": rating or "Unrated",
                    "url": review.get("url", ""),
                    "review_date": review.get("reviewDate", ""),
                    "language": review.get("languageCode", ""),
                    "similarity_score": round(similarity, 3),
                    "source": "Google Fact Check Tools"
                })

        parsed.sort(key=lambda result: result["similarity_score"], reverse=True)
        return parsed, {
            "status": "success",
            "message": (
                f"Google Fact Check search returned {len(parsed)} review(s)."
                if parsed else "Google Fact Check found no published reviews for this query."
            )
        }

    def find_matches(
        self,
        query: str,
        api_key: Optional[str] = None,
        language_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Combines relevant local and published Google fact-check results.
        """
        local_results = self.search_local_db(query, top_k=3)
        api_results, external_lookup = self.query_google_fact_check_api(
            query, api_key=api_key, language_code=language_code
        )
        combined = api_results + local_results
        combined = [
            item for item in combined
            if item.get('similarity_score', 0) >= MIN_MATCH_SCORE
        ]
        combined.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)

        date_conflict_match = next(
            (item for item in local_results if item.get("date_mismatch")),
            None
        )
        top_match = date_conflict_match or (combined[0] if combined else None)

        return {
            "has_match": top_match is not None,
            "top_match": top_match,
            "all_matches": combined[:5],
            "external_lookup": external_lookup
        }

fact_check_engine = FactCheckSearchEngine()
