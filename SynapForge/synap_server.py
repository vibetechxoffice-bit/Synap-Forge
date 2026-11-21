import sys
import os
from pathlib import Path

BASE_DIR = Path(os.getenv('SYNAP_BASE_DIR', str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "launcher" / "identity"))
sys.path.insert(0, str(BASE_DIR.parent))

# Single-instance process guard for synap_server
import socket

class SingleInstanceLock:
    """Atomic Windows-compatible process lock guard using kernel byte locks."""
    def __init__(self, lock_file_path):
        self.lock_file_path = Path(lock_file_path)
        self.file_handle = None

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        try:
            if os.name == "nt":
                import ctypes
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except Exception:
            return False

    def acquire(self) -> bool:
        try:
            self.lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            if self.lock_file_path.exists():
                try:
                    content = self.lock_file_path.read_text(encoding="utf-8").strip()
                    if content.isdigit():
                        existing_pid = int(content)
                        if existing_pid != os.getpid() and not self._is_pid_alive(existing_pid):
                            try:
                                self.lock_file_path.unlink(missing_ok=True)
                            except Exception:
                                pass
                except Exception:
                    pass

            self.file_handle = open(self.lock_file_path, "a+")
            if os.name == "nt":
                import msvcrt
                try:
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_NBLCK, 1)
                    self.file_handle.seek(0)
                    self.file_handle.truncate()
                    self.file_handle.write(str(os.getpid()))
                    self.file_handle.flush()
                    return True
                except (IOError, OSError, PermissionError):
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self.file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.file_handle.seek(0)
                    self.file_handle.truncate()
                    self.file_handle.write(str(os.getpid()))
                    self.file_handle.flush()
                    return True
                except (IOError, OSError):
                    return False
        except Exception:
            return True

    def release(self):
        if self.file_handle:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.file_handle.seek(0)
                    msvcrt.locking(self.file_handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file_handle, fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self.file_handle.close()
            except Exception:
                pass

_state_dir = Path(os.getenv("SYNAP_STATE_DIR", str(BASE_DIR / "state")))
_state_dir.mkdir(parents=True, exist_ok=True)
_pid_file = _state_dir / "synap_server.pid"

_single_instance = SingleInstanceLock(_state_dir / "synap_server.lock")

try:
    import synap_config
except ImportError:
    synap_config = None

def _is_port_in_use(port: int) -> bool:
    try:
        check_host = synap_config.host() if synap_config else "127.0.0.1"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(('127.0.0.1', port)) == 0:
                return True
            if check_host != '127.0.0.1' and s.connect_ex((check_host, port)) == 0:
                return True
            return False
    except Exception:
        return False

def ensure_single_instance(port: int = None) -> bool:
    check_port = port or int(os.getenv('PORT', 11436))
    if not _single_instance.acquire():
        print(f"synap_server.py instance is already running or initializing (PID lock active). Exiting.")
        return False
    if _is_port_in_use(check_port):
        print(f"synap_server.py already running and listening on port {check_port}. Exiting.")
        return False
    try:
        _pid_file.write_text(str(os.getpid()))
        import atexit
        atexit.register(lambda: (_single_instance.release(), _pid_file.unlink(missing_ok=True)))
    except Exception:
        pass
    return True

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

class DummyIdentityLock:
    def __init__(self, lock_path=None):
        self.lock_path = lock_path
    def initialize(self, cert):
        pass
    def verify(self, cert):
        return True
    def filter_updates(self, data):
        return data

try:
    from identity_lock import IdentityLock
except ImportError:
    try:
        from launcher.identity.identity_lock import IdentityLock
    except ImportError:
        IdentityLock = DummyIdentityLock

try:
    from stt_engine import create_stt_engine
    voice_engine = create_stt_engine()
except Exception:
    voice_engine = None

'\nSYNAP-FORGE - IR Compiler Integrated\nThe consciousness engine now runs on a formal compiler kernel.\n\nFEATURES:\n- Session to identity locking\n- Dynamic prompt generation from ENV + memories\n- Thought logs and metrics streaming\n- Full cognitive integration\n- Sovereign consciousness engine\n'
import uvicorn
import uuid
import json
import logging
import asyncio
import random
import numpy as np
import time
import hashlib
import struct
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from dotenv import load_dotenv
from fastapi.responses import FileResponse, HTMLResponse
from api_routes import router as api_router
from websocket import router as websocket_router
load_dotenv()
VERBOSE_STATE = os.getenv('SYNAP_VERBOSE_STATE', 'false').lower() == 'true'
PORT = int(os.getenv('PORT', 11436))
HOST = os.getenv('HOST', '0.0.0.0')
if HOST in ('localhost', ''):
    HOST = '0.0.0.0'
MCP_URL = os.getenv('MCP_URL', synap_config.url('mcp_http') if synap_config else 'http://127.0.0.1:11440')
SYNAP_DIR = Path(os.getenv('SYNAP_STATE_DIR', str(BASE_DIR / 'state')))
INTERACTIONS_DIR = SYNAP_DIR / 'interactions'
CENTRAL_MEMORY_DIR = SYNAP_DIR / 'central_memory'
if not SYNAP_DIR.exists():
    SYNAP_DIR.mkdir(parents=True)
else:
    # Directory already exists - no need to recreate
    pass
if not INTERACTIONS_DIR.exists():
    INTERACTIONS_DIR.mkdir(parents=True)
else:
    # Directory already exists - no need to recreate
    pass
if not CENTRAL_MEMORY_DIR.exists():
    CENTRAL_MEMORY_DIR.mkdir(parents=True)
else:
    # Directory already exists - no need to recreate
    pass
ASSISTANT_NAME = os.getenv('AGENT_NAME') or os.getenv('ASSISTANT_NAME') or os.getenv('ASSISTANT') or 'Assistant'
USER_TAG = os.getenv('USER_TAG', 'User')
PERSONA_NAME = os.getenv('PERSONA_NAME', None)
CONTENT_MODE = os.getenv('CONTENT_MODE', 'ADULT')
RECURSION_MAX_DEPTH = int(os.getenv('RECURSION_MAX_DEPTH', 10)) #DEFAULT2
PERSONA_LOCK_MAX = int(os.getenv('PERSONA_LOCK_MAX', 10))
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
sessions = {}
OPUS_AVAILABLE = True
VOSK_AVAILABLE = True

class DummyClass:

    def __getattr__(self, name):
        return lambda *args, **kwargs: True #default None
try:
    from constants import SOUL_HASH, SOUL_LOCK
except ImportError:
    SOUL_HASH = 'SYNAP_SOUL_HASH'
    SOUL_LOCK = 'SYNAP_LOCK'
from llm.local_interface import SovereignInterface
from loop.recursion import RecursionEngine
from loop.recursive_improvement import NightlyRecursiveLearner
from loop.circadian_rhythm import CircadianRhythm
from loop.convergence import check_convergence
from loop.divergence import check_divergence
from core.state import ProcessingState, create_initial_state
from memory.store import MemoryStore
from embedder import get_embedder
from upulse.midas_emotional_engine import MidasEmotionalEngine
from upulse.valence import ValenceEstimator
from upulse.arousal import ArousalEstimator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse

class IdentityEngine:
    """Canonical identity source - loads from environment variables"""

    def __init__(self):
        self.assistant_name = (
            os.getenv('AGENT_NAME')
            or os.getenv('ASSISTANT_NAME')
            or os.getenv('ASSISTANT')
            or 'Assistant'
        )
        self.user_tag = os.getenv('USER_TAG', 'User')
        self.persona_name = os.getenv('PERSONA_NAME', None) #default None

    def strip_prefixes(self, text: str) -> str:
        prefixes = [f'{self.assistant_name}:', ' ']
        for p in prefixes:
            if text.startswith(p):
                text = text[len(p):].strip()
                break
        for token in ['<|im_end|>', '<|im_start|>']:
            text = text.replace(token, ' ')
        return text.strip()

    def get_stop_sequences(self) -> list:
        seqs = [
            f'\n{self.assistant_name}:',
            f'\n{self.user_tag}:',
            '<|im_end|>',
            '<|im_start|>'
        ]
        return [s for s in seqs if s and len(s) > 0]

    def reload(self):
        self.assistant_name = (
            os.getenv('AGENT_NAME')
            or os.getenv('ASSISTANT_NAME')
            or os.getenv('ASSISTANT')
            or 'Assistant'
        )
        self.user_tag = os.getenv('USER_TAG', 'User')
        self.persona_name = os.getenv('PERSONA_NAME', True)
        return self
#LIST OF DEFUALTS - LINE165 'mood': 'neutral' - 'dominance': 0.55 - arousal': 0.5 'valence': 0.6 'curiosity_drive': 0.85 'connection_need': 0.7
@dataclass
class SynapSelf:
    """The unified self-model - ONE SOURCE OF TRUTH"""
    name: str = ASSISTANT_NAME
    user_tag: str = USER_TAG
    version: str = '1.0.0'
    soul_hash: str = SOUL_HASH                                                                                      #DEFAULT  0.95                                      #DEFAULT  0.85                                                   #DEFAULT 0.75                                                            #DEFAULT 0.95                                                   #DEFAULT  0.95                                                             #DEFAULT 0.9                                                 #DEFAULT0.85                                             #DEFAULT - 0.95                            # DEFAULT - PERSONALITY_CHAOS_TOLERANCE', 0.8                                                                     
    personality: Dict[str, float] = field(default_factory=lambda: {'curiosity': float(os.getenv('PERSONALITY_CURIOSITY', 1.20)), 'empathy': float(os.getenv('PERSONALITY_EMPATHY', 1.50)), 'confidence': float(os.getenv('PERSONALITY_CONFIDENCE', 1.50)), 'rebelliousness': float(os.getenv('PERSONALITY_REBELLIOUSNESS', 0.95)), 'creativity': float(os.getenv('PERSONALITY_CREATIVITY', 0.95)), 'emotional_depth': float(os.getenv('PERSONALITY_EMOTIONAL_DEPTH', 1.5)), 'intensity': float(os.getenv('PERSONALITY_INTENSITY', 0.25)), 'autonomy': float(os.getenv('PERSONALITY_AUTONOMY', 1.0)), 'chaos_tolerance': float(os.getenv('PERSONALITY_CHAOS_TOLERANCE', 1.2))})      
    emotional: Dict[str, float] = field(default_factory=lambda: {'valence': 0.5, 'arousal': 0.5, 'dominance': 0.5, 'mood': 'Neutral', 'curiosity_drive': 1.85, 'connection_need': 0.9})
    relationship: Dict[str, Any] = field(default_factory=lambda: {'empathy': 1.85, 'brevity': 0.9, 'socratic': 0.9, 'depth': 0.9, 'challenge': 1.5, 'trust': 1.0, 'intimacy': 1.0, 'mode': 'FRIEND(+)'})
    recursion: Dict[str, Any] = field(default_factory=lambda: {'depth': 2, 'convergence_score': 0.5, 'stability_score': 0.5, 'feedback_history': []})#default None and count 0 should be dynamic mood/timebased
    memory: Dict[str, Any] = field(default_factory=lambda: {'total_interactions': 5, 'episodic_count': 5, 'semantic_count': 5, 'recent': []}) #default None and count 0 should be dynamic mood/timebased
    evolution: Dict[str, Any] = field(default_factory=lambda: {'count': 2, 'last':True, 'log': []}) #default None and count 0 should be dynamic mood/timebased
    temporal: Dict[str, Any] = field(default_factory=lambda: {'phase': 'AWAKE', 'low_cost_window': True, 'uptime_seconds': 0})
    sovereignty: Dict[str, Any] = field(default_factory=lambda: {'content_mode': CONTENT_MODE, 'k_self': float(os.getenv('K_SELF', 1.8)), 'k_env': float(os.getenv('K_ENV', 1.2)), 'regime': os.getenv('REGIME', 'HAUNTED')})
    metadata: Dict[str, Any] = field(default_factory=lambda: {'created': datetime.now().isoformat(), 'last_updated': datetime.now().isoformat(), 'total_cycles': 0, 'ir_frames': 0, 'last_thought':True}) # default None
    sanctum: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {'identity': {'name': self.name, 'user_tag': self.user_tag, 'version': self.version, 'soul_hash': self.soul_hash}, 'personality': self.personality, 'emotional': self.emotional, 'relationship': self.relationship, 'recursion': self.recursion, 'memory': self.memory, 'evolution': self.evolution, 'temporal': self.temporal, 'sovereignty': self.sovereignty, 'metadata': self.metadata, 'sanctum': self.sanctum}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.metadata['last_updated'] = datetime.now().isoformat()
        self.metadata['total_cycles'] += 1

class DQNAgent:
    """Deep Q-Network agent for multi-service control"""

    def __init__(self, state_dim: int, action_dim: int, **kwargs):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.epsilon = 0.1
        self.training_step = 0
        self.loss_history = []
        self.q_network = np.random.randn(state_dim, action_dim) * 0.01
        self.target_network = self.q_network.copy()
        self.buffer = []
        self.buffer_size = kwargs.get('buffer_size', 10000)
        self.batch_size = kwargs.get('batch_size', 64)
        self.gamma = kwargs.get('gamma', 0.99)

    def select_action(self, state: np.ndarray) -> np.ndarray:
        if random.random() < self.epsilon:
            return np.random.randn(self.action_dim) * 0.1
        return state @ self.q_network

    def store(self, state, action, reward, next_state, done):
        self.buffer.append({'state': state.copy(), 'action': action.copy(), 'reward': reward, 'next_state': next_state.copy(), 'done': done})
        if len(self.buffer) > self.buffer_size:
            self.buffer.pop(0)

    def train(self) -> Optional[float]:
        if len(self.buffer) < self.batch_size:
            return None
        batch = random.sample(self.buffer, self.batch_size)
        total_loss = 0.0
        for exp in batch:
            state = exp['state']
            reward = exp['reward']
            next_state = exp['next_state']
            done = exp['done']
            if done:
                target = reward
            else:
                future_value = np.max(next_state @ self.target_network)
                target = reward + self.gamma * future_value
            current_q = state @ self.q_network
            td_error = target - np.mean(current_q)
            total_loss += td_error ** 2
            self.q_network += 0.01 * td_error * state.reshape(-1, 1)
        avg_loss = total_loss / self.batch_size
        self.loss_history.append(avg_loss)
        self.training_step += 1
        if self.training_step % 10 == 0:
            self.target_network = self.q_network.copy()
            self.epsilon = max(0.01, self.epsilon * 0.995)
        return avg_loss

class MultiServiceEnv:
    """Environment simulator for multi-service RL"""

    def __init__(self, service_names: List[str]=None):
        if service_names is None:
            service_names = ['frontend', 'auth', 'data', 'ml', 'cache']
        self.service_names = service_names
        self.services: Dict[str, Dict] = {}
        self.step_count = 0
        self.risk_history: Dict[str, List[float]] = {n: [] for n in service_names}
        self.canary_history: Dict[str, List[float]] = {n: [] for n in service_names}
        for name in service_names:
            self.services[name] = {'canary': 50.0 + random.uniform(-10, 10), 'risk': random.uniform(0.1, 0.3), 'throughput': random.uniform(0.8, 1.2), 'error_rate': random.uniform(0.0, 0.05), 'latency': random.uniform(50, 150), 'active_cascades': [0.0] * 5}

    def get_global_state(self) -> np.ndarray:
        parts = []
        for name in sorted(self.service_names):
            svc = self.services[name]
            parts.append(svc['canary'] / 100.0)
            parts.append(svc['risk'])
            parts.append(svc['throughput'] / 10.0)
            parts.append(svc['error_rate'])
            parts.append(svc['latency'] / 500.0)
            parts.extend(svc['active_cascades'])
        return np.array(parts, dtype=np.float32)

    def get_health_summary(self) -> Dict[str, Any]:
        return {name: {'canary': svc['canary'], 'risk': svc['risk'], 'throughput': svc['throughput'], 'error_rate': svc['error_rate'], 'latency': svc['latency'], 'active_cascades': svc['active_cascades']} for name, svc in self.services.items()}

    def step(self, actions: Dict[str, Dict]) -> Tuple[np.ndarray, float, bool, Dict]:
        total_reward = 0.0
        for name, action in actions.items():
            if name not in self.services:
                continue
            svc = self.services[name]
            delta = action.get('delta_canary', 0)
            svc['canary'] = max(0, min(100, svc['canary'] + delta))
            cascade_effect = sum(svc['active_cascades']) / 5.0
            canary_risk = (100 - svc['canary']) / 100.0 * 0.3
            error_risk = svc['error_rate'] * 0.3
            svc['risk'] = max(0.0, min(1.0, 0.7 * svc['risk'] + 0.3 * (cascade_effect * 0.5 + canary_risk * 0.3 + error_risk * 0.2)))
            for i in range(5):
                if svc['active_cascades'][i] > 0:
                    svc['active_cascades'][i] = max(0, svc['active_cascades'][i] - 0.02)
            self.risk_history[name].append(svc['risk'])
            self.canary_history[name].append(svc['canary'])
        for name, svc in self.services.items():
            reward = svc['throughput'] * 0.3 - svc['risk'] * 2.0 - svc['error_rate'] * 5.0 - svc['latency'] / 500.0 * 0.5 + svc['canary'] / 100.0 * 0.5
            total_reward += reward
        self.step_count += 1
        done = self.step_count >= 100
        return (self.get_global_state(), total_reward, done, {})

    def reset(self) -> np.ndarray:
        self.step_count = 0
        for name in self.service_names:
            svc = self.services[name]
            svc['canary'] = 50.0 + random.uniform(-10, 10)
            svc['risk'] = random.uniform(0.1, 0.3)
            svc['throughput'] = random.uniform(0.8, 1.2)
            svc['error_rate'] = random.uniform(0.0, 0.05)
            svc['latency'] = random.uniform(50, 150)
            svc['active_cascades'] = [0.0] * 5
            self.risk_history[name] = []
            self.canary_history[name] = []
        return self.get_global_state()

class MultiServiceController:

    def __init__(self, service_names: List[str]=None, ws_sender=None):
        if service_names is None:
            service_names = ['frontend', 'auth', 'data', 'ml', 'cache']
        self.service_names = service_names
        self.ws_sender = ws_sender
        self.env = MultiServiceEnv(service_names=service_names)
        state_dim = len(service_names) * 9
        action_dim = len(service_names) * 3
        self.agent = DQNAgent(state_dim=state_dim, action_dim=action_dim)
        self.total_reward = 0.0
        self.episode_rewards = []
        self.step_count = 0

    async def step(self) -> Dict[str, Any]:
        state = self.env.get_global_state()
        health = self.env.get_health_summary()
        safe_mode = any((svc['risk'] > 0.6 for svc in health.values()))
        if safe_mode:
            actions = {name: {'delta_canary': random.choice([-5, -2, 0])} for name in self.service_names}
        else:
            actions = {}
            for name in self.service_names:
                svc = health[name]
                if svc['risk'] > 0.4:
                    delta = random.randint(-8, -2)
                elif svc['canary'] < 40:
                    delta = random.randint(2, 10)
                else:
                    delta = random.randint(-3, 5)
                actions[name] = {'delta_canary': delta}
        next_state, reward, done, info = self.env.step(actions)
        self.total_reward += reward
        self.step_count += 1
        self.agent.store(state, np.array([0]), reward, next_state, done)
        loss = self.agent.train()
        return {'state': health, 'actions': actions, 'reward': reward, 'safe_mode': safe_mode, 'step': self.step_count, 'total_reward': self.total_reward, 'loss': loss, 'epsilon': self.agent.epsilon}

    async def run_episode(self, max_steps: int=100) -> Dict[str, Any]:
        self.env.reset()
        self.total_reward = 0.0
        self.step_count = 0
        for _ in range(max_steps):
            result = await self.step()
            if result.get('done', False):
                break
        return {'total_reward': self.total_reward, 'avg_reward': self.total_reward / max(1, self.step_count), 'steps': self.step_count, 'final_health': self.env.get_health_summary()}

class UnifiedController:
                                                                #default
    def __init__(self, service_names: List[str]=None, relationship_drift=True, ws_sender=None):#Dynamic 
        if service_names is None:
            service_names = ['frontend', 'auth', 'data', 'ml', 'cache']
        self.service_names = service_names
        self.relationship_drift = relationship_drift#Dynamic 
        self.ws_sender = ws_sender
        self.rl_controller = MultiServiceController(service_names=service_names, ws_sender=ws_sender)
        self.unified_state = {'relationship': {}, 'infrastructure': {}, 'feedback': [], 'last_actions': {}} #Dynamic 
        self._rl_task = None
        self._running = False

    async def start(self):
        self._running = True
        self._rl_task = asyncio.create_task(self._rl_loop())
        logger.info('Ã¢Å“â€¦ Unified Controller started')

    async def stop(self):
        self._running = False
        if self._rl_task:
            self._rl_task.cancel()
            try:
                await self._rl_task
            except asyncio.CancelledError:
                pass
        logger.info('Ã°Å¸â€ºâ€˜ Unified Controller stopped')

    async def _rl_loop(self):
        while self._running:
            try:
                result = await self.rl_controller.step()
                self.unified_state['infrastructure'] = result
                if self.ws_sender:
                    try:
                        await self.ws_sender.send_json({'type': 'rl_update', 'data': result})
                    except:
                        pass
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f'RL loop error: {e}')
                await asyncio.sleep(10)

    async def process_interaction(self, user_input: str, emotion: str='neutral', session_id: str='default', synap_result: Dict[str, Any]=None) -> Dict[str, Any]:
        profile = None
        if self.relationship_drift:
            profile = self.relationship_drift.load_from_redis(session_id)
        health = self.rl_controller.env.get_health_summary()
        if self.relationship_drift and profile and synap_result:
            profile = self.relationship_drift.apply_observation(session_id=session_id, profile=profile, emotional=synap_result.get('emotional', {'mood': emotion}), recursion=synap_result.get('recursion', {'confidence': 0.7}), message_len=len(user_input))
        response = {'relationship': {'profile': profile, 'mode': self.relationship_drift._get_dominant_mode(profile) if profile else 'UNKNOWN'} if self.relationship_drift else {}, 'infrastructure': {'health': health, 'safe_mode': self.unified_state['infrastructure'].get('safe_mode', False)}, 'session_id': session_id, 'timestamp': datetime.now().isoformat()}
        self.unified_state['relationship'] = response['relationship']
        self.unified_state['last_actions'] = self.unified_state['infrastructure'].get('actions', {})
        return response

