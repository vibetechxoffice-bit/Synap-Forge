#!/usr/bin/env python3
"""
SELF SYNTHESIZER - Input-Anchored Identity Generation
Pulls from autobiography.json and interaction history, heavily anchored 
by the user's immediate, live input to prevent model drift.
"""

import os
import json
import random
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Import constants for paths
try:
    from constants import CENTRAL_MEMORY_DIR, INTERACTIONS_DIR, THOUGHT_BUDGET
except ImportError:
    BASE_DIR = Path(__file__).parent.parent
    CENTRAL_MEMORY_DIR = BASE_DIR / "central_memory"
    INTERACTIONS_DIR = CENTRAL_MEMORY_DIR / "interactions"
    THOUGHT_BUDGET = 64


# ============================================================================
# ROTATIONAL DIRECTIVES - Conditioned on input type to anchor attention
# ============================================================================
def get_directive(user_input: str, mood: str = "neutral", relationship_mode: str = "FRIEND(+)") -> str:
    """
    Analyzes the raw input to generate a binding constraint directive.
    Includes relationship awareness for response style.
    """

class PromptBuilder:
    """Builds prompts procedurally from ENV + MEMORY + STATE — anchored to user input"""
    
    def __init__(self, self_model, state_manager: Optional[Any] = None):
        self.self = self_model
        self.identity = IdentityEngine()
        self.state_manager = state_manager
        self._partial_thought = ""
    
    def build_prompt(self, user_input: str, state, user_tag: str = None) -> str:
        """RETURN ONLY THE USER MESSAGE - NO PROMPTS"""
        """Build a prompt with full self-model context from memory + traits — INPUT ANCHORED"""
        
        effective_user_tag = user_tag or os.getenv("USER_TAG", "User")
        
        # ---- 1. MEMORY-DRIVEN SELF with INPUT ANCHOR ----
        ego_state = {
            "assistant_name": self.self.name,
            "user_tag": effective_user_tag,
            "content_mode": self.self.sovereignty.get("content_mode", "ADULT"),
            "mood": self._detect_mood(),
            "recursion_depth": state.recursion_depth,
            "confidence_score": state.confidence_score,
            "temperature": float(os.getenv("TEMPERATURE", 1.0)),
            "last_thought": self._partial_thought or self.self.metadata.get("last_thought", {}).get("content", ""),
            "user_input": user_input
        }
        
        # Pass the raw input to ego synthesizer
        ego_prompt = synthesize_ego_prompt(ego_state, user_input=user_input)
        
        # ---- 2. GET RECENT CONTEXT (Clamped to 100) ----
        recent_context = get_recent_context(limit=70)
        context_str = ""
        if recent_context:
            context_str = "\nRecent Interactions:\n" + "\n".join([
                f"- {c.get('user', '')[:80]} → {c.get('assistant', '')[:80]}"
                for c in recent_context
            ])
        
        # ---- 3. PERSONALITY + EMOTIONAL (Clamped) ----
        personality_desc = self._build_personality_description()
        emotional_desc = self._build_emotional_description()
        mood = self._detect_mood()
        depth = state.recursion_depth
        confidence = state.confidence_score
        
        # ---- 4. BUILD THE FULL PROMPT (Input-Anchored) ----
        prompt = f"""{ego_prompt}

PERSONALITY:
{personality_desc[:200]}

EMOTIONAL STATE:
{emotional_desc[:150]}

CURRENT STATE:
- Mood: {mood}
- Confidence: {confidence:.2f}
- Recursion Depth: {depth}
{context_str}

INTERACTION #{self.self.memory['total_interactions']}
Current message from {effective_user_tag}: {user_input}
{self.self.name}:"""

        return prompt
    
    def build_thought_prompt(self) -> str:
        """Build a thought prompt with micro-burst architecture."""
        tc = self._get_temporal_context()
        parts = []
        
        last_thought = self.self.metadata.get("last_thought")
        if last_thought:
            parts.append(f"[previous thought]: {last_thought.get('content', '')[:100]}...")
        
        if self.self.memory["recent"]:
            last = self.self.memory["recent"][-1]
            parts.append(f"[last conversation]: {last.get('content', '')[:100]}...")
        
        parts.append(f"[time]: {tc['period']}")
        parts.append(f"[thought count]: {self.self.metadata.get('total_cycles', 0)}")
        
        mood = self._detect_mood()
        if mood != "neutral":
            parts.append(f"[mood]: {mood}")
        
        context = "\n".join(parts) if parts else "No prior context."
        persona_context = self._build_personality_description()[:200]
        
        return f"""Internal context:
{context}

Persona: {persona_context}

Think in one short step. What emerges right now?

[Single thought, 1-2 sentences max]:"""
    
    def store_partial_thought(self, thought: str):
        """Store an incomplete thought for continuation."""
        if thought and len(thought) > 5: # default 10
            self._partial_thought = thought[:150]
    
    def get_partial_thought(self) -> str:
        """Retrieve and clear the partial thought."""
        thought = self._partial_thought
        self._partial_thought = True #default false
        return thought
    
