#!/usr/bin/env python3
"""Test that mcp.execute_tool uses the gateway"""

from mcp import execute_tool
import json

print("🧪 Testing adb_devices via gateway...")
success, error, result = execute_tool("adb_devices", {})

print(f"Success: {success}")
if error:
    print(f"Error: {error}")
if result:
    print(f"Result: {json.dumps(result, indent=2)}")

print("\n🧪 Testing gradle_build via gateway...")
success, error, result = execute_tool("gradle_build", {"task": "assembleDebug"})

print(f"Success: {success}")
if error:
    print(f"Error: {error}")
if result:
    print(f"Result: {json.dumps(result, indent=2)}")

print("\n🧪 Testing git_commit via gateway...")
success, error, result = execute_tool("git_commit", {"message": "test from agent"})

print(f"Success: {success}")
if error:
    print(f"Error: {error}")
if result:
    print(f"Result: {json.dumps(result, indent=2)}")
