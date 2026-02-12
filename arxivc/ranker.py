from typing import List, Dict, Any, Counter
import math
import re
from . import config

# Minimal stopword list
STOPWORDS = {
    'the', 'of', 'and', 'in', 'to', 'a', 'is', 'for', 'with', 'on', 'as', 'by', 'that', 'are', 'from',
    'this', 'we', 'an', 'at', 'be', 'which', 'or', 'it', 'can', 'has', 'have', 'not', 'but', 'their',
    'measurement', 'measurements', 'study', 'results', 'data', 'model', 'analysis', 'using', 'observations'
}

class SmartRanker:
    def __init__(self):
        self.profile = Counter()
        self.idf = {}
        self.total_docs = 0

    def tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        # Lowercase and remove punctuation
        text = re.sub(r'[^\w\s]', '', text.lower())
        tokens = text.split()
        return [t for t in tokens if t not in STOPWORDS and len(t) > 2]

    def train(self, liked_papers: List[Dict[str, Any]]):
        """
        Builds a user profile from liked papers.
        Ideally we would use TF-IDF, but for a small set,
        simple Term Frequency in liked papers is a strong signal.
        """
        self.profile = Counter()
        for p in liked_papers:
            text = (p.get('title', '') or "") + " " + (p.get('summary', '') or "")
            tokens = self.tokenize(text)
            self.profile.update(tokens)
        
        # Normalize
        total = sum(self.profile.values())
        if total > 0:
            for word in self.profile:
                self.profile[word] /= total

    def score(self, paper: Dict[str, Any]) -> float:
        text = (paper.get('title', '') or "") + " " + (paper.get('summary', '') or "")
        tokens = self.tokenize(text)
        paper_counts = Counter(tokens)
        
        score = 0.0
        for word, count in paper_counts.items():
            if word in self.profile:
                # Add weight from profile
                score += count * self.profile[word]
        
        # Boost by explicit keyword matches from config (hybrid approach)
        keyword_boost = 0
        text_lower = text.lower()
        for kw in config.KEYWORDS:
            if kw.lower() in text_lower:
                keyword_boost += 1.0 # Significant boost per keyword
                
        return score * 10.0 + keyword_boost


# Singleton instance
ranker_instance = SmartRanker()

def train_ranker(liked_papers: List[Dict[str, Any]]):
    ranker_instance.train(liked_papers)

def rank_papers(papers: List[Dict[str, Any]], use_smart_rank: bool = False) -> List[Dict[str, Any]]:
    """
    Sorts papers.
    If use_smart_rank is True, uses the trained SmartRanker.
    Otherwise, uses the simple keyword counting.
    """
    items = []
    
    for p in papers:
        # Check simple keyword score for display badge
        kw_score = p.get("match_score")
        if kw_score is None:
            kw_score = 0
            text = ((p.get('title') or "") + " " + (p.get('summary') or "")).lower()
            for kw in config.KEYWORDS:
                if kw.lower() in text:
                    kw_score += 1
                
        p_copy = p.copy()
        p_copy['score'] = kw_score # Keep the badge score as simple count
        
        if use_smart_rank:
            smart_score = ranker_instance.score(p)
            p_copy['_sort_score'] = smart_score
        else:
            p_copy['_sort_score'] = kw_score

        items.append(p_copy)
    
    # Sort by score desc, then by date desc
    items.sort(key=lambda x: (x.get('_sort_score', 0), x['published']), reverse=True)
    return items
