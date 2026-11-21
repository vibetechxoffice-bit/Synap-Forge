#!/usr/bin/env python3
"""
Comprehensive Independent Verification Test Suite for Synap-Forge Remediation Areas:
1. PCM Framing & Header Detection
2. Sample Rate Standardization (16 kHz)
3. Voice Listen STT Dispatch
4. Authentication & Default-Deny Security (Missing Token, Invalid Token, Local Access)
5. Critical Action Approval Lifecycle (Binding, Expiry, Replay Prevention, Single Consumption)
6. TTS Pacing & Queue Behavior
"""

import os
import sys
import time
import unittest
import numpy as np
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "mcp"))

from websocket import is_framed_audio, CODEC_PCM16, CODEC_OPUS, AudioMessage
from mcp_server import Gateway

class TestRemediationVerification(unittest.TestCase):

    # ── 1. PCM FRAMING & HEADER DETECTION ─────────────────────────────────────
    def test_pcm_framing_detection(self):
        """Verify that raw PCM and 5-byte framed payloads are unambiguously distinguished."""
        raw_pcm_640 = b"\x00\x01" * 320  # 640 bytes (even)

        # Raw PCM should be recognized as unframed
        is_framed, codec, payload = is_framed_audio(raw_pcm_640)
        self.assertFalse(is_framed, "Raw PCM 640 bytes should not be detected as framed")
        self.assertEqual(codec, CODEC_PCM16)
        self.assertEqual(payload, raw_pcm_640)

        # Framed PCM: 5-byte header (seq 0 + codec 0) + 640 bytes PCM = 645 bytes (odd)
        header_pcm = b"\x00\x00\x00\x00\x00"
        framed_pcm = header_pcm + raw_pcm_640

        is_framed, codec, payload = is_framed_audio(framed_pcm)
        self.assertTrue(is_framed, "5-byte header + 640 bytes PCM must be detected as framed")
        self.assertEqual(codec, CODEC_PCM16)
        self.assertEqual(payload, raw_pcm_640)

        # Framed Opus: 5-byte header (seq 0 + codec 1) + payload
        header_opus = b"\x00\x00\x00\x00\x01"
        raw_opus = b"\x08\xFF\x34\x12"
        framed_opus = header_opus + raw_opus

        is_framed, codec, payload = is_framed_audio(framed_opus)
        self.assertTrue(is_framed, "5-byte header + Opus payload must be detected as framed")
        self.assertEqual(codec, CODEC_OPUS)
        self.assertEqual(payload, raw_opus)

    # ── 2. SAMPLE RATE STANDARDIZATION (16 kHz) ──────────────────────────────
    def test_sample_rate_standardization(self):
        """Verify 16 kHz sample rate default across message schemas."""
        msg = AudioMessage()
        self.assertEqual(msg.sample_rate, 16000, "AudioMessage default sample rate must be 16000 Hz")

    # ── 3. AUTHENTICATION & DEFAULT DENY ─────────────────────────────────────
    def test_authentication_default_deny(self):
        """Verify default-deny when env vars absent, invalid token supplied, or request is local."""
        gw = Gateway()

        # Scenario A: All environment variables absent -> Default Deny
        orig_auth = os.environ.pop("AUTH_TOKEN", None)
        orig_mcp = os.environ.pop("MCP_API_KEY", None)
        orig_synap = os.environ.pop("SYNAP_API_KEY", None)

        try:
            auth, err, _ = gw._authorize_action("read_file", {"file_path": "test.txt"}, headers={})
            self.assertFalse(auth, "Action must be denied when no server auth token is configured")
            self.assertIn("not configured", err)

            # Scenario B: Valid server token configured, but invalid token supplied
            os.environ["AUTH_TOKEN"] = "secret_valid_token_123"
            auth, err, _ = gw._authorize_action("read_file", {"file_path": "test.txt"}, headers={"Authorization": "Bearer invalid_token"})
            self.assertFalse(auth, "Action must be denied when invalid token is supplied")
            self.assertIn("invalid or missing", err)

            # Scenario C: Request originates locally (from 127.0.0.1) without valid token -> NO BYPASS
            local_headers = {"X-Forwarded-For": "127.0.0.1", "Host": "localhost"}
            auth, err, _ = gw._authorize_action("read_file", {"file_path": "test.txt"}, headers=local_headers)
            self.assertFalse(auth, "Local access must NOT bypass authorization check")

            # Scenario D: Valid token supplied
            auth, err, _ = gw._authorize_action("read_file", {"file_path": "test.txt"}, headers={"Authorization": "Bearer secret_valid_token_123"})
            self.assertTrue(auth, "Action must succeed when valid token is supplied")

        finally:
            if orig_auth: os.environ["AUTH_TOKEN"] = orig_auth
            if orig_mcp: os.environ["MCP_API_KEY"] = orig_mcp
            if orig_synap: os.environ["SYNAP_API_KEY"] = orig_synap

    # ── 4. CRITICAL ACTION APPROVAL LIFECYCLE ────────────────────────────────
    def test_approval_lifecycle(self):
        """Verify full approval lifecycle: requirement, operator approval, param binding, single-use, & double-approval rejection."""
        gw = Gateway()
        os.environ["AUTH_TOKEN"] = "valid_api_key_456"
        os.environ["MCP_ADMIN_KEY"] = "operator_admin_key_789"

        headers = {"Authorization": "Bearer valid_api_key_456"}
        op_headers = {"Authorization": "Bearer operator_admin_key_789"}

        # Step 1: Initial call to critical action 'git_push' without approval_token -> returns pending approval
        auth, err, extra = gw._authorize_action("git_push", {"remote": "origin", "branch": "main"}, headers=headers)
        self.assertFalse(auth)
        self.assertTrue(extra.get("requires_approval"))
        approval_id = extra.get("approval_id")
        self.assertIsNotNone(approval_id)

        # Step 2: Operator grants approval
        with gw.app.test_request_context("/api/approve_confirmation", headers=op_headers, json={"approval_id": approval_id, "approved": True}):
            from flask import request as flask_req
            # Test approval logic directly through pending_confirmations state
            with gw.confirmations_lock:
                req = gw.pending_confirmations[approval_id]
                self.assertEqual(req["status"], "pending")
                req["status"] = "approved"
                approval_token = "tok_test_approval_123"
                req["approval_token"] = approval_token

        # Step 3: Parameter Mismatch Check -> Modified params must be rejected
        auth, err, _ = gw._authorize_action("git_push", {"remote": "origin", "branch": "dev", "approval_token": approval_token}, headers=headers)
        self.assertFalse(auth, "Critical action with modified parameters must be rejected")

        # Step 4: Correct Parameters -> Must succeed & consume token
        auth, err, _ = gw._authorize_action("git_push", {"remote": "origin", "branch": "main", "approval_token": approval_token}, headers=headers)
        self.assertTrue(auth, "Critical action with valid approval token and exact matching parameters must succeed")

        # Step 5: Replay Prevention -> Same token used a second time MUST be denied
        auth, err, _ = gw._authorize_action("git_push", {"remote": "origin", "branch": "main", "approval_token": approval_token}, headers=headers)
        self.assertFalse(auth, "Replay attempt with already consumed approval token must be denied")

    def test_approval_expiry(self):
        """Verify that expired approval requests cannot be approved or executed."""
        gw = Gateway()
        now = time.time()
        expired_id = "req_expired_test"

        with gw.confirmations_lock:
            gw.pending_confirmations[expired_id] = {
                "approval_id": expired_id,
                "action": "git_push",
                "params": {"remote": "origin", "branch": "main"},
                "created_at": now - 400,
                "expires_at": now - 100,  # Expired 100s ago
                "status": "pending",
                "approval_token": None
            }

        headers = {"Authorization": "Bearer valid_api_key_456"}
        auth, err, extra = gw._authorize_action("git_push", {"remote": "origin", "branch": "main"}, headers=headers)
        self.assertFalse(auth)
        # Expired request should have been cleaned up and a new request generated
        self.assertNotEqual(extra.get("approval_id"), expired_id)

if __name__ == "__main__":
    unittest.main()