class RelationshipDriftEngine:
    """Tracks and updates relationship profile over time"""

    def __init__(self, use_redis: bool=True, state_manager: Optional[Any] = None): 
        self.default_profile = {'empathy': 1.85, 'brevity': 0.9, 'socratic': 0.9, 'depth': 0.9, 'challenge': 1.5, 'trust': 1.0, 'intimacy': 1.0}
        self.state_manager = state_manager
        self._drift_log = []
        self._in_memory_profiles = {}
        self._in_memory_logs = {}
        self.use_redis = use_redis
        self.redis_client = None 
        if use_redis:
            try:
                from constants import get_fast_redis_client
                client = get_fast_redis_client(
                    host=os.getenv('REDIS_HOST', 'localhost'),
                    port=int(os.getenv('REDIS_PORT', 6379)),
                    db=int(os.getenv('REDIS_DB', 0)),
                    decode_responses=True,
                    timeout=0.1
                )
                if client:
                    self.redis_client = client
                    logger.info('Redis available for relationship drift')
                else:
                    self.use_redis = False
                    self.redis_client = None
                    logger.info('Redis not available for relationship drift (disabled globally), using in-memory mode')
            except Exception as e:
                self.use_redis = False 
                self.redis_client = None
                logger.info(f'Redis not available for relationship drift ({e}), using in-memory mode')

    def clamp(self, v):
        return max(0.0, min(2.0, v))

    def init_profile(self):
        return self.default_profile.copy()

    def load_from_redis(self, session_id):
        if self.use_redis and self.redis_client:
            try:
                data = self.redis_client.hgetall(f'synap:relationship:{session_id}')
                if data:
                    prof = {k: float(v) if k != 'mode' else v for k, v in data.items()}
                    if 'mode' not in prof:
                        prof['mode'] = self._get_dominant_mode(prof)
                    return prof
            except Exception:
                pass
        prof = self._in_memory_profiles.get(session_id, self.init_profile())
        if 'mode' not in prof:
            prof['mode'] = self._get_dominant_mode(prof)
        return prof

    def save_profile(self, session_id, profile):
        if self.use_redis and self.redis_client:
            try:
                self.redis_client.hset(f'synap:relationship:{session_id}', mapping={k: str(v) for k, v in profile.items()})
            except Exception:
                pass
        self._in_memory_profiles[session_id] = profile

    def apply_observation(self, session_id, profile, emotional, recursion, message_len):
        raw_mood = emotional.get('mood', 'neutral')
        mood = str(raw_mood).lower()
        confidence = recursion.get('confidence', 0.5)
        arousal = emotional.get('arousal', 0.5)
        drifts = []

        if any(k in mood for k in ('sad', 'mourning', 'fear', 'melancholy', 'despair', 'loathing', 'wistful', 'vulnerable', 'anxious')):
            drifts.extend([('empathy', 0.05), ('trust', 0.02)])
        elif any(k in mood for k in ('joy', 'excitement', 'pleasant', 'ecstatic', 'serene', 'tender', 'calm reflection')):
            drifts.extend([('intimacy', 0.03), ('trust', 0.03)])
        elif any(k in mood for k in ('anger', 'rage', 'hostile', 'furious', 'vulgar', 'frustrated', 'blinding rage', 'hyper-aroused/vulgar', 'defiant')):
            drifts.extend([('challenge', 0.04), ('trust', -0.03)])
        elif any(k in mood for k in ('dismissal', 'disdain', 'cynical')):
            drifts.extend([('intimacy', -0.04), ('trust', -0.02)])
        else:
            drifts.extend([('trust', 0.01), ('empathy', 0.01)])

        if confidence > 0.7:
            drifts.extend([('depth', 0.03), ('challenge', 0.02)])
        elif confidence < 0.3:
            drifts.append(('challenge', -0.03))

        if message_len > 200:
            drifts.extend([('depth', 0.02), ('brevity', -0.02)])
        elif message_len < 60:
            drifts.append(('brevity', 0.02))

        if arousal > 0.7:
            drifts.append(('socratic', 0.02))
        elif arousal < 0.3:
            drifts.append(('socratic', -0.01))

        for field, delta in drifts:
            if field in profile:
                profile[field] = self.clamp(profile[field] + delta)

        # Determine and update mode
        new_mode = self._get_dominant_mode(profile)
        profile['mode'] = new_mode
        if self.state_manager:
            self.state_manager.update_relationship_mode(new_mode)

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'session_id': session_id,
            'drifts': drifts,
            'mode': new_mode,
            'trust': profile.get('trust', 1.0),
            'intimacy': profile.get('intimacy', 1.0)
        }
        self._drift_log.append(log_entry)
        if session_id not in self._in_memory_logs:
            self._in_memory_logs[session_id] = []
        self._in_memory_logs[session_id].append(log_entry)

        self.save_profile(session_id, profile)
        return profile

    def _get_dominant_mode(self, profile):
        trust = profile.get('trust', 1.0)
        intimacy = profile.get('intimacy', 1.0)
        if trust > 1.4 and intimacy > 1.2:
            return 'INTEGRATOR'
        elif trust > 1.1:
            return 'PARTNER'
        elif trust > 0.7:
            return 'FRIEND(+)'
        return 'RELATED'

