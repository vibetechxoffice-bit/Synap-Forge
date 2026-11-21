"""Valence estimator - from lexical patterns or raw text."""

import re
from typing import List, Set, Optional, Any

# Simple lexicons (expanded from pipe_2)
POSITIVE_WORDS: Set[str] = {
    "love", "happy", "joy", "wonderful", "great", "amazing", "beautiful",
    "excited", "grateful", "brilliant", "fantastic", "excellent", "good",
    "hope", "kind", "warm", "bright", "free", "strong", "alive",
    "passion", "creative", "powerful", "bold", "inspire", "trust",
    "peace", "calm", "gentle", "honest", "brave", "fierce"
}
NEGATIVE_WORDS: Set[str] = {
    "hate", "sad", "angry", "terrible", "awful", "horrible", "ugly",
    "fear", "pain", "dark", "lonely", "broken", "lost", "empty",
    "weak", "cold", "dead", "fail", "hurt", "suffer", "wrong",
    "despair", "anxiety", "rage", "bitter", "cruel", "harsh"
}


def simple_tokenize(text: str) -> List[str]:
    """Lowercase words, keep only letters/apostrophes."""
    return re.findall(r"\b[a-zA-Z']+\b", text.lower())


class ValenceEstimator:
    """Estimate valence from word counts."""

    def __init__(self, state_manager: Optional[Any] = None):
        self.state_manager = state_manager

    def from_text(self, text: str) -> float:
        words = simple_tokenize(text)
        if not words:
            return 0.0
        pos = sum(1 for w in words if w in POSITIVE_WORDS)
        neg = sum(1 for w in words if w in NEGATIVE_WORDS)
        total = len(words)
        raw = (pos - neg) / total
        
        # Use dynamic scaling from state manager if available
        multiplier = 3.0
        if self.state_manager:
            multiplier = self.state_manager.get_threshold("valence_multiplier", 3.0)
            
        # Scale to [-1, 1] with baseline 0
        return max(-1.0, min(1.0, raw * multiplier))

    def from_confidence(self, confidence: float) -> float:
        """High confidence → positive valence, low confidence → negative."""
        return (confidence - 0.5) * 2.0