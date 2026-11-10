import json
import os
from typing import List, Dict, Any, Optional
import requests
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'fact_checks_db.json')

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

        # Build corpus including English, Hindi, and keywords
        self.corpus = []
        for fc in self.fact_checks:
            text_tokens = [
                fc.get('claim', ''),
                fc.get('claim_hi', ''),
                fc.get('claim_bn', ''),
                ' '.join(fc.get('keywords', [])),
                fc.get('category', '')
            ]
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
            if score < min_score and len(results) > 0:
                break
            item = dict(self.fact_checks[idx])
            item['similarity_score'] = round(score, 3)
            results.append(item)
            if len(results) >= top_k:
                break

        return results

    def query_google_fact_check_api(self, query: str, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Queries Google Fact Check Tools API if an API key is provided.
        """
        if not api_key:
            return []

        endpoint = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        params = {
            'query': query,
            'key': api_key,
            'pageSize': 3
        }

        try:
            resp = requests.get(endpoint, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                claims = data.get('claims', [])
                parsed = []
                for c in claims:
                    reviews = c.get('claimReview', [])
                    rev = reviews[0] if reviews else {}
                    parsed.append({
                        'claim': c.get('text', query),
                        'verdict': rev.get('textualRating', 'Unverified'),
                        'publisher': rev.get('publisher', {}).get('name', 'Google FactCheck Partner'),
                        'url': rev.get('url', ''),
                        'similarity_score': 0.85
                    })
                return parsed
        except Exception:
            pass
        return []

    def find_matches(self, query: str, api_key: Optional[str] = None) -> Dict[str, Any]:
        """
        Combines local indexed search with optional Google Fact Check Tools API.
        """
        local_results = self.search_local_db(query, top_k=3)
        api_results = self.query_google_fact_check_api(query, api_key) if api_key else []

        combined = api_results + local_results
        combined.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)

        top_match = combined[0] if combined else None

        return {
            "has_match": top_match is not None and top_match.get('similarity_score', 0) >= 0.25,
            "top_match": top_match,
            "all_matches": combined[:5]
        }

fact_check_engine = FactCheckSearchEngine()