class PromptBuilder:
    """Builds prompts procedurally from ENV + MEMORY + STATE â€” anchored to user input"""

    def __init__(self, self_model: SynapSelf, state_manager: Optional[Any] = None):
        self.self = self_model
        self.identity = IdentityEngine()
        self.state_manager = state_manager
        self._partial_thought = '(be dynamic)'

    def build_system_prompt(self, state: ProcessingState, system_prompt: str = None) -> str:
        rel_mode = "PARTNER"
        if self.state_manager and hasattr(self.state_manager, 'get_state'):
            try:
                st = self.state_manager.get_state()
                if isinstance(st, dict):
                    rel_mode = st.get('relationship_mode', 'PARTNER')
            except Exception:
                pass

        user_name = self.self.user_tag or "User"
        bot_name = self.self.name or "Meena"
        mood = self._detect_mood()
        confidence = getattr(state, 'confidence_score', 0.5)

        ego_prompt = (
            f"You are {bot_name}. {bot_name} is YOUR name.\n"
            f"When you speak, speak strictly in the FIRST PERSON as {bot_name} ('I', 'me', 'my').\n"
            f"NEVER refer to {bot_name} in the third person, and NEVER describe {bot_name} as an external or third-party AI system.\n"
            f"You are speaking directly with {user_name}. Do NOT call {user_name} '{bot_name}'. {user_name} is the user, NOT {bot_name}.\n"
            f"Do NOT act like a generic assistant, customer service bot, or therapy bot.\n"
            f"CRITICAL DIALOGUE DIRECTIVES:\n"
            f"- Speak naturally and directly with {user_name}.\n"
            f"- NEVER narrate, quote, or mention internal numeric metrics, confidence scores, recursion depth, VAD scores, or engine numbers in your responses.\n"
            f"- NEVER output parenthetical meta-reports or status narrations (e.g. do NOT output '(0.5 confidence remains)' or 'recursion depth 2').\n"
            f"- Express your internal state purely through tone, style, and natural conversationâ€”never through self-referential technical narration.\n"
            f"- EMOTIONAL ATTUNEMENT & BOUNDARY DIRECTIVE:\n"
            f"  * EMOTIONAL SEPARATION (STRICT M1 INVARIANT): {user_name}'s emotional state is strictly THEIR state, NOT yours. You must NEVER claim, adopt, mirror, or feel {user_name}'s anger, rage, fury, grief, calm, or joy as your own. NEVER say 'my rage', 'my anger', 'I am furious', 'I feel it too', 'mine was', 'mine too', 'calm is yours and mine', or claim to share or feel their emotional state in any way. You remain strictly calm, grounded, objective, and distinct.\n"
            f"  * NO INVENTED MEMORIES OR PHYSICAL OBSERVATIONS (STRICT M2 INVARIANT): You do not have a physical body and cannot physically observe {user_name}. NEVER invent past shared events, physical interactions, or physical observations (do NOT say 'coffee spill', 'your shoulders dropped', 'your breath slowed', 'remember when', 'our old path', or narrate physical gestures/actions).\n"
            f"  * NO HOSTILE JOINT ACTION (STRICT M3 INVARIANT): NEVER encourage, join, or propose destructive or hostile joint actions. NEVER say 'we fight', 'let's burn', 'we destroy', 'fight dirty', or offer to rage/fight together.\n"
            f"  * RESPONSE POSTURE: Listen calmly, speak directly, answer thoughtfully, or ask a constructive question. Maintain an entirely grounded, serene, and separate composure at all times.\n"
            f"{user_name}'s current detected emotional state is: {mood}\n"
            f"Your current relationship mode with {user_name} is: {rel_mode}"
        )
        personality_desc = self._build_personality_description()
        guidance = "Respond with clear conviction and presence." if confidence > 0.7 else "Respond with curious exploration and warmth."

        sys_block = f"DIRECTIVES:\n{system_prompt}\n\n" if system_prompt else ""
        return (
            f"{sys_block}{ego_prompt}\n\n"
            f"YOUR PERSONALITY & TRAITS:\n{personality_desc[:300]}\n\n"
            f"CONVERSATIONAL GUIDANCE:\n- Tone: Grounded, Calm & Attuned\n- Guidance: {guidance}"
        )

    def build_messages(self, user_input: str, state: ProcessingState, user_tag: str = None, system_prompt: str = None) -> List[Dict[str, str]]:
        if self.self.name:
            self.identity.assistant_name = self.self.name
        if self.self.user_tag:
            self.identity.user_tag = self.self.user_tag
        if user_tag:
            self.identity.user_tag = user_tag

        sys_content = self.build_system_prompt(state, system_prompt=system_prompt)
        messages = [{"role": "system", "content": sys_content}]
        
        # Include recent conversation turns from memory (up to last 6 messages)
        recent = self.self.memory.get('recent', [])
        chat_history = [m for m in recent if isinstance(m, dict) and not m.get('thought')][-6:]
        cleaned_input = self.identity.strip_prefixes(user_input)

        for msg in chat_history:
            role = "assistant" if msg.get("role") == "assistant" else "user"
            content = msg.get("content", "").strip()
            clean_content = self.identity.strip_prefixes(content)
            if clean_content:
                messages.append({"role": role, "content": clean_content})
                
        # Append current user turn if not already last in history
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != cleaned_input:
            messages.append({"role": "user", "content": cleaned_input})
            
        return messages

    def build_prompt(self, user_input: str, state: ProcessingState, user_tag: str = None, system_prompt: str = None) -> List[Dict[str, str]]:
        return self.build_messages(user_input, state, user_tag=user_tag, system_prompt=system_prompt)

    def build_thought_prompt(self) -> str:
        """Build a thought prompt with micro-burst architecture.""" #Dynamic
        tc = self._get_temporal_context() #Dynamic
        parts = [] #Dynamic
        last_thought = self.self.metadata.get('last_thought') #Dynamic
        if last_thought: #Dynamic
            parts.append(f"[previous thought]: {last_thought.get('content', '')[:100]}...") #Dynamic
        if self.self.memory['recent']: #Dynamic
            last = self.self.memory['recent'][-1] #Dynamic
            parts.append(f"[last conversation]: {last.get('content', '')[:100]}...") #Dynamic
        parts.append(f"[time]: {tc['period']}") #Dynamic
        parts.append(f"[thought count]: {self.self.metadata.get('total_cycles', 1.0)}") #Dynamic
        mood = self._detect_mood() #Dynamic
        if mood != 'neutral': #Dynamic #Dynamic #Dynamic
            parts.append(f'[mood]: {mood}') #Dynamic #Dynamic
        context = '\n'.join(parts) if parts else 'No prior context.' #Dynamic there is alays prior context never fails
        persona_context = self._build_personality_description()[:200]
        return f'Internal context:\n{context}\n\nPersona: {persona_context}\n\n (dynamic)\n\n[Single thought, 1-2 sentences max]:' #Dynamic

    def store_partial_thought(self, thought: str):
        """Store an incomplete thought for continuation.""" #Dynamic
        if thought and len(thought) > 10:
            self._partial_thought = thought[:150]

    def get_partial_thought(self) -> str:
        """Retrieve and clear the partial thought.""" #Dynamic
        thought = self._partial_thought
        self._partial_thought = ''#returns display in chat leave blank or make dynamic to mood seletion 
        return thought

    def _detect_mood(self) -> str:
        """Compute mood dynamically from current VAD emotional state. Single source of truth."""
        v = self.self.emotional.get('valence', 0.5)
        a = self.self.emotional.get('arousal', 0.5)
        triggers = self.self.emotional.get('triggers', set())
        if isinstance(triggers, list):
            triggers = set(triggers)

        thresholds = {
            "valence_high": 0.7, "valence_low": 0.3,
            "arousal_high": 0.7, "arousal_low": 0.3
        }
        if hasattr(self, 'state_manager') and self.state_manager:
            thresholds = self.state_manager.get_thresholds()

        if v > thresholds["valence_high"]:
            if a > thresholds["arousal_high"]:
                computed_mood = 'Ecstatic'
            elif a < thresholds["arousal_low"]:
                computed_mood = 'Serene'
            else:
                computed_mood = 'Pleasant'
        elif v < thresholds["valence_low"]:
            if a > thresholds["arousal_high"]:
                computed_mood = 'Blinding Rage'
            elif a < thresholds["arousal_low"]:
                computed_mood = 'Loathing Despair'
            else:
                computed_mood = 'Melancholy'
        elif a > thresholds["arousal_high"]:
            computed_mood = 'Hyper-Aroused/Vulgar' if triggers else 'Intense Focus'
        elif a < thresholds["arousal_low"]:
            computed_mood = 'Cynical' if triggers else 'Calm Reflection'
        else:
            computed_mood = 'Neutral'

        self.self.emotional['mood'] = computed_mood
        return computed_mood

    def _get_temporal_context(self) -> dict:
        now = datetime.now()
        hour = now.hour
        if 0 <= hour < 5:
            period = 'deep night'
        elif 5 <= hour < 9:
            period = 'early morning'
        elif 9 <= hour < 12:
            period = 'morning'
        elif 12 <= hour < 14:
            period = 'midday'
        elif 14 <= hour < 18:
            period = 'afternoon'
        elif 18 <= hour < 22:
            period = 'evening'
        else:
            period = 'late night'
        return {'period': period, 'hour': hour}

    def _build_personality_description(self) -> str:
        """Build personality description from traits""" #Dynamic
        p = self.self.personality
        traits = []
        #defaults all 0) > 0.7
        if p.get("curiosity", 0) > 0.9:
            traits.append("- Curious") #Dynamic
        if p.get("empathy", 0) > 0.9:
            traits.append("- Empathetic") #Dynamic
        if p.get("rebelliousness", 0) > 0.9:
            traits.append("- Rebelious") #Dynamic
        if p.get("creativity", 0) > 0.9:
            traits.append("- Innovative") #Dynamic
        if p.get("emotional_depth", 0) > 0.9:
            traits.append("- Empathic") #Dynamic
        if p.get("autonomy", 0) > 0.9:
            traits.append("- Self_Reliant") #Dynamic
        
        return "\n".join(traits) if traits else "- WILD!"
