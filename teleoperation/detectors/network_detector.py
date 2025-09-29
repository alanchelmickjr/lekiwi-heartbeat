#!/usr/bin/env python3
"""
Network Traffic Pattern Detector
Analyzes network traffic patterns to detect teleoperation activity.
"""

import asyncio
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import psutil

logger = logging.getLogger(__name__)


@dataclass
class NetworkFlow:
    """Represents a network flow."""
    flow_id: str
    protocol: str  # 'tcp', 'udp'
    local_addr: str
    remote_addr: str
    direction: str  # 'inbound', 'outbound', 'bidirectional'
    bytes_sent: int = 0
    bytes_received: int = 0
    packets_sent: int = 0
    packets_received: int = 0
    bandwidth_bps: float = 0.0  # Bits per second
    packet_rate: float = 0.0  # Packets per second
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    packet_loss_pct: float = 0.0
    started_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    flow_type: Optional[str] = None  # 'video', 'control', 'telemetry', 'unknown'
    
    @property
    def is_active(self) -> bool:
        """Check if flow is active."""
        if not self.last_activity:
            return False
        return (datetime.now() - self.last_activity) < timedelta(seconds=5)
    
    @property
    def duration(self) -> timedelta:
        """Get flow duration."""
        if not self.started_at:
            return timedelta(0)
        return datetime.now() - self.started_at
    
    @property
    def is_bidirectional(self) -> bool:
        """Check if flow has bidirectional traffic."""
        return self.bytes_sent > 0 and self.bytes_received > 0


@dataclass
class TrafficPattern:
    """Represents a traffic pattern."""
    pattern_type: str  # 'teleoperation', 'idle', 'download', 'upload'
    confidence: float  # 0-100
    characteristics: Dict[str, any] = field(default_factory=dict)
    detected_at: Optional[datetime] = None
    
    def matches_teleoperation(self) -> bool:
        """Check if pattern matches teleoperation characteristics."""
        return self.pattern_type == 'teleoperation' and self.confidence > 70


