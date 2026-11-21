import unittest
import os
import time
import threading
from pathlib import Path
import xml.etree.ElementTree as ET
import sys

# Add project root to path so we can import core.state_manager
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.state_manager import StateManager

class TestStateManager(unittest.TestCase):
    def setUp(self):
        self.test_xml = Path("test-cache-state.xml")
        if self.test_xml.exists():
            try: self.test_xml.unlink()
            except: pass
        
    def tearDown(self):
        if self.test_xml.exists():
            try: self.test_xml.unlink()
            except: pass

    def test_missing_file_provisioning(self):
        """Tier 1.5: Missing file boot provisions defaults"""
        sm = StateManager(config_file=str(self.test_xml))
        self.assertTrue(self.test_xml.exists())
        self.assertEqual(sm.get_current_mood(), "neutral")
        # Fixed expected value based on state_manager.py: FRIEND(+)
        self.assertEqual(sm.get_relationship_mode(), "FRIEND(+)")

    def test_utf8_fidelity(self):
        """Tier 1.2: Round-trip fidelity with special mood strings (Unicode/Typo checks)"""
        sm = StateManager(config_file=str(self.test_xml))
        moods = ['loathing dispare', 'Blinding Rage', 'Horney', 'Vulgar Humor', 'Mélancholy', '🔥 Rage']
        for mood in moods:
            sm.update_mood(mood)
            # Re-read from disk with a fresh instance to force file parse
            sm2 = StateManager(config_file=str(self.test_xml))
            self.assertEqual(sm2.get_current_mood(), mood)

    def test_event_history_append(self):
        """Tier 1.3: Event history appends correctly without truncation"""
        sm = StateManager(config_file=str(self.test_xml))
        sm.update_mood("calm")
        sm.update_mood("excited")
        
        # Verify directly in XML
        tree = ET.parse(self.test_xml)
        history = tree.getroot().find("history")
        events = history.findall("event")
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[-1].get("to"), "excited")
        self.assertEqual(events[-2].get("to"), "calm")

    def test_corrupted_file_recovery(self):
        """Tier 1.6: Corrupted file triggers recovery (defaults)"""
        self.test_xml.write_text("THIS IS NOT XML <GARBAGE>", encoding="utf-8")
        sm = StateManager(config_file=str(self.test_xml))
        self.assertEqual(sm.get_current_mood(), "neutral")
        self.assertTrue(self.test_xml.exists())

    def test_atomic_write_simulation(self):
        """Tier 1.1: Verify write safety under transient read lock"""
        sm = StateManager(config_file=str(self.test_xml))
        sm.update_mood("Initial")
        
        # We use a thread to release the lock after a short delay.
        # This proves the StateManager's retry logic works for transient locks.
        def hold_lock():
            with open(self.test_xml, "rb") as f:
                time.sleep(0.5) 
        
        threading.Thread(target=hold_lock).start()
        time.sleep(0.1) # Give thread time to grab handle
        
        try:
            sm.update_mood("New Mood")
            success = True
        except Exception as e:
            success = False
            print(f"Atomic write failure: {e}")
        
        self.assertTrue(success, "StateManager failed to handle transient lock")
        
        # Verify the write actually happened
        sm2 = StateManager(config_file=str(self.test_xml))
        self.assertEqual(sm2.get_current_mood(), "New Mood")

    def test_concurrency_stress(self):
        """Tier 1.4: Concurrent read during write stress test"""
        sm = StateManager(config_file=str(self.test_xml))
        sm.update_mood("Starter")
        stop_event = threading.Event()
        errors = []

        def reader_loop():
            while not stop_event.is_set():
                try:
                    # Fresh instance to force disk read
                    reader = StateManager(config_file=str(self.test_xml))
                    _ = reader.get_current_mood()
                except Exception as e:
                    errors.append(f"Reader error: {e}")
                time.sleep(0.001)

        def writer_loop():
            for i in range(50):
                try:
                    sm.update_mood(f"Mood {i}")
                except Exception as e:
                    errors.append(f"Writer error: {e}")
                time.sleep(0.001)

        rt = threading.Thread(target=reader_loop)
        wt = threading.Thread(target=writer_loop)
        
        rt.start()
        wt.start()
        
        wt.join()
        stop_event.set()
        rt.join()
        
        self.assertEqual(len(errors), 0, f"Concurrency errors found: {errors}")

if __name__ == "__main__":
    unittest.main()