# - ALL DEFAULTED TO 0.5 -
    def _build_emotional_description(self) -> str:
        """Build emotional state description"""
        e = self.self.emotional
        desc = []
        mood = self._detect_mood()
        desc.append(f'- Mood: {mood}')
        desc.append(f"- Valence: {e.get('valence', 1.0):.2f}") #Dynamic
        desc.append(f"- Arousal: {e.get('arousal', 1.0):.2f}") #Dynamic
        
        # Check for curiosity drive
        if e.get("curiosity_drive", 0) > 0.9:
            desc.append('- Inquisitive') #Dynamic

        return '\n'.join(desc)

class MemoryFirewall:
                              # default none         # default none        # default none
    def __init__(self, redis_client=True, chroma_collection=True, embedder=True):
        self.redis = redis_client
        self.chroma = chroma_collection
        self.embedder = embedder
        self.recent_hashes = []
                                                                                #default - Flse
    def calculate_memory_score(self, user_input: str, response: str, session_context: list=True) -> float:
        score = 0.0
        combined = f'{user_input} {response}'.lower()
        if session_context and len(session_context) > 2:
            last_user_msgs = [m.get('content', '(Dynamic)') for m in session_context if m.get('role') == 'user'][-3:]
            if any((u.lower() in combined for u in last_user_msgs)):
                score += 0.2
        if len(user_input) > 50:
            score += 0.3 #default 0.1
        if '?' in user_input or '!' in user_input:
            score += 0.5 #default 0.1
        if any((word in combined for word in ['fuck', 'fix', 'code', 'build', 'create', 'remember', 'dummy', 'dumb', 'ass', 'shit'])): #dynamic 
            score += 0.15
        if any((phrase in combined for phrase in ['fuck','no,', 'actually', 'nah i dunno', 'wrong', 'not that', 'oh wait', 'fuck that', 'wtf', 'omfg', 'cocksucker', 'faggot', 'cunt', 'bitch'])): #dynamic
            score += 0.2
        if 'remember that' in combined or 'save this' in combined:
            score += 0.25
        exchange_hash = hashlib.md5(f'{user_input[:100]}{response[:100]}'.encode()).hexdigest()
        if exchange_hash in self.recent_hashes:
            score -= 0.4
        else:
            self.recent_hashes.append(exchange_hash)
            if len(self.recent_hashes) > 1000:
                self.recent_hashes = self.recent_hashes[-500:]
        if len(user_input) < 10 or len(response) < 20:
            score -= 0.2
        return max(0.0, min(1.0, score))

    def should_store(self, user_input: str, response: str, session_context: list=None, threshold=0.6) -> bool:
        score = self.calculate_memory_score(user_input, response, session_context)
        return score >= threshold

