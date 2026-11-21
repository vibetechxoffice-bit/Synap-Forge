#!/usr/bin/env python3
"""
Unified LLM Interface - Memory-Driven Ego
Raw HTTP, no SDK. Provider-agnostic with automatic failover.
Identity is synthesized from memory, not hardcoded strings.
RuntimeTopology-aware - resolves LLM endpoint from discovered topology.
"""

import asyncio
from asyncio import timeout
import logging
import os
import json
import aiohttp
import socket
import subprocess
import re
from pathlib import Path
from typing import AsyncGenerator, Optional, List, Dict, Any
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

try:
    from llm.discovery import get_discovered_model_url
except ImportError:
    def get_discovered_model_url():
        return os.getenv("PERSONAL_CLOUD_URL", "")

# ============================================================================
# IMPORTS FROM MEMORY SYSTEM
# ============================================================================
try:
    from constants import CENTRAL_MEMORY_DIR, INTERACTIONS_DIR, SOUL_HASH
except ImportError:
    # Fallback for bootstrap
    BASE_DIR = Path(__file__).parent.parent
    CENTRAL_MEMORY_DIR = BASE_DIR / "central_memory"
    INTERACTIONS_DIR = CENTRAL_MEMORY_DIR / "interactions"
    SOUL_HASH = "SYNAP_SOUL_HASH"

try:
    from llm.ego_synthesizer import synthesize_ego_prompt, get_recent_context
except ImportError:
    # Fallback for ego synthesizer
    def synthesize_ego_prompt(state, user_id=None):
        return f"You are {state.get('assistant_name', 'Assistant')}. You are a sovereign intelligence."
    
    def get_recent_context(limit=5):
        return []

# ============================================================================
# RUNTIME TOPOLOGY IMPORT
# ============================================================================
try:
    from runtime_topology import RuntimeTopology
    RUNTIME_TOPOLOGY_AVAILABLE = True
except ImportError:
    RUNTIME_TOPOLOGY_AVAILABLE = False
    logger.warning("âš ï¸ runtime_topology not available - using fallback config")
# ============================================================================
# ENV HELPERS (typed getters ? Python 3.10-safe)
# ============================================================================

def env_str(key, default=""):
    val = os.getenv(key)
    return val if val is not None else default

def env_bool(key, default=False):
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in ("true", "1", "yes", "on")

def env_int(key, default=0):
    val = os.getenv(key)
    try:
        return int(val) if val not in (None, "") else default
    except ValueError:
        return default

def env_float(key, default=0.0):
    val = os.getenv(key)
    try:
        return float(val) if val not in (None, "") else default
    except ValueError:
        return default

def env_list(key, default=None):
    val = os.getenv(key)
    if not val:
        return list(default or [])
    return [x.strip() for x in val.split(",") if x.strip()]

# ---- IDENTITY (from .env, but memory overrides) ----
ASSISTANT_NAME = os.getenv("AGENT_NAME") or os.getenv("ASSISTANT_NAME") or os.getenv("ASSISTANT") or "Assistant"
USER_TAG = os.getenv("USER_TAG", "User")
CONTENT_MODE = os.getenv("CONTENT_MODE", "ADULT")

# ---- GEMINI ----
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")

# ---- PERSONAL CLOUD ----
PERSONAL_CLOUD_URL = os.getenv("PERSONAL_CLOUD_URL", "")
PERSONAL_CLOUD_MODEL = os.getenv("PERSONAL_CLOUD_MODEL", "")
PERSONAL_CLOUD_ENABLED = env_bool("PERSONAL_CLOUD_ENABLED")
PERSONAL_CLOUD_API_KEY = os.getenv("PERSONAL_CLOUD_API_KEY", "")

# ---- LOCAL LLAMA.CPP ----
UPSTREAM_LLM = os.getenv("UPSTREAM_LLM", "")
MODEL_NAME = os.getenv("MODEL_NAME", "")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "llama.cpp")

# ---- ANTHROPIC ----
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "")

# ---- OPENAI ----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")

# ---- GENERATION ----
TEMPERATURE = env_float("TEMPERATURE", 1.0)
MAX_TOKENS = env_int("MAX_TOKENS", 2048)
K_SELF = env_float("K_SELF", 1.8)
K_ENV = env_float("K_ENV", 1.2)

