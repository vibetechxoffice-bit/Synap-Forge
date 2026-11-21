import requests
import time
import sys
import json
from pathlib import Path

def wait_for_launcher_stage(stage_name, expected_statuses=["active", "verified"], timeout=180):
    project_root = Path(__file__).resolve().parent.parent
    stages_file = project_root / "state" / "stages.jsonl"
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        if stages_file.exists():
            try:
                with open(stages_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip(): continue
                        data = json.loads(line)
                        if data.get("stage") == stage_name and data.get("status") in expected_statuses:
                            return True
            except Exception:
                pass
        time.sleep(1)
    return False

def test_integration():
    failures = []
    print("\n" + "="*60)
    print("      SYNAP-FORGE TIER 2: INTEGRATION BOOT TEST")
    print("="*60)

    # 1. Check Identity Gate with Polling
    print("\n[STEP 1] Waiting for Identity Gate...")
    project_root = Path(__file__).resolve().parent.parent
    possible_cert_paths = [
        project_root / "state" / "identity_lock.json",
        project_root / "launcher" / "state" / "identity_lock.json",
        Path("state/identity_lock.json")
    ]
    
    cert_found = False
    timeout = 60
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        for cert_path in possible_cert_paths:
            if cert_path.exists():
                print(f"✅ Identity Certificate found at: {cert_path}")
                cert_found = True
                break
        if cert_found:
            break
        elapsed = int(time.time() - start_time)
        if elapsed > 0 and elapsed % 10 == 0:
            print(f"   ... waiting for identity certificate ({elapsed}s/{timeout}s)")
        time.sleep(1)

    if not cert_found:
        print("❌ Identity Certificate missing! Run Genesis / Launcher Stage A first.")
        failures.append("Step 1: Identity Certificate missing")
        _finish_test(failures)
        return

    # 2. Synchronize with Stage B & Monitor LLM Bring-up (Port 11437)
    print("\n[STEP 2] Waiting for Launcher Stage B (LLM Weights Bring-up)...")
    if not wait_for_launcher_stage("B", ["active", "verified"], timeout=180):
        print("❌ Launcher did not reach Stage B within 180s timeout.")
        failures.append("Step 2: Launcher Stage B timeout")
        _finish_test(failures)
        return
    print("✅ Stage B detected in launcher log. Probing LLM Node (Port 11437)...")

    llm_online = False
    for i in range(120): # 2 minute timeout for cold start
        try:
            resp = requests.get("http://127.0.0.1:11437/v1/models", timeout=2)
            if resp.status_code == 200:
                model_data = resp.json()
                print(f"✅ LLM Node Online. Model: {model_data['data'][0]['id']}")
                llm_online = True
                break
        except:
            if i % 10 == 0 and i > 0:
                print(f"   ... still waiting ({i}s/120s)")
            time.sleep(1)
    
    if not llm_online:
        print("❌ LLM Node failed to initialize within 120s.")
        failures.append("Step 2: LLM Node timeout")
        _finish_test(failures)
        return

    # 3. Synchronize with Stage C & Monitor Synap Server (Port 11436)
    print("\n[STEP 3] Waiting for Launcher Stage C (Synap Server Bring-up)...")
    if not wait_for_launcher_stage("C", ["active", "verified"], timeout=60):
        print("❌ Launcher did not reach Stage C within 60s timeout.")
        failures.append("Step 3: Launcher Stage C timeout")
        _finish_test(failures)
        return
    print("✅ Stage C detected in launcher log. Probing Consciousness Server (Port 11436)...")

    synap_online = False
    for i in range(30):
        try:
            resp = requests.get("http://127.0.0.1:11436/health", timeout=2)
            if resp.status_code == 200:
                print("✅ Synap Server Online.")
                synap_online = True
                break
        except:
            time.sleep(1)
            
    if not synap_online:
        print("❌ Synap Server failed to bind or responded with error.")
        failures.append("Step 3: Synap Server health check failed")
        _finish_test(failures)
        return

    # 4. Verify State Sync
    print("\n[STEP 4] Verifying XML State Synchronization...")
    try:
        resp = requests.get("http://127.0.0.1:11436/status", timeout=10)
        if resp.status_code == 200:
            state = resp.json()
            print(f"✅ State Sync Verified.")
            print(f"   Active Mood: {state.get('mood')}")
            print(f"   Agent Name:  {state.get('name')}")
        else:
            print(f"❌ State endpoint returned status {resp.status_code}")
            failures.append(f"Step 4: Status code {resp.status_code}")
    except Exception as e:
        print(f"❌ Could not verify state via API: {e}")
        failures.append(f"Step 4: Exception {e}")

    _finish_test(failures)

def _finish_test(failures):
    print("\n" + "="*60)
    if failures:
        print(f"❌ INTEGRATION TEST FAILED: {len(failures)} step(s) failed:")
        for f in failures:
            print(f"   - {f}")
        print("="*60 + "\n")
        sys.exit(1)
    else:
        print("      INTEGRATION TEST COMPLETE: SYSTEM NOMINAL")
        print("="*60 + "\n")
        sys.exit(0)

if __name__ == "__main__":
    test_integration()
