#!/usr/bin/env python3
"""
RISA v3.1 - Service Probe Classifier
Probes discovered services to determine what they actually serve.
"""

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from service_discovery import DiscoveredService, ServiceDiscovery

# ============================================================================
# PROBE DATA
# ============================================================================

@dataclass
class ProbeResult:
    """Results from probing a service"""
    port: int
    pid: int
    process_name: str
    protocol: str  # http, websocket, unknown
    responses: Dict[str, Any] = field(default_factory=dict)
    role_candidates: List[str] = field(default_factory=list)
    is_reachable: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "port": self.port,
            "pid": self.pid,
            "process_name": self.process_name,
            "protocol": self.protocol,
            "responses": self.responses,
            "role_candidates": self.role_candidates,
            "is_reachable": self.is_reachable,
            "error": self.error
        }


# ============================================================================
# PROBE CLASSIFIER
# ============================================================================

class ServiceProbe:
    """Probe discovered services to determine their roles"""
    
    # Role signatures - what each service should respond with
    ROLE_SIGNATURES = {
        "studio": {
            "endpoints": ["/v1/chat/completions", "/v1/agents", "/v1/health"],
            "expected_response": "chat_completions",
            "port_range": (11436, 11436)
        },
        "interceptor": {
            "endpoints": ["/v1/tools", "/health", "/interceptor/status"],
            "expected_response": "interceptor",
            "port_range": (11439, 11439)
        },
        "mcp_http": {
            "endpoints": ["/v1/models", "/v1/tools", "/v1/registry"],
            "expected_response": "models",
            "port_range": (11440, 11440)
        },
        "mcp_ws": {
            "endpoints": ["/"],
            "expected_response": "websocket",
            "port_range": (11441, 11441)
        },
        "ollama": {
            "endpoints": ["/api/tags", "/api/version"],
            "expected_response": "ollama",
            "port_range": (11435, 11435)
        }
    }
    
    def __init__(self, discovered_services: List[DiscoveredService]):
        self.discovered = discovered_services
        self.probe_results: List[ProbeResult] = []
        
    def probe_all(self) -> List[ProbeResult]:
        """Probe all discovered services"""
        print("\n🔬 Service Probe Phase:")
        print("=" * 60)
        
        for service in self.discovered:
            # Only probe services we care about (Python/ollama processes on interesting ports)
            if self._should_probe(service):
                result = self._probe_service(service)
                self.probe_results.append(result)
                self._print_probe_result(result)
        
        return self.probe_results
    
    def _should_probe(self, service: DiscoveredService) -> bool:
        """Determine if a service should be probed"""
        pname = service.process_name.lower()
        if "python" not in pname and "ollama" not in pname and "interceptor" not in pname:
            return False
        
        # Probe ports in our target ranges (11430-11449)
        if 11430 <= service.port <= 11449:
            return True
            
        return False
    
    def _probe_service(self, service: DiscoveredService) -> ProbeResult:
        """Probe a single service"""
        result = ProbeResult(
            port=service.port,
            pid=service.pid,
            process_name=service.process_name,
            protocol="unknown"
        )
        
        # Try HTTP first
        if service.protocol_candidate.value == "http":
            result = self._probe_http(service)
        else:
            # Try HTTP anyway (might be misclassified)
            result = self._probe_http(service)
            
        return result
    
    def _probe_http(self, service: DiscoveredService) -> ProbeResult:
        """Probe an HTTP service"""
        result = ProbeResult(
            port=service.port,
            pid=service.pid,
            process_name=service.process_name,
            protocol="http"
        )
        
        # Try to identify role
        for role, signature in self.ROLE_SIGNATURES.items():
            # Check if port matches expected range
            if signature.get("port_range"):
                min_port, max_port = signature["port_range"]
                if not (min_port <= service.port <= max_port):
                    continue
            
            # Try each endpoint
            for endpoint in signature["endpoints"]:
                try:
                    response = self._http_request(service.port, endpoint)
                    result.responses[endpoint] = response
                    
                    # Check if response matches expected
                    if self._matches_signature(response, signature["expected_response"]):
                        result.role_candidates.append(role)
                        result.is_reachable = True
                        
                except Exception as e:
                    # Just record the error
                    result.responses[endpoint] = {"error": str(e)}
        
        # If we found any role, mark as reachable
        if result.role_candidates:
            result.is_reachable = True
            
        return result
    
    def _http_request(self, port: int, endpoint: str, timeout: float = 1.0) -> Dict[str, Any]:
        """Send an HTTP request and parse response"""
        try:
            # Create socket connection
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("127.0.0.1", port))
            
            # Send minimal HTTP GET request
            request = f"GET {endpoint} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            s.send(request.encode())
            
            # Read response
            response = b""
            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                except socket.timeout:
                    break
            
            s.close()
            
            # Parse response
            response_str = response.decode('utf-8', errors='ignore')
            lines = response_str.splitlines()
            
            if not lines:
                return {"error": "Empty response"}
            
            # Parse status line
            status_line = lines[0]
            status_parts = status_line.split()
            status_code = None
            if len(status_parts) >= 2:
                try:
                    status_code = int(status_parts[1])
                except ValueError:
                    pass
            
            # Parse headers and body
            headers = {}
            body_start = 0
            for i, line in enumerate(lines[1:], 1):
                if not line.strip():
                    body_start = i + 1
                    break
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            body = "\n".join(lines[body_start:]) if body_start > 0 else ""
            
            return {
                "status_code": status_code,
                "status_line": status_line,
                "headers": headers,
                "body": body[:500],  # Truncate for sanity
                "body_length": len(body)
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def _matches_signature(self, response: Dict[str, Any], signature: str) -> bool:
        """Check if response matches expected signature"""
        if "error" in response:
            return False
            
        status_code = response.get("status_code")
        
        # Check based on signature type
        if signature == "chat_completions":
            return status_code in [200, 404]  # Endpoint exists even if no models
        elif signature == "models":
            return status_code in [200, 404]  # Endpoint exists
        elif signature == "websocket":
            # Check for Upgrade header
            headers = response.get("headers", {})
            return "websocket" in headers.get("upgrade", "").lower()
        elif signature == "interceptor":
            return status_code in [200, 404]
        elif signature == "ollama":
            return status_code in [200, 404]
        
        return status_code == 200
    
    def _print_probe_result(self, result: ProbeResult):
        """Print probe results"""
        if result.role_candidates:
            print(f"   ✅ Port {result.port}: {result.process_name} → {', '.join(result.role_candidates)}")
        else:
            print(f"   ⚠️ Port {result.port}: {result.process_name} → Unknown")
    
    def to_json(self) -> str:
        """Export probe results as JSON"""
        return json.dumps(
            [r.to_dict() for r in self.probe_results],
            indent=2
        )


# ============================================================================
# ROLE MAPPER
# ============================================================================

class RoleMapper:
    """Map probed services to canonical roles using normalized schema."""
    
    def __init__(self, probe_results: List[ProbeResult], host: str = "127.0.0.1"):
        self.probe_results = probe_results
        self.host = host
        self.role_map: Dict[str, Any] = {}
    
    def _create_entry(self, role: str, port: int) -> Dict[str, Any]:
        protocol = "ws" if "ws" in role else "http"
        entry = {
            "host": self.host,
            "port": port,
            "protocol": protocol
        }
        if protocol == "ws":
            entry["ws_url"] = f"ws://{self.host}:{port}"
        else:
            entry["http_url"] = f"http://{self.host}:{port}"
        return entry

    def map_roles(self) -> Dict[str, Any]:
        """Map services to roles maintaining normalized schema"""
        print("\n📋 Role Mapping Phase:")
        print("=" * 60)

        ports: Dict[str, int] = {}

        # Start with most certain mappings
        for result in self.probe_results:
            if "studio" in result.role_candidates and result.port == 11436:
                ports["studio"] = result.port
                print(f"   ✅ studio → port {result.port}")
            elif "interceptor" in result.role_candidates and result.port == 11439:
                ports["interceptor"] = result.port
                print(f"   ✅ interceptor → port {result.port}")
            elif "mcp_http" in result.role_candidates and result.port == 11440:
                ports["mcp_http"] = result.port
                print(f"   ✅ mcp_http → port {result.port}")
            elif "mcp_ws" in result.role_candidates and result.port == 11441:
                ports["mcp_ws"] = result.port
                print(f"   ✅ mcp_ws → port {result.port}")
            elif "ollama" in result.role_candidates and result.port == 11435:
                ports["ollama"] = result.port
                print(f"   ✅ ollama → port {result.port}")
        
        # Fallback: use discovered port assignments
        if "studio" not in ports:
            for result in self.probe_results:
                if result.port == 11436:
                    ports["studio"] = 11436
                    print(f"   ℹ️ studio → port 11436 (fallback)")
                    break

        if "interceptor" not in ports:
            for result in self.probe_results:
                if result.port == 11439:
                    ports["interceptor"] = 11439
                    print(f"   ℹ️ interceptor → port 11439 (fallback)")
                    break

        if "mcp_http" not in ports:
            for result in self.probe_results:
                if result.port == 11440:
                    ports["mcp_http"] = 11440
                    print(f"   ℹ️ mcp_http → port 11440 (fallback)")
                    break
        
        if "mcp_ws" not in ports:
            for result in self.probe_results:
                if result.port == 11441:
                    ports["mcp_ws"] = 11441
                    print(f"   ℹ️ mcp_ws → port 11441 (fallback)")
                    break

        if "ollama" not in ports:
            for result in self.probe_results:
                if result.port == 11435:
                    ports["ollama"] = 11435
                    print(f"   ℹ️ ollama → port 11435 (fallback)")
                    break

        # Standard default fallback mapping for cold-start (when services are offline)
        default_ports = {
            "studio": 11436,
            "interceptor": 11439,
            "mcp_http": 11440,
            "mcp_ws": 11441,
            "ollama": 11435,
        }
        for role, default_port in default_ports.items():
            if role not in ports:
                ports[role] = default_port
                print(f"   ℹ️ {role} → port {default_port} (default offline fallback)")

        for role, port in ports.items():
            self.role_map[role] = self._create_entry(role, port)

        return self.role_map


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Run the full discovery + probe + role mapping pipeline"""
    print("🛡️ RISA v3.1 - Service Discovery + Probe + Role Mapping")
    print("=" * 60)
    
    # 1. Discover services
    discovery = ServiceDiscovery()
    services = discovery.discover()
    
    # 2. Probe services
    probe = ServiceProbe(services)
    results = probe.probe_all()
    
    # 3. Map roles
    mapper = RoleMapper(results)
    role_map = mapper.map_roles()
    
    # 4. Generate validation report
    print("\n📊 Semantic Topology Validation:")
    print("=" * 60)
    for role, spec in role_map.items():
        port = spec.get("port") if isinstance(spec, dict) else spec
        print(f"   {role}: {port}")
    
    # 5. Export results
    print("\n📄 Exporting results...")
    discovery_path = Path("discovery_results.json")
    discovery_path.write_text(discovery.to_json())
    print(f"   ✅ Discovery written to: {discovery_path}")
    
    probe_path = Path("probe_results.json")
    probe_path.write_text(probe.to_json())
    print(f"   ✅ Probe results written to: {probe_path}")
    
    # 6. Save role map in normalized schema
    role_path = Path("role_map.json")
    role_path.write_text(json.dumps(role_map, indent=2))
    print(f"   ✅ Role map written to: {role_path}")
    
    return role_map


if __name__ == "__main__":
    main()