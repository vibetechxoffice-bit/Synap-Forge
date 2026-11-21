import xml.etree.ElementTree as ET
from pathlib import Path
import os
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class StateManager:
    """
    Centralized State Manager for SYNAP-FORGE.
    Handles persistent state via cache-state.xml.
    """
    def __init__(self, config_file: Optional[str] = None):
        # Default path to the cache-state.xml in the project artifacts or local app data
        # Based on user context, it's at C:/Users/User/AppData/Local/Google/AndroidStudio2025.3.4/projects/synap_installer.d60f6eb/cache-state.xml
        self.config_file = Path(config_file or os.getenv("STATE_CACHE_PATH", "cache-state.xml"))
        self.root = None
        self._load_state()

    def _load_state(self):
        """Load state from XML with Windows-safe reading retries."""
        if not self.config_file.exists():
            logger.info(f"State file {self.config_file} not found. Initializing defaults.")
            self._initialize_default_config()
        else:
            # Retry loop for reading
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with open(self.config_file, 'rb') as f:
                        content = f.read()
                    
                    if not content:
                        if attempt < max_retries - 1:
                            time.sleep(0.01)
                            continue
                        raise ValueError("State file is empty")

                    self.root = ET.fromstring(content)
                    if self.root.tag != "synapse_state":
                         logger.warning("Invalid root tag in state file. Re-initializing.")
                         self._initialize_default_config()
                    return # Success
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(0.01)
                        continue
                    
                    logger.error(f"Error parsing state file: {e}. Resetting to default.")
                    self._initialize_default_config()
                    break

    def _write_state(self):
        """Write current state back to XML atomically with Windows-safe retries and fallbacks."""
        if self.root is None:
            return
        
        try:
            tree = ET.ElementTree(self.root)
            # Update last_updated timestamp
            last_updated = self.root.find("last_updated")
            if last_updated is None:
                last_updated = ET.SubElement(self.root, "last_updated")
            last_updated.text = datetime.now().isoformat()

            # Atomic write-then-rename pattern
            temp_file = self.config_file.with_suffix(".tmp")
            with open(temp_file, "wb") as f:
                f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
                tree.write(f, encoding="utf-8", xml_declaration=False)
            
            # Windows-safe atomic replace with retry loop
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    os.replace(temp_file, self.config_file)
                    return
                except (PermissionError, OSError):
                    if attempt < max_retries - 1:
                        time.sleep(0.01)
                        continue
                    
                    backup = self.config_file.with_suffix(".bak")
                    try:
                        if self.config_file.exists():
                            if backup.exists():
                                os.remove(backup)
                            os.rename(self.config_file, backup)
                        os.rename(temp_file, self.config_file)
                        try: os.remove(backup)
                        except: pass
                        return
                    except Exception as fallback_err:
                        logger.error(f"Fallback write failed: {fallback_err}")
                        break
        except Exception as e:
            logger.error(f"Failed to write state to {self.config_file}: {e}")

    def _initialize_default_config(self):
        """Create a default XML state structure."""
        self.root = ET.Element("synapse_state")
        
        ET.SubElement(self.root, "current_mood").text = "neutral"
        ET.SubElement(self.root, "time_period").text = "daylight"
        ET.SubElement(self.root, "relationship_mode").text = "FRIEND(+)"
        ET.SubElement(self.root, "behavior_mode").text = "NORMAL"

        thresholds = ET.SubElement(self.root, "emotional_thresholds")
        ET.SubElement(thresholds, "valence_high").text = os.getenv("MIDAS_VALENCE_HIGH", "0.7")
        ET.SubElement(thresholds, "valence_low").text = os.getenv("MIDASE_VALENCE_LOW", "0.3")
        ET.SubElement(thresholds, "arousal_high").text = os.getenv("MIDAS_AROUSAL_HIGH", "0.7")
        ET.SubElement(thresholds, "arousal_low").text = os.getenv("MIDAS_AROUSAL_LOW", "0.3")

        traits = ET.SubElement(self.root, "active_traits")
        # Default traits can be added here if needed

        history = ET.SubElement(self.root, "history")
        
        self.root.append(ET.Element("upulse_state"))
        
        self._write_state()

    def get_threshold(self, key: str, default: float = 0.5) -> float:
        """Retrieve a threshold with XML lookup and ENV fallback."""
        elem = self.root.find("emotional_thresholds")
        if elem is not None:
            val = elem.findtext(key)
            if val is not None:
                try:
                    return float(val)
                except ValueError:
                    pass
        
        # ENV Fallback (e.g., valence_high -> MIDAS_VALENCE_HIGH)
        env_key = f"MIDAS_{key.upper()}"
        env_val = os.getenv(env_key)
        if env_val is not None:
            try:
                return float(env_val)
            except ValueError:
                pass
        
        return default

    def get_thresholds(self) -> Dict[str, float]:
        """Retrieve all emotional thresholds."""
        return {
            "valence_high": self.get_threshold("valence_high", 0.7),
            "valence_low": self.get_threshold("valence_low", 0.3),
            "arousal_high": self.get_threshold("arousal_high", 0.7),
            "arousal_low": self.get_threshold("arousal_low", 0.3)
        }

    def get_current_mood(self) -> str:
        return self.root.findtext("current_mood", "neutral")

    def update_mood(self, mood: str):
        elem = self.root.find("current_mood")
        if elem is None:
            elem = ET.SubElement(self.root, "current_mood")
        
        old_mood = elem.text
        if old_mood != mood:
            elem.text = mood
            self._log_history("mood_change", {"from": old_mood, "to": mood})
            self._write_state()

    def get_relationship_mode(self) -> str:
        return self.root.findtext("relationship_mode", "FRIEND(+)")

    def update_relationship_mode(self, mode: str):
        elem = self.root.find("relationship_mode")
        if elem is None:
            elem = ET.SubElement(self.root, "relationship_mode")
        elem.text = mode
        self._write_state()

    def get_temporal_context(self) -> Dict[str, Any]:
        return {
            "period": self.root.findtext("time_period", "daylight"),
            "hour": datetime.now().hour
        }

    def update_temporal_context(self, period: str):
        elem = self.root.find("time_period")
        if elem is None:
            elem = ET.SubElement(self.root, "time_period")
        elem.text = period
        self._write_state()

    def get_full_state(self) -> Dict[str, Any]:
        """Returns a snapshot of the full state for prompt injection."""
        thresholds = self.get_thresholds()
        return {
            "mood": self.get_current_mood(),
            "time_period": self.root.findtext("time_period", "daylight"),
            "relationship_mode": self.get_relationship_mode(),
            "behavior_mode": self.root.findtext("behavior_mode", "NORMAL"),
            "high_valence": thresholds["valence_high"],
            "low_valence": thresholds["valence_low"],
            "high_arousal": thresholds["arousal_high"],
            "low_arousal": thresholds["arousal_low"]
        }

    def _log_history(self, event_type: str, details: Dict[str, Any]):
        history = self.root.find("history")
        if history is None:
            history = ET.SubElement(self.root, "history")
        
        event = ET.SubElement(history, "event")
        event.set("timestamp", datetime.now().isoformat())
        event.set("type", event_type)
        for k, v in details.items():
            event.set(k, str(v))
        
        # Keep history manageable (last 50 events)
        if len(history) > 50:
            history.remove(history[0])