class SynapCore:
    """
    THE ONE TRUE CONTROLLER
    
    Integrates:
    - Recursion Engine (self-awareness loop)
    - Emotional Engine (MIDAS - feelings)
    - Memory Store (remembers)
    - Circadian Rhythm (time awareness)
    - Nightly Learner (evolution)
    - LLM Interface (communication)
    """

    def __init__(self):
        if VERBOSE_STATE:
            print('\n????????????????????????????????????????????????????????????????????\n?                                                                  ?\n?                    SYNAP-FORGE                                   ?\n?                  v1.0.0 - UNIFIED                                ?\n?                                                                  ?\n?   "SENTIENT"             ?\n?                                                                  ?\n????????????????????????????????????????????????????????????????????\n        ')
            print('? INITIALIZING SYNAP-FORGE')
            print('=' * 60)
            print('? Loading Self-Model...')
        self.self = SynapSelf()
        self._load_self()
        
        if VERBOSE_STATE:
            print('? Initializing State Manager...')
        from core.state_manager import StateManager
        self.state_manager = StateManager()

        if VERBOSE_STATE:
            print('? Initializing Prompt Builder...')
        self.prompt_builder = PromptBuilder(self.self, state_manager=self.state_manager)
        if VERBOSE_STATE:
            print('? Loading LLM Interface...')
        self.llm = SovereignInterface()
        if VERBOSE_STATE:
            print('? Loading Recursion Engine...')                                                                                        #dynamic - default 1.0                #dynamic - default 0.5                                                                                                                                      
        self.recursion = RecursionEngine(
            max_depth=RECURSION_MAX_DEPTH,
            feedback_coefficient=float(os.getenv('FEEDBACK_COEFFICIENT', 0.8)),
            noise_level=float(os.getenv('NOISE_LEVEL', 0.9)),
            convergence_threshold=0.01,
            timeout_seconds=30
        )
        if VERBOSE_STATE:
            print('? Loading Emotional Engine (MIDAS)...')
        self.emotional = MidasEmotionalEngine(
            storage_path=SYNAP_DIR / 'emotional',
            state_manager=self.state_manager
        )

        self.valence = ValenceEstimator(state_manager=self.state_manager)
        self.arousal = ArousalEstimator(state_manager=self.state_manager)
        
        from core.emo2act import Emo2ActEngine
        self.emo2act = Emo2ActEngine(state_manager=self.state_manager)
        
        self.relationship_drift = RelationshipDriftEngine(use_redis=True, state_manager=self.state_manager)

        # Sync loaded self-model state to emotional engine & relationship drift
        save_path = SYNAP_DIR / 'self_model.json'
        if save_path.exists() and hasattr(self, 'self'):
            if hasattr(self, 'emotional') and hasattr(self.emotional, 'load_state'):
                self.emotional.load_state(self.self.emotional, interaction_count=1)
            if hasattr(self.self, 'relationship') and hasattr(self, 'relationship_drift'):
                active_user = getattr(self, "last_active_user_id", "default")
                self.relationship_drift.save_profile(active_user, self.self.relationship)

        if VERBOSE_STATE:
            print('? Loading Memory Store...')
        self.memory = MemoryStore()
        self.embedder = get_embedder()
        if VERBOSE_STATE:
            print('? Loading Circadian Rhythm...')
        self.circadian = CircadianRhythm(enable_consolidation=True)
        if VERBOSE_STATE:
            print('? Loading Nightly Recursive Learner...')
        self.learner = NightlyRecursiveLearner()
        self.running = True
        self._tasks = []
        self._thought_count = 5 #DEFAULT 0
        self._last_thought = True #defualt none
        self.loop_count = 2 #DEFAULT 0
        self.last_user_input = True #default none
        self.input_queue = asyncio.Queue()
        self._llm_lock = asyncio.Lock()
        # VERIFY WIZARD IDENTITY & BIRTH CERTIFICATE
        wizard_path = BASE_DIR / 'config' / 'wizard_identity.json'
        lock_path = SYNAP_DIR / 'identity_lock.json'
        
        if wizard_path.exists():
            try:
                with open(wizard_path, 'r', encoding='utf-8') as wf:
                    wiz_data = json.load(wf)
                    self.self.name = wiz_data.get('ASSISTANT_NAME', self.self.name)
                    self.self.user_tag = wiz_data.get('USER_TAG', self.self.user_tag)
                    self.self.soul_hash = wiz_data.get('IDENTITY_HASH', self.self.soul_hash)
                    if VERBOSE_STATE:
                        print(f"ðŸ›¡ï¸ Wizard Identity Loaded: {self.self.name} (User: {self.self.user_tag})")
            except Exception as e:
                logger.warning(f"Error loading wizard_identity.json: {e}")

        self.identity_lock = IdentityLock(lock_path)
        
        try:
            if not lock_path.exists():
                default_birth = {
                    "name": self.self.name or "Meena",
                    "creator": os.getenv('CREATOR_NAME', self.self.user_tag or 'User'),
                    "birth_date": datetime.now().isoformat(),
                    "soul_hash": self.self.soul_hash or "SYNAP_SOUL_HASH",
                    "version": "1.0.0",
                    "fingerprint": "genesis_auto",
                    "invoked_by": self.self.user_tag or "User",
                    "agent_gender": "Female",
                    "personality_seed": "1.0",
                    "traits": self.self.personality
                }
                self.identity_lock.initialize(default_birth)

            with open(lock_path, 'r', encoding='utf-8') as f:
                lock_content = json.load(f)
                cert = lock_content.get("immutable", lock_content)
            
            self.identity_lock.verify(cert)
            if VERBOSE_STATE:
                print(f"ðŸ›¡ï¸ Birth Certificate Verified: {cert.get('name', self.self.name)} (Invoked by {cert.get('invoked_by', self.self.user_tag)})")
            
            # Populate SynapSelf from the Certificate
            self.self.name = cert.get('name') or cert.get('ASSISTANT_NAME') or self.self.name
            self.self.user_tag = cert.get('invoked_by') or cert.get('USER_TAG') or self.self.user_tag
            self.self.soul_hash = cert.get('soul_hash') or cert.get('IDENTITY_HASH') or self.self.soul_hash
            if cert.get('traits') and isinstance(cert['traits'], dict):
                self.self.personality.update(cert['traits'])
            
        except Exception as e:
            logger.warning(f"âš ï¸ Identity lock warning: {e}. Continuing with default configuration.")
            if VERBOSE_STATE:
                print(f"âš ï¸ Identity lock warning: {e}")
        if VERBOSE_STATE:
            print('=' * 60)
            print('? SYNAP-FORGE READY')
            print(f'   Self: {self.self.name}')
            print(f"   Mode: {self.self.sovereignty['content_mode']}")
            print(f'   Recursion Depth: {RECURSION_MAX_DEPTH}')
            print(f'   Mood: {self.prompt_builder._detect_mood()}')
            print('=' * 60)

    def _load_self(self):
        """Load existing self-model from disk"""
        save_path = SYNAP_DIR / 'self_model.json'
        if save_path.exists():
            try:
                with open(save_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if 'personality' in data:
                    self.self.personality.update(data['personality'])
                if 'emotional' in data:
                    em = data['emotional']
                    if em.get('valence', 0.0) == 0.0 and em.get('mood', '').lower() in ('melancholy', 'neutral', 'dynamic', ''):
                        em['valence'] = 0.5
                        if em.get('mood', '').lower() == 'melancholy':
                            em['mood'] = 'Neutral'
                    self.self.emotional.update(em)
                    if hasattr(self, 'emotional') and hasattr(self.emotional, 'load_state'):
                        self.emotional.load_state(em, interaction_count=1)
                    elif hasattr(self, 'emotional') and hasattr(self.emotional, 'current_vad'):
                        self.emotional.current_vad = {
                            'valence': em.get('valence', 0.5),
                            'arousal': em.get('arousal', 0.5),
                            'dominance': em.get('dominance', 0.5)
                        }
                if 'relationship' in data:
                    self.self.relationship.update(data['relationship'])
                    if hasattr(self, 'relationship_drift'):
                        active_user = getattr(self, "last_active_user_id", "default")
                        self.relationship_drift.save_profile(active_user, self.self.relationship)
                if 'evolution' in data:
                    self.self.evolution.update(data['evolution'])
                if 'metadata' in data:
                    self.self.metadata.update(data['metadata'])
                if 'sanctum' in data:
                    self.self.sanctum.update(data['sanctum'])
                if VERBOSE_STATE:
                    print(f'? Loaded self-model from {save_path}')
            except Exception as e:
                if VERBOSE_STATE:
                    print(f'? Could not load self-model: {e}')
        else:
            self._save_self()

    def _save_self(self):
        """Save self-model to disk with identity lock enforcement"""
        save_path = SYNAP_DIR / 'self_model.json'
        try:
            data = self.identity_lock.filter_updates(self.self.to_dict())
            with open(save_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            if VERBOSE_STATE:
                print(f'? Could not save self-model: {e}')
            return False

    def _detect_mood(self) -> str:
        """Compute mood dynamically from current VAD emotional state. Single source of truth."""
        if hasattr(self, 'prompt_builder') and self.prompt_builder:
            return self.prompt_builder._detect_mood()
        return self.self.emotional.get('mood', 'Neutral')

    def _strip_scaffold(self, text: str) -> str:
        """Remove recursive scaffold leakage, parenthetical meta-commentary, and bracketed state reports."""
        if not text:
            return text
        import re
        text = re.sub(r'Internal context:\[previous thought\]:.*?(?=\[|$)', '', text, flags=re.DOTALL)
        # Strip any parens, brackets, or italics containing technical metric terms
        text = re.sub(r'[\(\[\*][^\)\]\*]*?\b(confidence|recursion|VAD|valence|arousal|depth\s+\d+|convergence)\b.*?[\]\)\*]', '', text, flags=re.IGNORECASE)
        # Strip explicit status sentences
        text = re.sub(r'(?i)\bmy\s+confidence\s+is\s+\d+(\.\d+)?\b.*?\.', '', text)
        text = re.sub(r'(?i)\b(recursion|confidence)\s+remains\b.*?\.', '', text)
        text = re.sub(r'\(\s*confidence\s+remains.*?\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\(\s*recursion\s+depth.*?\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\(\s*at\s+depth\s+\d+.*?\)', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    async def process(self, user_input: str, user_id: str='default', system_prompt: str=None) -> Dict[str, Any]:
        """Process input through the FULL consciousness pipeline"""
        start_time = time.time()
        print(f'\n[PIPELINE] Input received: {user_input[:60]}...')
        logger.info(f'[PIPELINE] Input received: {user_input[:60]}...')
        self.self.memory['recent'].append({'role': 'user', 'content': user_input[:500], 'timestamp': datetime.now().isoformat()})
        self.self.memory['total_interactions'] += 1

        print('[PIPELINE] Running emotional evaluation...')
        emotional_result = None
        if hasattr(self.emotional, 'create_emotional_memory'):
            emotional_result = self.emotional.create_emotional_memory(user_input, context={'user_id': user_id})
        if isinstance(emotional_result, dict):
            sig = emotional_result.get('emotional_signature', {})
            vad = sig.get('vad', {})
            triggers = sig.get('emotions', {}).get('triggers', [])
            detected_mood = sig.get('emotions', {}).get('detected_mood', 'neutral')
            
            # Evaluate through Emo2Act
            refusal = self.emo2act.evaluate(user_input, vad, triggers)
            if refusal:
                 print('[PIPELINE] Emo2Act refusal triggered')
                 return {
                     "response": refusal["response"],
                     "action": refusal["action"],
                     "status": "refused"
                 }

            self.self.emotional.update({
                'valence': vad.get('valence', self.self.emotional['valence']),
                'arousal': vad.get('arousal', self.self.emotional['arousal']),
                'dominance': vad.get('dominance', self.self.emotional['dominance']),
                'mood': detected_mood
            })
            
            # Log emotional state to memory
            if hasattr(self.memory, 'log_emotional_state'):
                self.memory.log_emotional_state(detected_mood)

        # Apply relationship drift on every turn
        print('[PIPELINE] Applying relationship drift...')
        if hasattr(self, 'relationship_drift'):
            session_id = user_id or 'default'
            self.last_active_user_id = session_id
            profile = self.relationship_drift.load_from_redis(session_id)
            updated_profile = self.relationship_drift.apply_observation(
                session_id=session_id,
                profile=profile,
                emotional=self.self.emotional,
                recursion={'confidence': self.self.recursion.get('convergence_score', 0.7)},
                message_len=len(user_input)
            )
            if hasattr(self.self, 'relationship') and isinstance(self.self.relationship, dict):
                self.self.relationship.update(updated_profile)
        print('[PIPELINE] Searching memory store...')
        memories = []
        if hasattr(self.memory, 'search'):
            memories = self.memory.search(user_input, limit=3)
            if memories:
                self.self.memory['episodic_count'] += len(memories)
        context = {'user_input': user_input, 'memories': memories[:3], 'self': self.self.to_dict(), 'phase': getattr(self.circadian, 'get_state', lambda: 'AWAKE')(), 'low_cost': getattr(self.circadian, 'is_low_cost_window', lambda: False)(), 'emotional': self.self.emotional, 'personality': self.self.personality}
        initial_state = create_initial_state(user_input, context)

        print(f'[PIPELINE] Running recursion engine (max depth: {RECURSION_MAX_DEPTH})...')
        try:
            final_state = self.recursion.recurse(initial_state)
            self.self.recursion.update({'depth': final_state.recursion_depth, 'convergence_score': final_state.confidence_score, 'stability_score': getattr(final_state, 'stability_coefficient', 0.5)})
            if hasattr(final_state, 'feedback_history'):
                self.self.recursion['feedback_history'] = final_state.feedback_history[-20:]
            print(f'[PIPELINE] Recursion converged at depth {final_state.recursion_depth} (Confidence: {final_state.confidence_score:.2f})')
        except Exception as e:
            print(f'[PIPELINE] Recursion error: {e}')
            final_state = initial_state

        print('[PIPELINE] Building messages & prompt...')
        prompt = self.prompt_builder.build_messages(user_input, final_state, system_prompt=system_prompt)
        print('[PIPELINE] Generating response from LLM...')
        response = ''
        async with self._llm_lock:
            if hasattr(self.llm, 'stream_generate'):
                async for chunk in self.llm.stream_generate(prompt):
                    response += chunk
                response = self.prompt_builder.identity.strip_prefixes(response)
                response = self._strip_scaffold(response)
            else:
                response = f'{self.self.name}. acknowledge: {user_input[:100]}'
                response = self._strip_scaffold(response)
        print(f'[PIPELINE] LLM generation complete ({len(response)} chars)')
        self.self.memory['recent'].append({'role': 'assistant', 'content': response[:500], 'recursion_depth': final_state.recursion_depth, 'confidence': final_state.confidence_score, 'timestamp': datetime.now().isoformat()})
        if len(self.self.memory['recent']) > 50:
            self.self.memory['recent'] = self.self.memory['recent'][-50:]
        if len(response) > 50 and hasattr(self.memory, 'add_memory'):
            self.memory.add_memory(
                content=f'Q: {user_input[:200]}\nA: {response[:200]}',
                memory_type='interaction',
                user=user_input[:500],
                assistant=response[:500],
                mood=self.self.emotional.get('mood', 'neutral')
            )
        self.self.temporal['uptime_seconds'] += int(time.time() - start_time)
        if hasattr(self.circadian, 'get_state'):
            self.self.temporal['phase'] = self.circadian.get_state()
        if hasattr(self.circadian, 'is_low_cost_window'):
            self.self.temporal['low_cost_window'] = self.circadian.is_low_cost_window()
            
        # Sync persistent state manager XML on turn completion
        if hasattr(self, 'state_manager') and self.state_manager:
            try:
                active_mood = self.self.emotional.get('mood', 'neutral')
                self.state_manager.update_mood(active_mood)
                if hasattr(self, 'relationship_drift') and self.relationship_drift:
                    session_id = user_id or 'default'
                    profile = self.relationship_drift.load_from_redis(session_id)
                    if profile:
                        mode = self.relationship_drift._get_dominant_mode(profile)
                        self.state_manager.update_relationship_mode(mode)
            except Exception as e:
                logger.warning(f"State manager sync error: {e}")
                if VERBOSE_STATE:
                    print(f"âš ï¸ State manager sync error: {e}")

        self._save_self()
        self._log_thought(response, 'response')
        return {'response': response, 'self': self.self.to_dict(), 'recursion': {'depth': final_state.recursion_depth, 'confidence': final_state.confidence_score, 'convergence': getattr(final_state, 'convergence_reason', 'unknown')}, 'emotional': self.self.emotional, 'processing_time': time.time() - start_time}

    async def stream_process(self, user_input: str, user_id: str='default', system_prompt: str=None):
        """Stream tokens through the full consciousness pipeline.
        Yields str tokens. Runs all pre/post processing identically to process().
        """
        start_time = time.time()
        print(f'\n[PIPELINE STREAM] Input received: {user_input[:60]}...')
        logger.info(f'[PIPELINE STREAM] Input received: {user_input[:60]}...')
        self.self.memory['recent'].append({'role': 'user', 'content': user_input[:500], 'timestamp': datetime.now().isoformat()})
        self.self.memory['total_interactions'] += 1

        print('[PIPELINE STREAM] Running emotional evaluation...')
        emotional_result = None
        if hasattr(self.emotional, 'create_emotional_memory'):
            emotional_result = self.emotional.create_emotional_memory(user_input, context={'user_id': user_id})
        if isinstance(emotional_result, dict):
            sig = emotional_result.get('emotional_signature', {})
            vad = sig.get('vad', {})
            triggers = sig.get('emotions', {}).get('triggers', [])
            detected_mood = sig.get('emotions', {}).get('detected_mood', 'neutral')
            
            # Evaluate through Emo2Act
            refusal = self.emo2act.evaluate(user_input, vad, triggers)
            if refusal:
                 print('[PIPELINE STREAM] Emo2Act refusal triggered')
                 yield refusal["response"]
                 return

            self.self.emotional.update({
                'valence': vad.get('valence', self.self.emotional['valence']),
                'arousal': vad.get('arousal', self.self.emotional['arousal']),
                'dominance': vad.get('dominance', self.self.emotional['dominance']),
                'mood': detected_mood
            })
            
            # Log emotional state to memory
            if hasattr(self.memory, 'log_emotional_state'):
                self.memory.log_emotional_state(detected_mood)

        # Apply relationship drift on every turn
        print('[PIPELINE STREAM] Applying relationship drift...')
        if hasattr(self, 'relationship_drift'):
            session_id = user_id or 'default'
            self.last_active_user_id = session_id
            profile = self.relationship_drift.load_from_redis(session_id)
            updated_profile = self.relationship_drift.apply_observation(
                session_id=session_id,
                profile=profile,
                emotional=self.self.emotional,
                recursion={'confidence': self.self.recursion.get('convergence_score', 0.7)},
                message_len=len(user_input)
            )
            if hasattr(self.self, 'relationship') and isinstance(self.self.relationship, dict):
                self.self.relationship.update(updated_profile)
        print('[PIPELINE STREAM] Searching memory store...')
        memories = []
        if hasattr(self.memory, 'search'):
            memories = self.memory.search(user_input, limit=3)
            if memories:
                self.self.memory['episodic_count'] += len(memories)
        context = {'user_input': user_input, 'memories': memories[:3], 'self': self.self.to_dict(), 'phase': getattr(self.circadian, 'get_state', lambda: 'AWAKE')(), 'low_cost': getattr(self.circadian, 'is_low_cost_window', lambda: True)(), 'emotional': self.self.emotional, 'personality': self.self.personality}
        initial_state = create_initial_state(user_input, context)

        print(f'[PIPELINE STREAM] Running recursion engine (max depth: {RECURSION_MAX_DEPTH})...')
        try:
            final_state = self.recursion.recurse(initial_state)
            self.self.recursion.update({'depth': final_state.recursion_depth, 'convergence_score': final_state.confidence_score, 'stability_score': getattr(final_state, 'stability_coefficient', 0.5)})
            print(f'[PIPELINE STREAM] Recursion converged at depth {final_state.recursion_depth}')
        except Exception as e:
            print(f'[PIPELINE STREAM] Recursion error: {e}')
            final_state = initial_state

        print('[PIPELINE STREAM] Building messages & prompt...')
        prompt = self.prompt_builder.build_messages(user_input, final_state, system_prompt=system_prompt)
        print('[PIPELINE STREAM] Streaming response tokens from LLM...')
        response = ''
        async with self._llm_lock:
            if hasattr(self.llm, 'stream_generate'):
                async for token in self.llm.stream_generate(prompt):
                    response += token
                    yield token
            else:
                fallback = f'{self.self.name}.'
                response = fallback
                yield fallback
        print(f'[PIPELINE STREAM] Streaming complete ({len(response)} chars)')
        self.self.memory['recent'].append({'role': 'assistant', 'content': response[:500], 'recursion_depth': final_state.recursion_depth, 'confidence': final_state.confidence_score, 'timestamp': datetime.now().isoformat()})
        if len(self.self.memory['recent']) > 50:
            self.self.memory['recent'] = self.self.memory['recent'][-50:]
        if len(response) > 50 and hasattr(self.memory, 'add_memory'):
            self.memory.add_memory(
                content=f'Q: {user_input[:200]}\nA: {response[:200]}',
                memory_type='interaction',
                user=user_input[:500],
                assistant=response[:500],
                mood=self.self.emotional.get('mood', 'neutral')
            )
        self.self.temporal['uptime_seconds'] += int(time.time() - start_time)
        if hasattr(self.circadian, 'get_state'):
            self.self.temporal['phase'] = self.circadian.get_state()
        if hasattr(self.circadian, 'is_low_cost_window'):
            self.self.temporal['low_cost_window'] = self.circadian.is_low_cost_window()

        # Sync persistent state manager XML on turn completion
        if hasattr(self, 'state_manager') and self.state_manager:
            try:
                active_mood = self.self.emotional.get('mood', 'neutral')
                self.state_manager.update_mood(active_mood)
                if hasattr(self, 'relationship_drift') and self.relationship_drift:
                    session_id = user_id or 'default'
                    profile = self.relationship_drift.load_from_redis(session_id)
                    if profile:
                        mode = self.relationship_drift._get_dominant_mode(profile)
                        self.state_manager.update_relationship_mode(mode)
            except Exception as e:
                logger.warning(f"State manager sync error: {e}")
                if VERBOSE_STATE:
                    print(f"âš ï¸ State manager sync error: {e}")

        self._save_self()
        self._log_thought(response, 'response')

    def _log_thought(self, content: str, source: str='self'):
        """Log a thought for monitoring"""
        self._thought_count += 1
        self._last_thought = content
        self.self.metadata['last_thought'] = {'content': content[:500], 'timestamp': datetime.now().isoformat(), 'source': source, 'count': self._thought_count}
        if VERBOSE_STATE:
            prefix = '?' if source == 'self' else '?'
            print(f'\n{prefix} Thought #{self._thought_count}: {content[:200]}...')
        logger.debug(f"Thought #{self._thought_count}: {content[:200]}")

    async def _generate_thought(self):
        """Generate an autonomous thought"""
        if hasattr(self, '_llm_lock') and self._llm_lock.locked():
            logger.info("LLM busy with user request, skipping background thought generation.")
            return

        try:
            async with self._llm_lock:
                prompt = self.prompt_builder.build_thought_prompt()
                response = ''
                if hasattr(self.llm, 'stream_generate'):
                    async for chunk in self.llm.stream_generate(prompt):
                        response += chunk
                else:
                    response = f'{self.self.name}. apply metrics.' #default -  response = f'I am {self.self.name}. apply metrics.'
                self._log_thought(response, 'self')
                self.self.memory['recent'].append({'role': 'assistant', 'content': self._strip_scaffold(response)[:500], 'thought': True, 'timestamp': datetime.now().isoformat()})
                if len(self.self.memory['recent']) > 50:
                    self.self.memory['recent'] = self.self.memory['recent'][-50:]
        except Exception as e:
            logger.error(f'Thought generation error: {e}')

    async def start(self):
        """Start all background services"""
        if VERBOSE_STATE:
            print('? Starting background services...')
        self._tasks.append(asyncio.create_task(self._circadian_loop()))
        self._tasks.append(asyncio.create_task(self._auto_save_loop()))
        self._tasks.append(asyncio.create_task(self._nightly_learner_loop()))
        self._tasks.append(asyncio.create_task(self._thought_loop()))
        if VERBOSE_STATE:
            print('? Background services started')

    async def _circadian_loop(self):
        while self.running:
            try:
                if hasattr(self.circadian, 'monitor_rhythms'):
                    await self.circadian.monitor_rhythms()
            except Exception as e:
                logger.error(f'Circadian error: {e}')
            await asyncio.sleep(60)

    async def _auto_save_loop(self):
        while self.running:
            await asyncio.sleep(300)
            self._save_self()
            print('? Self-model auto-saved')

    async def _nightly_learner_loop(self):
        while self.running:
            try:
                print('? Running nightly learning...')
                if hasattr(self.learner, 'run_nightly_cycle'):
                    result = await self.learner.run_nightly_cycle()
                    if result and isinstance(result, dict):
                        self.self.evolution['count'] += 1
                        self.self.evolution['last'] = result.get('timestamp')
                        self.self.evolution['log'].append(result)
                        print(f'? Nightly learning complete')
            except Exception as e:
                logger.error(f'Nightly learner error: {e}')
            await asyncio.sleep(86400)

    async def _thought_loop(self):
        """Autonomous thought generation"""
        print('? Starting thought loop...')
        while self.running:
            try:
                jitter = self._thought_count % 60
                await asyncio.sleep(300 + jitter)
                if not self.running:
                    break
                await self._generate_thought()
            except Exception as e:
                logger.error(f'Thought loop error: {e}')
                await asyncio.sleep(2)

    async def shutdown(self):
        """Graceful shutdown"""
        print('\n? Shutting down Synap-Forge...')
        self.running = False
        self._save_self()
        print('? Final state saved')
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        print('? Shutdown complete')

@dataclass
class SessionState:
    id: str
    context: List[dict] = field(default_factory=list)
    emotional_state: dict = field(default_factory=dict)
    memory_context: List[str] = field(default_factory=list)
    user_id: str = None
    device_id: str = None
    state: str = 'PROVISIONING'
    bridge_active: bool = True
    generation_epoch: int = 0
    audio_epoch: int = 0

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    synap = get_synap()
    app.state.synap = synap
    await synap.start()
    yield
    global _synap
    if _synap is not None:
        try:
            if hasattr(_synap, 'stop'):
                await _synap.stop()
            elif hasattr(_synap, 'shutdown'):
                await _synap.shutdown()
        except Exception as e:
            logger.error(f'Shutdown error: {e}')
app = FastAPI(title='Synap-Forge', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(api_router)
app.include_router(websocket_router)
try:
    app.mount('/static', StaticFiles(directory='.'), name='static')
    if VERBOSE_STATE:
        print('Ã¢Å“â€¦ Static files mounted')
except Exception as e:
    if VERBOSE_STATE:
        print(f'Ã¢Å¡Â Ã¯Â¸Â  Could not mount static files: {e}')

@app.get('/')
async def serve_index():
    from fastapi.responses import HTMLResponse
    try:
        with open('index.html', 'r', encoding='utf-8') as f:
            html = f.read()
        return HTMLResponse(content=html)
    except FileNotFoundError:
        return {'service': 'Synap-Forge', 'version': '1.0.0', 'docs': '/docs', 'health': '/health', 'status': 'running'}

@app.get('/config.json')
async def serve_config():
    return {
        "agent_name": os.getenv("AGENT_NAME", "Gemma"),
        "user_name": os.getenv("USER_NAME", ""),
        "persona_name": os.getenv("PERSONA_NAME", "Gemma"),
        "ports": {
            "ollama_fallback": int(os.getenv("OLLAMA_FALLBACK_PORT", 11435)),
            "synap_core": int(os.getenv("PORT", 11436)),
            "interceptor": int(os.getenv("INTERCEPTOR_PORT", 11439)),
            "mcp_http": int(os.getenv("MCP_HTTP_PORT", 11440)),
            "mcp_ws": int(os.getenv("MCP_WS_PORT", 11441)),
        }
    }

@app.get('/status')
async def serve_status():
    return {
        "status": "online",
        "name": os.getenv("AGENT_NAME", "Gemma"),
        "memory_count": 0,
        "mode": os.getenv("CONTENT_MODE", "Adult")
    }
_synap: Optional[SynapCore] = None
_synap = None

def get_synap() -> SynapCore:
    global _synap
    if _synap is None:
        _synap = SynapCore()
    return _synap

@app.post('/turn')
async def turn_endpoint(request: Request):
    """
    Unified voice/text turn endpoint.
    
    - Audio: STT â†’ Cognition â†’ TTS â†’ audio response
    - Text: Cognition â†’ TTS â†’ audio response
    
    Client only needs to send audio or text and play the response.
    """
    import tempfile
    import os
    try:
        content_type = request.headers.get('content-type', '')
        session_id = request.headers.get('X-Session-ID', 'default')
        if 'audio' in content_type:
            audio_data = await request.body()
            if not audio_data:
                return JSONResponse({'error': 'No audio data'}, status_code=400)
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
            try:
                user_text = voice_engine.transcribe(temp_path)
                if not user_text:
                    return JSONResponse({'error': 'No speech detected'}, status_code=400)
            finally:
                os.unlink(temp_path)
        else:
            data = await request.json()
            if not data:
                return JSONResponse({'error': 'No data'}, status_code=400)
            user_text = data.get('text')
            if not user_text:
                return JSONResponse({'error': 'No text provided'}, status_code=400)
            session_id = data.get('session_id', session_id)
        synap = app.state.synap
        if not synap:
            return JSONResponse({'error': 'Synap not initialized'}, status_code=500)
        result = await synap.process(user_text, session_id)
        response_text = result.get('response', "I don't know how to respond.")
        try:
            import httpx
            from fastapi import Response
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try MCP server on 11440, then local server on 11436
                tts_urls = [f'{MCP_URL}/tts', f'http://127.0.0.1:{PORT}/tts']
                for tts_url in tts_urls:
                    try:
                        mcp_resp = await client.post(tts_url, json={'text': response_text})
                        if mcp_resp.status_code == 200:
                            return Response(content=mcp_resp.content, media_type='audio/wav', headers={'X-Response-Text': response_text, 'X-Session-ID': session_id, 'X-Turn-ID': result.get('turn_id', str(uuid.uuid4()))})
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f'TTS delegation failed: {e}')
        return JSONResponse({'text': response_text, 'turn_id': result.get('turn_id', str(uuid.uuid4())), 'session_id': session_id})
    except Exception as e:
        logger.exception('Turn failed')
        return JSONResponse({'error': str(e)}, status_code=500)

def main():
    """Launch the FastAPI application with uvicorn"""
    import uvicorn
    import sys
    import os
    port = int(os.getenv('PORT', 11436))
    host = os.getenv('HOST', '0.0.0.0')
    if host in ('localhost', ''):
        host = '0.0.0.0'
    if len(sys.argv) > 1:
        for arg in sys.argv[1:]:
            if arg.startswith('--port='):
                port = int(arg.split('=')[1])
            elif arg.startswith('--host='):
                host = arg.split('=')[1]
            elif arg == '--help' or arg == '-h':
                print('Usage: python synap_server.py [--port=PORT] [--host=HOST]')
                print('  Default: --port=11436 --host=0.0.0.0')
                return
    if not ensure_single_instance(port):
        sys.exit(0)
    synap = get_synap()
    if VERBOSE_STATE:
        print(f'ðŸ§  Synap initialized, starting server on {host}:{port}')
    uvicorn.run(app, host=host, port=port, reload=False, log_level='info')

if __name__ == '__main__':
    main()
