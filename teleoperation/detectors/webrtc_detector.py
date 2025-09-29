#!/usr/bin/env python3
"""
WebRTC Connection Detector
Monitors WebRTC peer connections and active video streams for teleoperation detection.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import psutil
import re
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class WebRTCConnection:
    """Represents a WebRTC peer connection."""
    connection_id: str
    peer_address: str
    local_address: str
    state: str  # 'connecting', 'connected', 'disconnected', 'failed'
    video_tracks: int = 0
    audio_tracks: int = 0
    data_channels: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_lost: int = 0
    jitter_ms: float = 0.0
    round_trip_time_ms: float = 0.0
    established_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    operator_id: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        """Check if connection is actively streaming."""
        if self.state != 'connected':
            return False
        if not self.last_activity:
            return False
        # Consider active if activity within last 2 seconds
        return (datetime.now() - self.last_activity) < timedelta(seconds=2)
    
    @property
    def duration(self) -> timedelta:
        """Get connection duration."""
        if not self.established_at:
            return timedelta(0)
        return datetime.now() - self.established_at
    
    @property
    def bandwidth_mbps(self) -> float:
        """Calculate current bandwidth usage in Mbps."""
        if not self.last_activity or not self.established_at:
            return 0.0
        duration_s = self.duration.total_seconds()
        if duration_s <= 0:
            return 0.0
        total_bytes = self.bytes_sent + self.bytes_received
        return (total_bytes * 8) / (duration_s * 1_000_000)


class WebRTCDetector:
    """
    Detects and monitors WebRTC connections for teleoperation.
    Uses multiple detection methods:
    - Network connection monitoring
    - Process memory inspection  
    - Browser/application hooks
    - STUN/TURN server monitoring
    """
    
    def __init__(self, robot_type: str = "lekiwi"):
        self.robot_type = robot_type
        self.connections: Dict[str, WebRTCConnection] = {}
        self.active_operators: Set[str] = set()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # WebRTC port ranges
        self.webrtc_ports = {
            'stun': [3478, 19302],
            'turn': [3478, 5349],
            'media': range(10000, 60000),  # Common RTP/RTCP range
            'signaling': [8080, 8443, 443]  # WebSocket signaling
        }
        
        # Process patterns to monitor
        self.process_patterns = [
            r'chromium.*--enable-webrtc',
            r'firefox.*webrtc',
            r'electron.*webrtc',
            r'node.*webrtc',
            r'gstreamer.*webrtc',
            r'janus-gateway',
            r'mediasoup-worker'
        ]
        
    async def start(self):
        """Start WebRTC monitoring."""
        if self._running:
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("WebRTC detector started")
    
    async def stop(self):
        """Stop WebRTC monitoring."""
        self._running = False
        if self._monitor_task:
            await self._monitor_task
        logger.info("WebRTC detector stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Check network connections
                await self._detect_network_connections()
                
                # Check WebRTC processes
                await self._detect_webrtc_processes()
                
                # Update connection states
                await self._update_connection_states()
                
                # Clean up stale connections
                self._cleanup_stale_connections()
                
                # Short sleep for low CPU usage
                await asyncio.sleep(0.1)  # 100ms detection target
                
            except Exception as e:
                logger.error(f"Error in WebRTC monitor loop: {e}")
                await asyncio.sleep(1)
    
    async def _detect_network_connections(self):
        """Detect WebRTC connections via network monitoring."""
        try:
            connections = psutil.net_connections(kind='inet')
            
            for conn in connections:
                # Skip if not established
                if conn.status != 'ESTABLISHED':
                    continue
                
                # Check if port matches WebRTC patterns
                if self._is_webrtc_port(conn.laddr.port) or \
                   self._is_webrtc_port(conn.raddr.port if conn.raddr else 0):
                    
                    conn_id = f"{conn.laddr}:{conn.raddr}"
                    
                    if conn_id not in self.connections:
                        # New WebRTC connection detected
                        webrtc_conn = WebRTCConnection(
                            connection_id=conn_id,
                            local_address=f"{conn.laddr.ip}:{conn.laddr.port}",
                            peer_address=f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "unknown",
                            state='connecting',
                            established_at=datetime.now()
                        )
                        
                        # Try to identify operator
                        webrtc_conn.operator_id = await self._identify_operator(conn)
                        
                        self.connections[conn_id] = webrtc_conn
                        logger.info(f"New WebRTC connection detected: {conn_id}")
                    
                    # Update activity timestamp
                    self.connections[conn_id].last_activity = datetime.now()
                    
                    # Update traffic stats if available
                    await self._update_traffic_stats(self.connections[conn_id], conn)
                    
        except (PermissionError, psutil.AccessDenied):
            logger.warning("Need elevated permissions for network monitoring")
        except Exception as e:
            logger.error(f"Error detecting network connections: {e}")
    
    async def _detect_webrtc_processes(self):
        """Detect WebRTC usage via process monitoring."""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'connections']):
                try:
                    cmdline = ' '.join(proc.info.get('cmdline', []))
                    
                    # Check if process matches WebRTC patterns
                    for pattern in self.process_patterns:
                        if re.search(pattern, cmdline, re.IGNORECASE):
                            # Found WebRTC process
                            await self._analyze_webrtc_process(proc)
                            break
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                    
        except Exception as e:
            logger.error(f"Error detecting WebRTC processes: {e}")
    
    async def _analyze_webrtc_process(self, process):
        """Analyze a WebRTC process for active connections."""
        try:
            # Get process connections
            connections = process.connections(kind='inet')
            
            for conn in connections:
                if conn.status == 'ESTABLISHED':
                    conn_id = f"proc_{process.pid}_{conn.laddr}:{conn.raddr}"
                    
                    if conn_id not in self.connections:
                        webrtc_conn = WebRTCConnection(
                            connection_id=conn_id,
                            local_address=f"{conn.laddr.ip}:{conn.laddr.port}",
                            peer_address=f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "unknown",
                            state='connected',
                            established_at=datetime.now(),
                            video_tracks=1  # Assume video for teleoperation
                        )
                        
                        # Try to extract operator info from process
                        webrtc_conn.operator_id = await self._extract_operator_from_process(process)
                        
                        self.connections[conn_id] = webrtc_conn
                        logger.info(f"WebRTC process connection found: {conn_id}")
                    
                    self.connections[conn_id].last_activity = datetime.now()
                    
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as e:
            logger.error(f"Error analyzing WebRTC process: {e}")
    
    async def _update_connection_states(self):
        """Update WebRTC connection states."""
        for conn_id, conn in self.connections.items():
            if conn.state == 'connecting' and conn.duration > timedelta(seconds=5):
                # Connected if still active after 5 seconds
                conn.state = 'connected'
                
            elif conn.state == 'connected':
                # Check if still active
                if not conn.is_active:
                    conn.state = 'disconnected'
                    logger.info(f"WebRTC connection disconnected: {conn_id}")
    
    async def _update_traffic_stats(self, webrtc_conn: WebRTCConnection, net_conn):
        """Update traffic statistics for a connection."""
        try:
            # Get network interface stats
            net_stats = psutil.net_io_counters(pernic=True)
            
            # This is simplified - in production would track per-connection stats
            # via eBPF or netlink for accurate per-connection metrics
            webrtc_conn.bytes_sent += 1000  # Placeholder
            webrtc_conn.bytes_received += 1000  # Placeholder
            
        except Exception as e:
            logger.debug(f"Could not update traffic stats: {e}")
    
    async def _identify_operator(self, connection) -> Optional[str]:
        """Identify the operator from a connection."""
        try:
            # Check for operator ID in various places:
            # 1. Process environment variables
            # 2. Connection metadata
            # 3. Reverse DNS lookup
            # 4. Application-specific markers
            
            # Try to get process that owns the connection
            for proc in psutil.process_iter(['pid', 'environ']):
                try:
                    if any(c.laddr == connection.laddr for c in proc.connections()):
                        env = proc.environ()
                        
                        # Check for operator ID in environment
                        if 'OPERATOR_ID' in env:
                            return env['OPERATOR_ID']
                        if 'USER' in env:
                            return env['USER']
                            
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            # Fallback to IP-based identification
            if connection.raddr:
                return f"operator_{connection.raddr.ip}"
                
        except Exception as e:
            logger.debug(f"Could not identify operator: {e}")
        
        return None
    
    async def _extract_operator_from_process(self, process) -> Optional[str]:
        """Extract operator ID from process information."""
        try:
            # Check process environment
            env = process.environ()
            if 'OPERATOR_ID' in env:
                return env['OPERATOR_ID']
            if 'USER' in env:
                return env['USER']
                
            # Check process owner
            return process.username()
            
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as e:
            logger.debug(f"Could not extract operator from process: {e}")
        
        return None
    
    def _is_webrtc_port(self, port: int) -> bool:
        """Check if port is commonly used for WebRTC."""
        if port == 0:
            return False
            
        # Check STUN/TURN ports
        if port in self.webrtc_ports['stun'] or port in self.webrtc_ports['turn']:
            return True
        
        # Check signaling ports
        if port in self.webrtc_ports['signaling']:
            return True
            
        # Check media port range
        if port in self.webrtc_ports['media']:
            return True
            
        return False
    
    def _cleanup_stale_connections(self):
        """Remove stale connections."""
        stale_threshold = timedelta(seconds=30)
        now = datetime.now()
        
        stale_ids = [
            conn_id for conn_id, conn in self.connections.items()
            if conn.state == 'disconnected' or 
            (conn.last_activity and (now - conn.last_activity) > stale_threshold)
        ]
        
        for conn_id in stale_ids:
            del self.connections[conn_id]
            logger.debug(f"Removed stale connection: {conn_id}")
    
    def get_active_connections(self) -> List[WebRTCConnection]:
        """Get list of active WebRTC connections."""
        return [
            conn for conn in self.connections.values()
            if conn.state == 'connected' and conn.is_active
        ]
    
    def get_operator_sessions(self) -> Dict[str, List[WebRTCConnection]]:
        """Get connections grouped by operator."""
        sessions = {}
        for conn in self.get_active_connections():
            operator = conn.operator_id or 'unknown'
            if operator not in sessions:
                sessions[operator] = []
            sessions[operator].append(conn)
        return sessions
    
    def get_metrics(self) -> Dict:
        """Get current WebRTC metrics."""
        active_conns = self.get_active_connections()
        
        return {
            'total_connections': len(self.connections),
            'active_connections': len(active_conns),
            'unique_operators': len(self.get_operator_sessions()),
            'total_bandwidth_mbps': sum(c.bandwidth_mbps for c in active_conns),
            'avg_rtt_ms': sum(c.round_trip_time_ms for c in active_conns) / len(active_conns) if active_conns else 0,
            'video_streams': sum(c.video_tracks for c in active_conns),
            'connections': [
                {
                    'id': c.connection_id,
                    'operator': c.operator_id,
                    'state': c.state,
                    'duration_s': c.duration.total_seconds(),
                    'bandwidth_mbps': c.bandwidth_mbps,
                    'rtt_ms': c.round_trip_time_ms,
                    'video_tracks': c.video_tracks
                }
                for c in active_conns
            ]
        }