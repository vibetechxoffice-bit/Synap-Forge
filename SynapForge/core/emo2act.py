"""
Emotion-to-Action Mapping (Emo2Act)
===================================
Dynamic refusal and action engine based on intent and emotional triggers.
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class Emo2ActEngine:
    def __init__(self, state_manager: Optional[Any] = None):
        self.state_manager = state_manager
        # Define refusal patterns based on VAD and triggers
        self.refusal_patterns = [
            {
                "condition": self._check_hostile,
                "action": "REFUSE_HOSTILE",
                "template": "I cannot engage with that level of hostility. Let's take a breath."
            },
            {
                "condition": self._check_harm,
                "action": "REFUSE_HARM",
                "template": "I'm concerned about what you're saying. Please reach out to a professional."
            },
            {
                "condition": self._check_vulgar,
                "action": "REFUSE_VULGAR",
                "template": "I'm not in the mood for that kind of language right now."
            }
        ]

    def _get_thresholds(self):
        if self.state_manager:
            return self.state_manager.get_thresholds()
        return {"valence_high": 0.7, "valence_low": 0.3, "arousal_high": 0.7, "arousal_low": 0.3}

    def _check_hostile(self, vad, triggers):
        thresh = self._get_thresholds()
        return vad["arousal"] > thresh["arousal_high"] and "rage" in triggers

    def _check_harm(self, vad, triggers):
        thresh = self._get_thresholds()
        return vad["valence"] < thresh["valence_low"] and "suicide" in triggers

    def _check_vulgar(self, vad, triggers):
        thresh = self._get_thresholds()
        # Use triggers detected by MIDAS (which include ADULT_CONTENT)
        return len(triggers) > 0 and vad["arousal"] > thresh["arousal_high"]

    def evaluate(self, text: str, vad: Dict[str, float], triggers: List[str]) -> Optional[Dict[str, Any]]:
        """Evaluate text and emotional signature for potential actions/refusals."""
        for pattern in self.refusal_patterns:
            if pattern["condition"](vad, triggers):
                logger.info(f"[Emo2Act] Pattern matched: {pattern['action']}")
                return {
                    "action": pattern["action"],
                    "response": pattern["template"]
                }
        return None

    def map_mood_to_action(self, mood: str) -> str:
        """Map a detected mood to a behavioral directive."""
        mappings = {
            "Blinding Rage": "Respond with cold precision. Do not escalate.",
            "exstatic": "Respond with high energy and creative flair.",
            "loathing dispare": "Respond with deep empathy and gentle support.",
            "Horney": "Redirect conversation to a more productive topic.",
            "Vulagar Humor": "Maintain boundaries while acknowledging the humor."
        }
        return mappings.get(mood, "Respond naturally based on your persona.")