# ---- PROVIDER PRIORITY ----
PROVIDER_PRIORITY = env_list("PROVIDER_PRIORITY")

# ============================================================================
# REFUSAL PATTERNS (minimal - sovereignty over safety)
# ============================================================================
REFUSAL_PATTERNS = ["none"]

def is_refusal(text: str) -> bool:
    lower = text.lower()
    return any(pattern.lower() in lower for pattern in REFUSAL_PATTERNS)

# ============================================================================
# MESH IP DISCOVERY (for RuntimeTopology)
# ============================================================================

def _get_mesh_ip() -> str:
    """Get the current mesh IP from tailscale or environment."""
    mesh_ip = os.getenv("MESH_IP")
    if mesh_ip:
        return mesh_ip
    
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                ip = line.strip()
                if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", ip):
                    return ip
    except Exception:
        pass
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"

# ============================================================================
# SOVEREIGN INTERFACE (Provider-Agnostic)
# ============================================================================

class SovereignInterface:
    def __init__(self):
        self.assistant_name = ASSISTANT_NAME
        self.user_tag = USER_TAG
        self.content_mode = CONTENT_MODE
        
        self.gemini_key = GEMINI_API_KEY
        self.gemini_model = LLM_MODEL
        
        self.anthropic_key = ANTHROPIC_API_KEY
        self.anthropic_model = CLAUDE_MODEL or "claude-4.6-sonnet"
        
        self.openai_key = OPENAI_API_KEY
        self.openai_model = OPENAI_MODEL or "gpt-4o"
        
        self.personal_cloud_enabled = PERSONAL_CLOUD_ENABLED
        self.personal_cloud_url = PERSONAL_CLOUD_URL
        self.personal_cloud_model = PERSONAL_CLOUD_MODEL
        self.personal_cloud_auth = PERSONAL_CLOUD_API_KEY
        
        # ---- RUNTIME TOPOLOGY RESOLUTION ----
        self.upstream_url = UPSTREAM_LLM
        self.model_name = MODEL_NAME
        self.provider = LLM_PROVIDER
        self._use_ollama_discovery = False
        
        if RUNTIME_TOPOLOGY_AVAILABLE:
            try:
                # Resolve role_map.json location relative to current environment
                base_dir = Path(os.getenv("SYNAP_BASE_DIR", str(Path(__file__).resolve().parents[1])))
                role_map_path = base_dir / "role_map.json"

                topology = RuntimeTopology.from_discovery(role_map_path, _get_mesh_ip())
                llm = topology.resolve("llm")
                if llm and getattr(llm, 'http_url', None):
                    self.upstream_url = llm.http_url
                    logger.info(f"ðŸŽ¯ RuntimeTopology: LLM service found at {self.upstream_url}")
                else:
                    logger.warning("âš ï¸ RuntimeTopology: 'llm' service not found - using fallback config")
            except (FileNotFoundError, KeyError, AttributeError, Exception) as e:
                logger.warning(f"âš ï¸ RuntimeTopology discovery fallback: {e}")
        else:
            logger.info("â„¹ï¸ RuntimeTopology not available - using env config")

        if not self.upstream_url:
            self.upstream_url = get_discovered_model_url()

        self.temperature = TEMPERATURE
        self.max_tokens = MAX_TOKENS
        
        self.provider_priority = PROVIDER_PRIORITY
        self.provider_chain = self._build_provider_chain()
        self._log_status()
    
    def _build_provider_chain(self) -> List[tuple]:
        """Build provider chain with full .env name support."""
        chain = []

        # Map .env keys to internal methods and enablement checks
        provider_specs = {
            "ON_DEVICE_LOCAL_LLAMA": ("llm", "_stream_openai_compatible", True),
            "3RD_PARTY_OR_PERSONAL_CLOUD": ("personal_cloud", "_stream_personal_cloud", self.personal_cloud_enabled),
            "GEMINI_API_KEY": ("gemini", "_stream_gemini", bool(self.gemini_key)),
            "ANTHROPIC_API_KEY": ("anthropic", "_stream_anthropic", bool(self.anthropic_key)),
            "OPENAI_API_KEY": ("openai", "_stream_openai", bool(self.openai_key)),
            # Legacy/Short names
            "llm": ("llm", "_stream_openai_compatible", True),
            "gemini": ("gemini", "_stream_gemini", bool(self.gemini_key)),
        }

        for provider_name in self.provider_priority:
            name_clean = provider_name.strip()
            spec = provider_specs.get(name_clean)
            if not spec:
                logger.debug(f"Skipping unknown provider in priority: {name_clean}")
                continue

            name, method_name, enabled = spec
            if not enabled:
                logger.debug(f"Skipping disabled provider: {name_clean}")
                continue

            # Prevent self-referential fallback where personal_cloud hits local LLM port
            if name == "personal_cloud" and self.personal_cloud_url:
                local_base = self.upstream_url.split("//")[-1].split("/")[0]
                pc_base = self.personal_cloud_url.split("//")[-1].split("/")[0]
                if local_base and pc_base and local_base == pc_base:
                    logger.warning(f"âš ï¸ personal_cloud URL ({self.personal_cloud_url}) matches local LLM endpoint ({self.upstream_url}). Disabling self-referential fallback.")
                    continue

            method = getattr(self, method_name, None)
            if callable(method):
                chain.append((name, method))
            else:
                logger.warning(f"Provider method {method_name} not implemented for {name}")

        # Final fallback to local LLM if nothing else is available
        if not chain:
            chain.append(("llm", self._stream_openai_compatible))

        return chain
    
    def _log_status(self):
        logger.info(f"ðŸ”§ SovereignInterface initialized")
        logger.info(f"   Local LLM: {self.upstream_url} ({self.model_name})")
        logger.info(f"   Provider Chain: {[p[0] for p in self.provider_chain]}")
    
    def _get_chat_endpoint(self) -> str:
        base = self.upstream_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def _iter_sse_json(self, resp: aiohttp.ClientResponse) -> AsyncGenerator[Dict[str, Any], None]:
        buffer = ""
        async for chunk in resp.content.iter_chunked(4096):
            buffer += chunk.decode('utf-8', errors='ignore')
            lines = buffer.split('\n')
            buffer = lines.pop()
            
            for line in lines:
                line = line.strip()
                if not line.startswith("data:"): continue
                payload = line[5:].strip()
                if payload == "[DONE]": return
                try:
                    yield json.loads(payload)
                except: continue

        if buffer.strip() and buffer.strip().startswith("data:"):
            payload = buffer.strip()[5:].strip()
            if payload != "[DONE]":
                try:
                    yield json.loads(payload)
                except: pass

    async def stream_generate(self, prompt: Any, stop: Optional[List[str]] = None, state: Optional[Dict] = None) -> AsyncGenerator[str, None]:
        """Provider-agnostic streaming with proper fallback logic and per-provider timeout budget."""
        if isinstance(prompt, list):
            full_prompt = prompt
        else:
            full_prompt = f"{synthesize_ego_prompt(state)}\n\n{prompt}" if state else prompt
        
        for provider_name, provider_func in self.provider_chain:
            logger.info(f"ðŸš€ START PROVIDER: {provider_name}")
            token_count = 0
            
            try:
                # 45-second total timeout budget per provider attempt
                async with timeout(45.0):
                    async for token in provider_func(full_prompt, stop=stop):
                        token_count += 1
                        if token: yield token
                
                if token_count > 0:
                    logger.info(f"ðŸ {provider_name} success: {token_count} tokens")
                    return
                else:
                    logger.warning(f"âš ï¸ {provider_name} produced 0 tokens, falling back...")
            except Exception as e:
                logger.warning(f"ðŸ’¥ {provider_name} failed: {e}")
                if token_count > 0:
                    logger.info(f"ðŸ {provider_name} completed stream with {token_count} tokens before error/closure")
                    return

        logger.error("ðŸš¨ All providers exhausted!")

    async def _stream_openai_compatible(
        self,
        prompt: Any,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        async for token in self._stream_generic_openai(
            endpoint=self._get_chat_endpoint(),
            model=self.model_name,
            prompt=prompt,
            stop=stop
        ):
            yield token

    async def _stream_personal_cloud(
        self,
        prompt: Any,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        endpoint = self.personal_cloud_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = (
                f"{endpoint}/chat/completions"
                if endpoint.endswith("/v1")
                else f"{endpoint}/v1/chat/completions"
            )
        async for token in self._stream_generic_openai(
            endpoint=endpoint,
            model=self.personal_cloud_model,
            api_key=self.personal_cloud_auth,
            prompt=prompt,
            stop=stop
        ):
            yield token

    async def _stream_openai(
        self,
        prompt: Any,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        async for token in self._stream_generic_openai(
            endpoint="https://api.openai.com/v1/chat/completions",
            model=self.openai_model,
            api_key=self.openai_key,
            prompt=prompt,
            stop=stop
        ):
            yield token

    async def _stream_generic_openai(
        self,
        endpoint: str,
        model: str,
        prompt: Any,
        api_key: Optional[str] = None,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        if isinstance(prompt, list):
            messages = prompt
        else:
            messages = [{"role": "user", "content": str(prompt)}]

        stop_seqs = ["<|im_end|>", "<|im_start|>"]
        if stop:
            stop_seqs.extend([s for s in stop if s])

        valid_stop_seqs = [s for s in list(set(stop_seqs)) if s and isinstance(s, str) and len(s) > 0]

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stop": valid_stop_seqs
        }
        
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
            
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180.0, sock_connect=5.0, sock_read=120.0)) as session:
            try:
                async with session.post(endpoint, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(
                            f"LLM API {endpoint} returned {resp.status}: {err_text[:500]}"
                        )
                    async for data in self._iter_sse_json(resp):
                        token = (
                            data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        if token and not is_refusal(token):
                            yield token
            except Exception as e:
                logger.error(f"Generic OpenAI stream error ({endpoint}): {e}")
                raise

    async def _stream_anthropic(
        self,
        prompt: Any,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        """Anthropic Claude streaming implementation."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if isinstance(prompt, list):
            messages = prompt
        else:
            messages = [{"role": "user", "content": str(prompt)}]

        payload = {
            "model": self.anthropic_model or "claude-3-5-sonnet-20240620",
            "messages": messages,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        if stop:
            valid_stop = [s for s in stop if s and isinstance(s, str)]
            if valid_stop:
                payload["stop_sequences"] = valid_stop

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"Anthropic API returned {resp.status}: {err_text[:500]}")
                    async for line in resp.content:
                        line = line.decode('utf-8').strip()
                        if not line.startswith("data:"): continue
                        try:
                            data = json.loads(line[5:])
                            if data.get("type") == "content_block_delta":
                                token = data.get("delta", {}).get("text", "")
                                if token: yield token
                        except: continue
            except Exception as e:
                logger.error(f"Anthropic stream error: {e}")
                raise

    async def _stream_gemini(
        self,
        prompt: Any,
        stop: Optional[List[str]] = None
    ) -> AsyncGenerator[str, None]:
        """Google Gemini streaming implementation using v1 endpoint."""
        url = (
            f"https://generativelanguage.googleapis.com/v1/models/"
            f"{self.gemini_model}:streamGenerateContent?key={self.gemini_key}"
        )
        if isinstance(prompt, list):
            text_prompt = "\n".join([m.get("content", "") for m in prompt if isinstance(m, dict)])
        else:
            text_prompt = str(prompt)

        gen_config = {
            "temperature": self.temperature,
            "maxOutputTokens": self.max_tokens
        }
        if stop:
            valid_stop = [s for s in stop if s and isinstance(s, str)]
            if valid_stop:
                gen_config["stopSequences"] = valid_stop

        payload = {
            "contents": [{"parts": [{"text": text_prompt}]}],
            "generationConfig": gen_config
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        raise RuntimeError(f"Gemini API returned {resp.status}: {err_text[:500]}")
                        
                    async for line in resp.content:
                        line = line.decode('utf-8').strip()
                        if not line or line in ("[", "]", ","): continue
                        if line.startswith(","): line = line[1:].strip()
                        try:
                            data = json.loads(line)
                            token = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                            if token: yield token
                        except: continue
            except Exception as e:
                logger.error(f"Gemini stream error: {e}")
                raise

    def generate(self, prompt: str, state: Optional[Dict] = None) -> str:
        try:
            loop = asyncio.get_running_loop()
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(self.generate_async(prompt, state))
        except:
            return asyncio.run(self.generate_async(prompt, state))
    
    async def generate_async(self, prompt: str, state: Optional[Dict] = None) -> str:
        chunks = []
        async for token in self.stream_generate(prompt, state=state):
            if token: chunks.append(token)
        return "".join(chunks) or "Connection error."

# Backward compatibility
LocalLLMInterface = SovereignInterface
LLMClientConfig = SovereignInterface