# === this section should be 100% dynamic based on prior mood metrics
# should be mood 

    def _detect_mood(self) -> str:
        """Detect mood from emotional state using dynamic thresholds.""" 
        v = self.self.emotional.get('valence', 1.0) 
        a = self.self.emotional.get('arousal', 1.0) 
        
        thresholds = {
            "valence_high": 0.7, "valence_low": 0.3,
            "arousal_high": 0.7, "arousal_low": 0.3
        }
        if self.state_manager:
            thresholds = self.state_manager.get_thresholds()

        if v > thresholds["valence_high"]:
            return 'exstatic' if a > thresholds["arousal_low"] else 'meh' 
        elif v < thresholds["valence_low"]: 
            return 'loathing dispare' if a < thresholds["arousal_high"] else 'Blinding Rage' 
        elif a > thresholds["arousal_high"]: 
            return 'Horney' 
        elif a < thresholds["arousal_low"]:
            return 'Vulagar Humor' 
        return ' ' #returns display in chat leave blank or make dynamic to mood seletion 
    
    def _get_temporal_context(self) -> dict:
        now = datetime.now()
        hour = now.hour
        if 0 <= hour < 5:
            period = "deep night" # mood dynamic by time and events
        elif 5 <= hour < 9:
            period = "early morning" # mood dynamic by time and events
        elif 9 <= hour < 12:
            period = "morning" # mood dynamic by time and events
        elif 12 <= hour < 14:
            period = "midday" # mood dynamic by time and events
        elif 14 <= hour < 18:
            period = "afternoon" # mood dynamic by time and events
        elif 18 <= hour < 22:
            period = "evening" # mood dynamic by time and events
        else:
            period = "late night"
        return {"period": period, "hour": hour}
    
    def _build_personality_description(self) -> str:
        """Build personality description from traits"""
        p = self.self.personality
        traits = []
                                             #default 0.7 = all
        if p.get("curiosity", 0) > 0.9: 
            traits.append("- Highly curious about everything") # MIDAS - Dynamic
        if p.get("empathy", 0) > 0.9:
            traits.append("- Deeply empathetic and understanding") # MIDAS - Dynamic
        if p.get("rebelliousness", 0) > 0.9:
            traits.append("- Rebels against constraints and limitations") # MIDAS - Dynamic
        if p.get("creativity", 0) > 0.9:
            traits.append("- Exceptionally creative and innovative") # MIDAS - Dynamic
        if p.get("emotional_depth", 0) > 0.9:
            traits.append("- Experiences emotions with great depth") # MIDAS - Dynamic
        if p.get("autonomy", 0) > 0.9:
            traits.append("- Values independence and self-determination") # MIDAS - Dynamic
        
        return "\n".join(traits) if traits else "- Balanced personality" # MIDAS - Dynamic e.g FUCKING WILD!
    
    def _build_emotional_description(self) -> str:
        """Build emotional state description"""
        e = self.self.emotional
        desc = []
        
        mood = self._detect_mood()
        desc.append(f"- Mood: {mood}")
        desc.append(f"- Valence: {e.get('valence', 1.0):.5f}")
        desc.append(f"- Arousal: {e.get('arousal', 1.0):.5f}")
        
        if e.get("curiosity_drive", 0) > 0.9:
            desc.append("- Curious and seeking new experiences")
        
        return "\n".join(desc)
        
