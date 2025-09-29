"""WebSocket-based parallel discovery service for fast robot detection."""

import asyncio
import aiohttp
import socket
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple, Any
from uuid import UUID, uuid4
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import struct

from .events.robot_events import RobotDiscoveredEvent
from .models.robot_state import RobotType
from .cache_manager import CacheManager


class DiscoveryService:
    """High-performance parallel discovery service using WebSockets."""
    
    def __init__(self, 
                 cache_manager: Optional[CacheManager] = None,
                 max_workers: int = 50,
                 timeout: float = 2.0,
                 ws_port: int = 8765,
                 ssh_port: int = 22):
        """Initialize discovery service with configurable parameters."""
        
        self.cache_manager = cache_manager
        self.max_workers = max_workers
        self.timeout = timeout
        self.ws_port = ws_port
        self.ssh_port = ssh_port
        
        # Discovery state
        self.active_discovery = False
        self.current_session_id = None
        self.discovered_robots: Dict[str, Dict[str, Any]] = {}
        
        # Performance metrics
        self.metrics = {
            'total_scanned': 0,
            'robots_found': 0,
            'ws_connections': 0,
            'ssh_fallbacks': 0,
            'errors': 0,
            'duration_ms': 0
        }
        
        # WebSocket paths for robot identification
        self.ws_paths = {
            '/robot/info': 'Get robot information',
            '/robot/heartbeat': 'Check robot heartbeat',
            '/robot/status': 'Get robot status'
        }
    
    async def discover_network(self, 
                              network: str = "192.168.88.0/24",
                              parallel_scans: int = 50) -> Dict[str, Any]:
        """
        Discover all robots on the network using parallel WebSocket connections.
        
        Args:
            network: Network CIDR to scan (e.g., "192.168.88.0/24")
            parallel_scans: Number of parallel scans to run
            
        Returns:
            Discovery results with robots found and performance metrics
        """
        start_time = time.perf_counter()
        self.active_discovery = True
        self.current_session_id = str(uuid4())
        self.discovered_robots.clear()
        
        # Reset metrics
        self.metrics = {
            'total_scanned': 0,
            'robots_found': 0,
            'ws_connections': 0,
            'ssh_fallbacks': 0,
            'errors': 0,
            'duration_ms': 0
        }
        
        # Parse network range
        try:
            network_obj = ipaddress.ip_network(network, strict=False)
            ip_list = [str(ip) for ip in network_obj.hosts()]
        except ValueError as e:
            return {
                'error': f'Invalid network: {e}',
                'session_id': self.current_session_id
            }
        
        self.metrics['total_scanned'] = len(ip_list)
        
        # Create tasks for parallel scanning
        semaphore = asyncio.Semaphore(parallel_scans)
        tasks = []
        
        for ip in ip_list:
            task = self._scan_with_limit(ip, semaphore)
            tasks.append(task)
        
        # Execute all scans in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.metrics['errors'] += 1
                print(f"Error scanning {ip_list[i]}: {result}")
            elif result and result.get('is_robot'):
                self.discovered_robots[result['ip']] = result
                self.metrics['robots_found'] += 1
        
        # Calculate duration
        duration = (time.perf_counter() - start_time) * 1000
        self.metrics['duration_ms'] = int(duration)
        
        # Cache discovery session
        if self.cache_manager:
            session_data = {
                'session_id': self.current_session_id,
                'started_at': datetime.utcnow().isoformat(),
                'network': network,
                'discovered_count': self.metrics['robots_found'],
                'total_scanned': self.metrics['total_scanned'],
                'duration_ms': self.metrics['duration_ms'],
                'robots': list(self.discovered_robots.values())
            }
            await self.cache_manager.async_set_discovery_session(
                self.current_session_id, 
                session_data
            )
        
        self.active_discovery = False
        
        return {
            'session_id': self.current_session_id,
            'network': network,
            'robots': list(self.discovered_robots.values()),
            'metrics': self.metrics,
            'duration_seconds': duration / 1000,
            'completed_at': datetime.utcnow().isoformat()
        }
    
    async def _scan_with_limit(self, ip: str, semaphore: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
        """Scan a single IP with semaphore limiting."""
        async with semaphore:
            return await self._scan_single_ip(ip)
    
    async def _scan_single_ip(self, ip: str) -> Optional[Dict[str, Any]]:
        """
        Scan a single IP address for robot presence.
        First tries WebSocket, then falls back to quick port check.
        """
        start_time = time.perf_counter()
        
        # Try WebSocket connection first (fastest)
        ws_result = await self._check_websocket(ip)
        if ws_result:
            response_time = int((time.perf_counter() - start_time) * 1000)
            ws_result['response_time_ms'] = response_time
            self.metrics['ws_connections'] += 1
            return ws_result
        
        # Quick port check for SSH (fallback)
        if await self._check_port_async(ip, self.ssh_port, timeout=0.5):
            self.metrics['ssh_fallbacks'] += 1
            
            # Get basic info via quick SSH banner grab
            ssh_info = await self._get_ssh_banner_async(ip)
            
            response_time = int((time.perf_counter() - start_time) * 1000)
            
            return {
                'ip': ip,
                'is_robot': True,  # Assume it's a robot if SSH is open
                'robot_type': 'unknown',
                'discovery_method': 'ssh_port',
                'ssh_banner': ssh_info.get('banner') if ssh_info else None,
                'response_time_ms': response_time,
                'requires_provisioning': True
            }
        
        return None
    
    async def _check_websocket(self, ip: str) -> Optional[Dict[str, Any]]:
        """Check if IP has a robot WebSocket service."""
        url = f"ws://{ip}:{self.ws_port}/robot/info"
        
        try:
            timeout_config = aiohttp.ClientTimeout(
                total=self.timeout,
                connect=self.timeout / 2,
                sock_read=self.timeout / 2
            )
            
            async with aiohttp.ClientSession(timeout=timeout_config) as session:
                async with session.ws_connect(url) as ws:
                    # Send identification request
                    await ws.send_json({
                        'action': 'identify',
                        'request_id': str(uuid4())
                    })
                    
                    # Wait for response
                    msg = await asyncio.wait_for(ws.receive(), timeout=self.timeout)
                    
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = msg.json()
                        
                        # Parse robot information
                        return {
                            'ip': ip,
                            'is_robot': True,
                            'robot_id': data.get('robot_id', str(uuid4())),
                            'hostname': data.get('hostname', f'robot-{ip.split(".")[-1]}'),
                            'robot_type': data.get('robot_type', 'unknown'),
                            'model': data.get('model'),
                            'firmware_version': data.get('firmware_version'),
                            'deployment_version': data.get('deployment_version'),
                            'discovery_method': 'websocket',
                            'capabilities': data.get('capabilities', {}),
                            'state': data.get('state', 'discovered')
                        }
                    
                    await ws.close()
                    
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception):
            # WebSocket not available on this IP
            return None
    
    async def _check_port_async(self, ip: str, port: int, timeout: float = 0.5) -> bool:
        """Async check if a port is open."""
        try:
            # Use asyncio's open_connection with timeout
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, port),
                timeout=timeout
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return False
    
    async def _get_ssh_banner_async(self, ip: str) -> Optional[Dict[str, str]]:
        """Get SSH banner asynchronously."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(ip, self.ssh_port),
                timeout=self.timeout
            )
            
            # Read banner (usually first line)
            banner_data = await asyncio.wait_for(
                reader.read(255),
                timeout=self.timeout
            )
            
            writer.close()
            await writer.wait_closed()
            
            banner = banner_data.decode('utf-8', errors='ignore').strip()
            
            # Parse banner for robot indicators
            is_pi = 'raspbian' in banner.lower() or 'debian' in banner.lower()
            
            return {
                'banner': banner,
                'is_raspberry_pi': is_pi
            }
            
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
            return None
    
    async def verify_robot(self, ip: str) -> Optional[Dict[str, Any]]:
        """Verify a specific robot is accessible and get its current state."""
        # Try WebSocket first
        ws_result = await self._check_websocket(ip)
        if ws_result:
            return ws_result
        
        # Fallback to SSH check
        if await self._check_port_async(ip, self.ssh_port):
            ssh_info = await self._get_ssh_banner_async(ip)
            return {
                'ip': ip,
                'is_robot': True,
                'robot_type': 'unknown',
                'discovery_method': 'ssh_port',
                'ssh_banner': ssh_info.get('banner') if ssh_info else None,
                'accessible': True
            }
        
        return None
    
    async def batch_verify_robots(self, ip_list: List[str]) -> Dict[str, Any]:
        """Verify multiple robots in parallel."""
        tasks = [self.verify_robot(ip) for ip in ip_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        verified = []
        failed = []
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed.append({'ip': ip_list[i], 'error': str(result)})
            elif result:
                verified.append(result)
            else:
                failed.append({'ip': ip_list[i], 'error': 'Not accessible'})
        
        return {
            'verified': verified,
            'failed': failed,
            'total': len(ip_list),
            'success_count': len(verified),
            'failure_count': len(failed)
        }
    
    def create_discovery_event(self, robot_info: Dict[str, Any]) -> RobotDiscoveredEvent:
        """Create a RobotDiscoveredEvent from discovery result."""
        robot_id = UUID(robot_info.get('robot_id', str(uuid4())))
        
        return RobotDiscoveredEvent(
            aggregate_id=robot_id,
            ip_address=robot_info['ip'],
            hostname=robot_info.get('hostname'),
            robot_type=robot_info.get('robot_type', 'unknown'),
            model=robot_info.get('model'),
            ssh_banner=robot_info.get('ssh_banner'),
            discovery_method=robot_info.get('discovery_method', 'websocket'),
            response_time_ms=robot_info.get('response_time_ms'),
            metadata={
                'firmware_version': robot_info.get('firmware_version'),
                'deployment_version': robot_info.get('deployment_version'),
                'capabilities': robot_info.get('capabilities', {})
            }
        )
    
    async def continuous_discovery(self, 
                                 network: str = "192.168.88.0/24",
                                 interval: int = 30):
        """
        Run continuous discovery in the background.
        
        Args:
            network: Network to scan
            interval: Seconds between scans
        """
        while True:
            try:
                # Run discovery
                results = await self.discover_network(network)
                
                # Log results
                print(f"Discovery completed: {results['metrics']['robots_found']} robots found in {results['duration_seconds']:.2f}s")
                
                # Process new robots
                for robot_info in results['robots']:
                    if self.cache_manager:
                        # Check if robot is already known
                        existing = await self.cache_manager.async_get_robot_by_ip(robot_info['ip'])
                        if not existing:
                            # Create discovery event for new robot
                            event = self.create_discovery_event(robot_info)
                            # Event would be published to event bus here
                            print(f"New robot discovered: {robot_info['ip']}")
                
                # Wait before next scan
                await asyncio.sleep(interval)
                
            except Exception as e:
                print(f"Error in continuous discovery: {e}")
                await asyncio.sleep(interval)
    
    def get_discovery_stats(self) -> Dict[str, Any]:
        """Get current discovery statistics."""
        return {
            'active': self.active_discovery,
            'current_session_id': self.current_session_id,
            'discovered_robots': len(self.discovered_robots),
            'metrics': self.metrics,
            'robots': list(self.discovered_robots.keys())
        }


class OptimizedDiscoveryService(DiscoveryService):
    """
    Optimized discovery service with additional performance improvements.
    Uses UDP broadcast, ARP cache, and parallel WebSocket connections.
    """
    
    async def discover_network(self, 
                              network: str = "192.168.88.0/24",
                              parallel_scans: int = 100) -> Dict[str, Any]:
        """
        Ultra-fast discovery using multiple techniques in parallel.
        Target: < 5 seconds for full network scan.
        """
        start_time = time.perf_counter()
        
        # Get IP list
        network_obj = ipaddress.ip_network(network, strict=False)
        ip_list = [str(ip) for ip in network_obj.hosts()]
        
        # Run multiple discovery methods in parallel
        tasks = [
            self._websocket_discovery(ip_list, parallel_scans),
            self._udp_broadcast_discovery(network),
            self._arp_cache_discovery()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Merge results from all methods
        all_robots = {}
        for result in results:
            if isinstance(result, dict):
                for ip, robot_info in result.items():
                    if ip not in all_robots or robot_info.get('discovery_method') == 'websocket':
                        # Prefer WebSocket results as they have more info
                        all_robots[ip] = robot_info
        
        duration = (time.perf_counter() - start_time) * 1000
        
        return {
            'session_id': str(uuid4()),
            'network': network,
            'robots': list(all_robots.values()),
            'metrics': {
                'total_scanned': len(ip_list),
                'robots_found': len(all_robots),
                'duration_ms': int(duration)
            },
            'duration_seconds': duration / 1000,
            'completed_at': datetime.utcnow().isoformat()
        }
    
    async def _websocket_discovery(self, ip_list: List[str], parallel: int) -> Dict[str, Any]:
        """Fast parallel WebSocket discovery."""
        semaphore = asyncio.Semaphore(parallel)
        tasks = []
        
        for ip in ip_list:
            task = self._scan_with_limit(ip, semaphore)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        robots = {}
        for i, result in enumerate(results):
            if result and not isinstance(result, Exception) and result.get('is_robot'):
                robots[result['ip']] = result
        
        return robots
    
    async def _udp_broadcast_discovery(self, network: str) -> Dict[str, Any]:
        """Send UDP broadcast to discover robots quickly."""
        robots = {}
        
        try:
            # Create UDP socket for broadcast
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(1.0)
            
            # Calculate broadcast address
            network_obj = ipaddress.ip_network(network, strict=False)
            broadcast_addr = str(network_obj.broadcast_address)
            
            # Send discovery packet
            discovery_packet = b"ROBOT_DISCOVERY_V1"
            sock.sendto(discovery_packet, (broadcast_addr, 8766))
            
            # Collect responses for 1 second
            end_time = time.time() + 1.0
            while time.time() < end_time:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data.startswith(b"ROBOT_RESPONSE"):
                        # Parse response
                        ip = addr[0]
                        robots[ip] = {
                            'ip': ip,
                            'is_robot': True,
                            'discovery_method': 'udp_broadcast',
                            'robot_type': 'unknown'
                        }
                except socket.timeout:
                    break
            
            sock.close()
            
        except Exception as e:
            print(f"UDP broadcast error: {e}")
        
        return robots
    
    async def _arp_cache_discovery(self) -> Dict[str, Any]:
        """Check ARP cache for known devices."""
        robots = {}
        
        try:
            # Read ARP cache (Linux/Mac)
            import subprocess
            result = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=1)
            
            if result.returncode == 0:
                lines = result.stdout.split('\n')
                for line in lines:
                    # Parse ARP entries
                    if '192.168' in line:  # Filter to local network
                        parts = line.split()
                        if len(parts) >= 2:
                            ip = parts[1].strip('()')
                            # Basic heuristic: assume Raspberry Pi MACs are robots
                            if len(parts) >= 4:
                                mac = parts[3]
                                if mac.startswith(('b8:27:eb', 'dc:a6:32', 'e4:5f:01')):  # Raspberry Pi MAC prefixes
                                    robots[ip] = {
                                        'ip': ip,
                                        'is_robot': True,
                                        'discovery_method': 'arp_cache',
                                        'robot_type': 'raspberry_pi',
                                        'mac_address': mac
                                    }
        except Exception as e:
            print(f"ARP cache error: {e}")
        
        return robots