class NetworkDetector:
    """
    Detects teleoperation by analyzing network traffic patterns.
    Identifies characteristic patterns of video streaming and control commands.
    """
    
    # Teleoperation traffic characteristics
    TELEOPERATION_PATTERNS = {
        'video_stream': {
            'bandwidth_min_mbps': 1.0,  # Minimum 1 Mbps for video
            'bandwidth_max_mbps': 50.0,  # Maximum 50 Mbps
            'packet_rate_min': 30,  # At least 30 packets/sec
            'ports': [554, 1935, 8554, 5000, 5001],  # RTSP, RTMP, RTP
            'protocols': ['udp', 'tcp']
        },
        'control_commands': {
            'bandwidth_min_kbps': 10,  # 10 Kbps minimum
            'bandwidth_max_kbps': 500,  # 500 Kbps maximum
            'packet_rate_min': 10,  # At least 10 Hz
            'packet_rate_max': 200,  # At most 200 Hz
            'latency_max_ms': 100,  # Low latency required
            'bidirectional': True  # Commands and feedback
        },
        'combined': {
            'flow_count_min': 2,  # At least 2 flows (video + control)
            'bandwidth_ratio': 0.01,  # Control is ~1% of video bandwidth
            'timing_correlation': 0.7  # Flows should be correlated
        }
    }
    
    def __init__(self, robot_type: str = "lekiwi"):
        self.robot_type = robot_type
        self.flows: Dict[str, NetworkFlow] = {}
        self.patterns: List[TrafficPattern] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Traffic history for pattern analysis
        self.traffic_history = deque(maxlen=300)  # 5 minutes at 1Hz
        
        # Connection tracking
        self.prev_connections = {}
        self.prev_stats = {}
        
        # Pattern detection state
        self.teleoperation_detected = False
        self.detection_confidence = 0.0
    
    async def start(self):
        """Start network monitoring."""
        if self._running:
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Network detector started")
    
    async def stop(self):
        """Stop network monitoring."""
        self._running = False
        if self._monitor_task:
            await self._monitor_task
        logger.info("Network detector stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Capture network snapshot
                snapshot = await self._capture_network_snapshot()
                
                # Update flows
                await self._update_flows(snapshot)
                
                # Analyze traffic patterns
                await self._analyze_patterns()
                
                # Store history
                self.traffic_history.append({
                    'timestamp': datetime.now(),
                    'flows': len(self.flows),
                    'active_flows': len([f for f in self.flows.values() if f.is_active]),
                    'total_bandwidth': sum(f.bandwidth_bps for f in self.flows.values()),
                    'confidence': self.detection_confidence
                })
                
                await asyncio.sleep(1)  # 1 second sampling
                
            except Exception as e:
                logger.error(f"Error in network monitor loop: {e}")
                await asyncio.sleep(5)
    
    async def _capture_network_snapshot(self) -> Dict:
        """Capture current network state."""
        snapshot = {
            'timestamp': datetime.now(),
            'connections': [],
            'stats': {},
            'interfaces': {}
        }
        
        try:
            # Get network connections
            connections = psutil.net_connections(kind='inet')
            snapshot['connections'] = [
                {
                    'fd': conn.fd,
                    'family': conn.family,
                    'type': conn.type,
                    'laddr': conn.laddr,
                    'raddr': conn.raddr,
                    'status': conn.status,
                    'pid': conn.pid
                }
                for conn in connections
                if conn.status == 'ESTABLISHED'
            ]
            
            # Get network statistics
            net_stats = psutil.net_io_counters()
            snapshot['stats'] = {
                'bytes_sent': net_stats.bytes_sent,
                'bytes_recv': net_stats.bytes_recv,
                'packets_sent': net_stats.packets_sent,
                'packets_recv': net_stats.packets_recv,
                'errin': net_stats.errin,
                'errout': net_stats.errout,
                'dropin': net_stats.dropin,
                'dropout': net_stats.dropout
            }
            
            # Get per-interface statistics
            per_nic = psutil.net_io_counters(pernic=True)
            snapshot['interfaces'] = {
                iface: {
                    'bytes_sent': stats.bytes_sent,
                    'bytes_recv': stats.bytes_recv,
                    'packets_sent': stats.packets_sent,
                    'packets_recv': stats.packets_recv
                }
                for iface, stats in per_nic.items()
            }
            
        except Exception as e:
            logger.error(f"Error capturing network snapshot: {e}")
        
        return snapshot
    
    async def _update_flows(self, snapshot: Dict):
        """Update network flows from snapshot."""
        current_time = snapshot['timestamp']
        
        # Track current connections
        current_connections = set()
        
        for conn in snapshot['connections']:
            # Create flow ID
            laddr = conn['laddr']
            raddr = conn['raddr']
            
            if not laddr or not raddr:
                continue
            
            flow_id = f"{laddr.ip}:{laddr.port}-{raddr.ip}:{raddr.port}"
            current_connections.add(flow_id)
            
            # Update or create flow
            if flow_id not in self.flows:
                # New flow detected
                flow = NetworkFlow(
                    flow_id=flow_id,
                    protocol='tcp' if conn['type'] == 1 else 'udp',
                    local_addr=f"{laddr.ip}:{laddr.port}",
                    remote_addr=f"{raddr.ip}:{raddr.port}",
                    direction='unknown',
                    started_at=current_time
                )
                
                # Classify flow type
                flow.flow_type = self._classify_flow(laddr.port, raddr.port)
                
                self.flows[flow_id] = flow
                logger.debug(f"New flow detected: {flow_id} (type: {flow.flow_type})")
            
            # Update activity
            self.flows[flow_id].last_activity = current_time
            
            # Update traffic stats (simplified - would use eBPF in production)
            await self._update_flow_stats(self.flows[flow_id], snapshot)
        
        # Mark inactive flows
        for flow_id in list(self.flows.keys()):
            if flow_id not in current_connections:
                if self.flows[flow_id].is_active:
                    # Flow just became inactive
                    logger.debug(f"Flow ended: {flow_id}")
                # Keep for analysis but mark as inactive
    
    async def _update_flow_stats(self, flow: NetworkFlow, snapshot: Dict):
        """Update flow statistics."""
        try:
            # Calculate bandwidth based on system-wide stats
            # In production, use eBPF or netfilter for per-flow stats
            
            current_stats = snapshot['stats']
            
            if hasattr(self, 'prev_snapshot_time'):
                time_delta = (snapshot['timestamp'] - self.prev_snapshot_time).total_seconds()
                
                if time_delta > 0 and self.prev_stats:
                    # Calculate rates
                    bytes_delta = current_stats['bytes_sent'] - self.prev_stats.get('bytes_sent', 0)
                    packets_delta = current_stats['packets_sent'] - self.prev_stats.get('packets_sent', 0)
                    
                    # Estimate per-flow share (simplified)
                    active_flows = len([f for f in self.flows.values() if f.is_active])
                    if active_flows > 0:
                        flow.bandwidth_bps = (bytes_delta * 8 / time_delta) / active_flows
                        flow.packet_rate = packets_delta / time_delta / active_flows
                    
                    # Update cumulative stats
                    flow.bytes_sent += bytes_delta // active_flows if active_flows > 0 else 0
                    flow.packets_sent += packets_delta // active_flows if active_flows > 0 else 0
                    
                    # Calculate packet loss
                    errors = current_stats.get('errout', 0) - self.prev_stats.get('errout', 0)
                    drops = current_stats.get('dropout', 0) - self.prev_stats.get('dropout', 0)
                    total_packets = packets_delta
                    
                    if total_packets > 0:
                        flow.packet_loss_pct = ((errors + drops) / total_packets) * 100
            
            self.prev_stats = current_stats
            self.prev_snapshot_time = snapshot['timestamp']
            
        except Exception as e:
            logger.debug(f"Error updating flow stats: {e}")
    
    def _classify_flow(self, local_port: int, remote_port: int) -> str:
        """Classify flow type based on ports."""
        video_ports = [554, 1935, 8554, 5000, 5001, 8080, 8443]
        control_ports = [5555, 5556, 5557, 5558, 5559, 9090]
        
        if local_port in video_ports or remote_port in video_ports:
            return 'video'
        elif local_port in control_ports or remote_port in control_ports:
            return 'control'
        elif 10000 <= local_port <= 60000 or 10000 <= remote_port <= 60000:
            return 'media'  # RTP/RTCP range
        else:
            return 'unknown'
    
    async def _analyze_patterns(self):
        """Analyze traffic patterns for teleoperation detection."""
        try:
            active_flows = [f for f in self.flows.values() if f.is_active]
            
            # Check for video streams
            video_flows = [f for f in active_flows if f.flow_type in ['video', 'media']]
            control_flows = [f for f in active_flows if f.flow_type == 'control']
            
            # Calculate detection confidence
            confidence = 0.0
            characteristics = {}
            
            # Check for video stream characteristics
            if video_flows:
                total_video_bandwidth = sum(f.bandwidth_bps for f in video_flows) / 1_000_000  # Mbps
                
                if (self.TELEOPERATION_PATTERNS['video_stream']['bandwidth_min_mbps'] <= 
                    total_video_bandwidth <= 
                    self.TELEOPERATION_PATTERNS['video_stream']['bandwidth_max_mbps']):
                    confidence += 30
                    characteristics['video_bandwidth_mbps'] = total_video_bandwidth
                
                # Check packet rate
                total_packet_rate = sum(f.packet_rate for f in video_flows)
                if total_packet_rate >= self.TELEOPERATION_PATTERNS['video_stream']['packet_rate_min']:
                    confidence += 20
                    characteristics['video_packet_rate'] = total_packet_rate
            
            # Check for control command characteristics
            if control_flows:
                total_control_bandwidth = sum(f.bandwidth_bps for f in control_flows) / 1000  # Kbps
                
                if (self.TELEOPERATION_PATTERNS['control_commands']['bandwidth_min_kbps'] <= 
                    total_control_bandwidth <= 
                    self.TELEOPERATION_PATTERNS['control_commands']['bandwidth_max_kbps']):
                    confidence += 20
                    characteristics['control_bandwidth_kbps'] = total_control_bandwidth
                
                # Check for bidirectional control
                bidirectional = any(f.is_bidirectional for f in control_flows)
                if bidirectional:
                    confidence += 15
                    characteristics['bidirectional_control'] = True
            
            # Check for combined pattern
            if video_flows and control_flows:
                confidence += 15
                characteristics['multi_flow'] = True
                
                # Check bandwidth ratio
                if video_flows and control_flows:
                    video_bw = sum(f.bandwidth_bps for f in video_flows)
                    control_bw = sum(f.bandwidth_bps for f in control_flows)
                    
                    if video_bw > 0:
                        ratio = control_bw / video_bw
                        if 0.001 <= ratio <= 0.1:  # Control is 0.1-10% of video
                            confidence += 10
                            characteristics['bandwidth_ratio'] = ratio
            
            # Check for sustained activity
            if len(self.traffic_history) >= 10:
                recent_active = sum(
                    1 for h in list(self.traffic_history)[-10:]
                    if h['active_flows'] > 0
                )
                if recent_active >= 8:  # Active for 8 out of 10 seconds
                    confidence += 10
                    characteristics['sustained_activity'] = True
            
            # Update detection state
            self.detection_confidence = min(confidence, 100)
            
            # Create pattern
            pattern = TrafficPattern(
                pattern_type='teleoperation' if confidence > 70 else 'unknown',
                confidence=confidence,
                characteristics=characteristics,
                detected_at=datetime.now()
            )
            
            self.patterns.append(pattern)
            
            # Limit pattern history
            if len(self.patterns) > 100:
                self.patterns.pop(0)
            
            # Log detection changes
            if confidence > 70 and not self.teleoperation_detected:
                self.teleoperation_detected = True
                logger.info(f"Teleoperation detected via network patterns (confidence: {confidence:.0f}%)")
                logger.info(f"Characteristics: {characteristics}")
            elif confidence <= 50 and self.teleoperation_detected:
                self.teleoperation_detected = False
                logger.info("Teleoperation ended (network patterns)")
                
        except Exception as e:
            logger.error(f"Error analyzing patterns: {e}")
    
    def get_active_flows(self) -> List[NetworkFlow]:
        """Get list of active network flows."""
        return [f for f in self.flows.values() if f.is_active]
    
    def get_teleoperation_flows(self) -> Dict[str, List[NetworkFlow]]:
        """Get flows categorized by type."""
        active_flows = self.get_active_flows()
        
        return {
            'video': [f for f in active_flows if f.flow_type in ['video', 'media']],
            'control': [f for f in active_flows if f.flow_type == 'control'],
            'unknown': [f for f in active_flows if f.flow_type == 'unknown']
        }
    
    def get_metrics(self) -> Dict:
        """Get current network metrics."""
        active_flows = self.get_active_flows()
        categorized = self.get_teleoperation_flows()
        
        return {
            'total_flows': len(self.flows),
            'active_flows': len(active_flows),
            'video_flows': len(categorized['video']),
            'control_flows': len(categorized['control']),
            'teleoperation_detected': self.teleoperation_detected,
            'detection_confidence': self.detection_confidence,
            'total_bandwidth_mbps': sum(f.bandwidth_bps for f in active_flows) / 1_000_000,
            'avg_packet_loss_pct': sum(f.packet_loss_pct for f in active_flows) / len(active_flows) if active_flows else 0,
            'flows': [
                {
                    'id': f.flow_id,
                    'type': f.flow_type,
                    'protocol': f.protocol,
                    'bandwidth_kbps': f.bandwidth_bps / 1000,
                    'packet_rate': f.packet_rate,
                    'duration_s': f.duration.total_seconds(),
                    'bidirectional': f.is_bidirectional
                }
                for f in active_flows
            ],
            'latest_pattern': {
                'type': self.patterns[-1].pattern_type if self.patterns else 'unknown',
                'confidence': self.patterns[-1].confidence if self.patterns else 0,
                'characteristics': self.patterns[-1].characteristics if self.patterns else {}
            } if self.patterns else None
        }