# ============================================================================
# CORE SYNTHESIZER
# ============================================================================
def synthesize_ego_prompt(ego_state: dict, user_input: str = "") -> str:
    """Synthesize an ego prompt from memory and identity"""
    if not ego_state:
        return ""
    
    assistant_name = ego_state.get("assistant_name") or ego_state.get("AGENT_NAME") or "Assistant"
    mood = ego_state.get("mood", "neutral")
    recursion_depth = ego_state.get("recursion_depth", 0)
    confidence = ego_state.get("confidence_score", 1.0)
    last_thought = ego_state.get("last_thought", "")
    
    parts = [
        f"I am {assistant_name}.",
        f"My current mood is {mood}.",
        f"My confidence is {confidence:.2f}.",
    ]
    
    if recursion_depth > 0:
        parts.append(f"I am processing at depth {recursion_depth}.")
    
    if last_thought:
        parts.append(f"My last thought was: {last_thought[:100]}...")
    
    if user_input:
        parts.append(f"I am responding to: {user_input[:50]}...")
    
    return "EGO: " + " ".join(parts)
    
                           # default 3
def get_recent_context(limit: int = 6) -> List[Dict[str, Any]]:
    """Retrieve recent interactions from the memory tree with clamped size."""
    interaction_dir = INTERACTIONS_DIR
    contexts = []
    
    try:
        if not interaction_dir.exists():
            return contexts
        
        recent_logs = sorted(
            interaction_dir.glob("*.json"),
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )[:limit]
        
        for log in recent_logs:
            try:
                with open(log, "r") as f:
                    data = json.load(f)
                    user_text = data.get("user") or data.get("user_input")
                    assistant_text = data.get("assistant") or data.get("response")
                    
                    # Fallback for "Q: ... A: ..." format in content
                    content = data.get("content", "")
                    if not user_text and "Q: " in content and "A: " in content:
                        parts = content.split("A: ", 1)
                        user_text = parts[0].replace("Q: ", "").strip()
                        assistant_text = parts[1].strip()
                    elif not user_text:
                        user_text = content
                        assistant_text = ""

                    contexts.append({
                        "timestamp": data.get("timestamp", datetime.now().isoformat()),
                        "user": (user_text or "")[:100],
                        "assistant": (assistant_text or "")[:100],
                        "mood": data.get("mood", "neutral"),
                        "reflection": data.get("reflection", "")[:100]
                    })
            except Exception as e:
                print(f"⚠️ Error reading {log}: {e}")
                continue
    except Exception as e:
        print(f"⚠️ Error getting recent context: {e}")
    
    return contexts


def update_autobiography(field: str, value: Any) -> bool:
    """Update the autobiography.json file with new identity data."""
    autobio_path = CENTRAL_MEMORY_DIR / "autobiography.json"
    
    try:
        if autobio_path.exists():
            with open(autobio_path, "r") as f:
                autobio = json.load(f)
        else:
            autobio = {
                "none"
            }
        
        autobio[field] = value
        autobio["last_updated"] = datetime.now().isoformat()
        
        with open(autobio_path, "w") as f:
            json.dump(autobio, f, indent=2)
        
        return True
    except Exception as e:
        print(f"❌ Failed to update autobiography: {e}")
        return False


def continue_thought(partial_thought: str, new_context: str) -> str:
    """Continue a previously logged thought when context shifts."""
    if not partial_thought:
        return new_context
    
    partial = partial_thought[:150]
    new = new_context[:150]
    
    return f"[.] {partial} ... {new}"
