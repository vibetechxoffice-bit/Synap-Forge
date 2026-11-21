"""
QBIT Gateway - State-Aware Communication
========================================
Handles communication with external systems and LLMs with state injection.
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class QbitGateway:
    def __init__(self, state_manager: Optional[Any] = None, llm_client: Optional[Any] = None):
        self.state_manager = state_manager
        self.llm_client = llm_client

    async def send_message(self, user_input: str) -> dict:
        """Inject state into prompt and dispatch to LLM."""
        if not self.state_manager:
            # Fallback if no state manager
            if self.llm_client:
                response = await self.llm_client.prompt(user_input)
                return {"response": response}
            return {"error": "No LLM client available"}

        mood_data = self.state_manager.get_full_state()
        
        # Build state-aware prompt template
        prompt_template = f"""
[CONTEXT]
Time Period: {mood_data.get('time_period', 'unknown')}
Relationship Mode: {mood_data.get('relationship_mode', 'neutral')}
Behavior Mode: {mood_data.get('behavior_mode', 'NORMAL')}

[Mood Detection Thresholds]:
High Valence: {mood_data.get('high_valence', 0.7)}
Low Valence: {mood_data.get('low_valence', 0.3)}

{user_input}
"""
        if self.llm_client and hasattr(self.llm_client, 'prompt'):
            response = await self.llm_client.prompt(prompt_template)
        else:
            # Mock or log if no client
            logger.warning("No LLM client configured for QbitGateway. Using mock response.")
            response = f"[MOCK RESPONSE TO: {user_input}]"

        return {
            "response": response,
            "state_after_interaction": mood_data
        }
