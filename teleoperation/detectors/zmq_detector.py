#!/usr/bin/env python3
"""
ZMQ Message Flow Detector
Monitors ZeroMQ message flow for teleoperation control commands.
"""

import asyncio
import json
import logging
import struct
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import psutil
import zmq
import zmq.asyncio
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class ZMQFlow:
    """Represents a ZMQ message flow."""
    flow_id: str
    socket_type: str  # 'pub', 'sub', 'req', 'rep', 'push', 'pull'
    endpoint: str
    direction: str  # 'inbound', 'outbound', 'bidirectional'
    message_rate: float = 0.0  # messages per second
    byte_rate: float = 0.0  # bytes per second
    total_messages: int = 0
    total_bytes: int = 0
    last_message_time: Optional[datetime] = None
    command_types: Dict[str, int] = field(default_factory=dict)
    operator_id: Optional[str] = None
    started_at: Optional[datetime] = None
    
    @property
    def is_active(self) -> bool:
        """Check if flow is active."""
        if not self.last_message_time:
            return False
        # Active if message received within last second
        return (datetime.now() - self.last_message_time) < timedelta(seconds=1)
    
    @property
    def duration(self) -> timedelta:
        """Get flow duration."""
        if not self.started_at:
            return timedelta(0)
        return datetime.now() - self.started_at
    
    @property
    def avg_message_size(self) -> float:
        """Calculate average message size."""
        if self.total_messages == 0:
            return 0.0
        return self.total_bytes / self.total_messages


class ZMQDetector:
    """
    Detects and monitors ZMQ message flows for teleoperation.
    Intercepts and analyzes control commands without impacting performance.
    """
    
    # Common ZMQ ports for robot control
    DEFAULT_PORTS = {
        'control_commands': 5555,
        'state_feedback': 5556,
        'video_stream': 5557,
        'telemetry': 5558,
        'joystick': 5559
    }
    
    # Command type patterns
    COMMAND_PATTERNS = {
        'movement': ['move', 'drive', 'velocity', 'twist'],
        'manipulation': ['arm', 'gripper', 'joint', 'servo'],
        'camera': ['pan', 'tilt', 'zoom', 'camera'],
        'system': ['enable', 'disable', 'emergency', 'stop']
    }
    
    def __init__(self, robot_type: str = "lekiwi", ports: Optional[Dict[str, int]] = None):
        self.robot_type = robot_type
        self.ports = ports or self.DEFAULT_PORTS
        self.flows: Dict[str, ZMQFlow] = {}
        self.active_operators: Set[str] = set()
        self._running = False
        self._monitor_tasks: List[asyncio.Task] = []
        
        # ZMQ context for monitoring
        self.context = zmq.asyncio.Context()
        self.monitor_sockets: Dict[str, zmq.asyncio.Socket] = {}
        
        # Message history for pattern analysis
        self.message_history = deque(maxlen=1000)
        
        # Performance metrics
        self.metrics = {
            'messages_processed': 0,
            'bytes_processed': 0,
            'processing_time_ms': 0.0
        }
    
    async def start(self):
        """Start ZMQ monitoring."""
        if self._running:
            return
            
        self._running = True
        
        # Setup monitor sockets
        await self._setup_monitors()
        
        # Start monitoring tasks
        for name, port in self.ports.items():
            task = asyncio.create_task(self._monitor_port(name, port))
            self._monitor_tasks.append(task)
        
        # Start flow analysis task
        analysis_task = asyncio.create_task(self._analyze_flows())
        self._monitor_tasks.append(analysis_task)
        
        logger.info("ZMQ detector started")
    
    async def stop(self):
        """Stop ZMQ monitoring."""
        self._running = False
        
        # Cancel monitoring tasks
        for task in self._monitor_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self._monitor_tasks, return_exceptions=True)
        
        # Close monitor sockets
        for socket in self.monitor_sockets.values():
            socket.close()
        
        # Terminate context
        self.context.term()
        
        logger.info("ZMQ detector stopped")
    
    async def _setup_monitors(self):
        """Setup ZMQ monitor sockets."""
        for name, port in self.ports.items():
            try:
                # Create SUB socket to monitor published messages
                socket = self.context.socket(zmq.SUB)
                socket.setsockopt(zmq.SUBSCRIBE, b'')  # Subscribe to all
                socket.setsockopt(zmq.CONFLATE, 1)  # Keep only latest message
                socket.setsockopt(zmq.RCVHWM, 100)  # Limit queue size
                
                # Try to connect to the endpoint
                endpoint = f"tcp://localhost:{port}"
                socket.connect(endpoint)
                
                self.monitor_sockets[name] = socket
                logger.debug(f"Monitoring ZMQ {name} on {endpoint}")
                
            except Exception as e:
                logger.warning(f"Could not setup monitor for {name}: {e}")
    
    async def _monitor_port(self, name: str, port: int):
        """Monitor a specific ZMQ port for messages."""
        socket = self.monitor_sockets.get(name)
        if not socket:
            return
        
        flow_id = f"zmq_{name}_{port}"
        flow = ZMQFlow(
            flow_id=flow_id,
            socket_type='monitor',
            endpoint=f"tcp://localhost:{port}",
            direction='inbound',
            started_at=datetime.now()
        )
        self.flows[flow_id] = flow
        
        while self._running:
            try:
                # Non-blocking receive with timeout
                if await socket.poll(100, zmq.POLLIN):
                    message = await socket.recv(zmq.NOBLOCK)
                    
                    # Process message
                    await self._process_message(flow, message)
                    
                await asyncio.sleep(0.001)  # Minimal sleep
                
            except zmq.Again:
                # No message available
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error monitoring {name}: {e}")
                await asyncio.sleep(1)
    
    async def _process_message(self, flow: ZMQFlow, message: bytes):
        """Process a ZMQ message."""
        start_time = datetime.now()
        
        try:
            # Update flow statistics
            flow.total_messages += 1
            flow.total_bytes += len(message)
            flow.last_message_time = datetime.now()
            
            # Try to parse message
            command_type = self._identify_command_type(message)
            if command_type:
                flow.command_types[command_type] = flow.command_types.get(command_type, 0) + 1
            
            # Extract operator if possible
            operator = self._extract_operator(message)
            if operator:
                flow.operator_id = operator
                self.active_operators.add(operator)
            
            # Add to history
            self.message_history.append({
                'flow_id': flow.flow_id,
                'timestamp': datetime.now(),
                'size': len(message),
                'type': command_type,
                'operator': operator
            })
            
            # Update metrics
            self.metrics['messages_processed'] += 1
            self.metrics['bytes_processed'] += len(message)
            
        except Exception as e:
            logger.debug(f"Error processing message: {e}")
        
        finally:
            # Track processing time
            processing_time = (datetime.now() - start_time).total_seconds() * 1000
            self.metrics['processing_time_ms'] = (
                self.metrics['processing_time_ms'] * 0.9 + processing_time * 0.1
            )  # Exponential moving average
    
    def _identify_command_type(self, message: bytes) -> Optional[str]:
        """Identify the type of command in the message."""
        try:
            # Try to decode as JSON
            if message.startswith(b'{'):
                data = json.loads(message)
                
                # Check for command type field
                if 'type' in data:
                    return data['type']
                if 'cmd' in data:
                    return data['cmd']
                
                # Check command patterns
                message_str = str(data).lower()
                for cmd_type, patterns in self.COMMAND_PATTERNS.items():
                    if any(pattern in message_str for pattern in patterns):
                        return cmd_type
            
            # Try to decode as string
            try:
                message_str = message.decode('utf-8').lower()
                for cmd_type, patterns in self.COMMAND_PATTERNS.items():
                    if any(pattern in message_str for pattern in patterns):
                        return cmd_type
            except:
                pass
            
            # Check binary protocol patterns
            if len(message) >= 4:
                # Common binary protocol with command ID
                cmd_id = struct.unpack('!I', message[:4])[0]
                if cmd_id < 100:  # Likely a command ID
                    return f"binary_cmd_{cmd_id}"
            
        except Exception:
            pass
        
        return None
    
    def _extract_operator(self, message: bytes) -> Optional[str]:
        """Extract operator ID from message."""
        try:
            # Try JSON
            if message.startswith(b'{'):
                data = json.loads(message)
                
                # Common operator fields
                for field in ['operator', 'operator_id', 'user', 'user_id', 'source']:
                    if field in data:
                        return str(data[field])
            
            # Try to find operator in string
            try:
                message_str = message.decode('utf-8')
                if 'operator:' in message_str:
                    parts = message_str.split('operator:')
                    if len(parts) > 1:
                        operator = parts[1].split()[0].strip()
                        return operator
            except:
                pass
                
        except Exception:
            pass
        
        return None
    
    async def _analyze_flows(self):
        """Analyze message flows for patterns."""
        while self._running:
            try:
                now = datetime.now()
                
                for flow_id, flow in self.flows.items():
                    # Calculate message rate
                    if flow.duration.total_seconds() > 0:
                        flow.message_rate = flow.total_messages / flow.duration.total_seconds()
                        flow.byte_rate = flow.total_bytes / flow.duration.total_seconds()
                    
                    # Detect teleoperation patterns
                    if self._is_teleoperation_pattern(flow):
                        if flow.operator_id and flow.operator_id not in self.active_operators:
                            self.active_operators.add(flow.operator_id)
                            logger.info(f"Teleoperation detected: operator={flow.operator_id}")
                    
                    # Remove inactive operators
                    if not flow.is_active and flow.operator_id in self.active_operators:
                        self.active_operators.remove(flow.operator_id)
                        logger.info(f"Teleoperation ended: operator={flow.operator_id}")
                
                await asyncio.sleep(0.5)  # Analyze every 500ms
                
            except Exception as e:
                logger.error(f"Error analyzing flows: {e}")
                await asyncio.sleep(1)
    
    def _is_teleoperation_pattern(self, flow: ZMQFlow) -> bool:
        """Detect if flow matches teleoperation pattern."""
        # Teleoperation characteristics:
        # - Regular message rate (10-100 Hz typical)
        # - Movement commands present
        # - Sustained activity
        
        if not flow.is_active:
            return False
        
        # Check message rate (10-100 Hz typical for teleoperation)
        if flow.message_rate < 10 or flow.message_rate > 200:
            return False
        
        # Check for movement commands
        movement_cmds = sum(
            count for cmd_type, count in flow.command_types.items()
            if 'move' in cmd_type.lower() or 'velocity' in cmd_type.lower()
        )
        
        if movement_cmds < 10:  # Need sustained movement commands
            return False
        
        # Check duration (at least 2 seconds of activity)
        if flow.duration < timedelta(seconds=2):
            return False
        
        return True
    
    def get_active_flows(self) -> List[ZMQFlow]:
        """Get list of active ZMQ flows."""
        return [flow for flow in self.flows.values() if flow.is_active]
    
    def get_operator_flows(self) -> Dict[str, List[ZMQFlow]]:
        """Get flows grouped by operator."""
        operator_flows = {}
        for flow in self.get_active_flows():
            operator = flow.operator_id or 'unknown'
            if operator not in operator_flows:
                operator_flows[operator] = []
            operator_flows[operator].append(flow)
        return operator_flows
    
    def get_metrics(self) -> Dict:
        """Get current ZMQ metrics."""
        active_flows = self.get_active_flows()
        
        # Calculate command distribution
        all_commands = {}
        for flow in active_flows:
            for cmd_type, count in flow.command_types.items():
                all_commands[cmd_type] = all_commands.get(cmd_type, 0) + count
        
        return {
            'total_flows': len(self.flows),
            'active_flows': len(active_flows),
            'unique_operators': len(self.active_operators),
            'total_message_rate': sum(f.message_rate for f in active_flows),
            'total_byte_rate': sum(f.byte_rate for f in active_flows),
            'messages_processed': self.metrics['messages_processed'],
            'bytes_processed': self.metrics['bytes_processed'],
            'avg_processing_time_ms': self.metrics['processing_time_ms'],
            'command_distribution': all_commands,
            'flows': [
                {
                    'id': f.flow_id,
                    'operator': f.operator_id,
                    'endpoint': f.endpoint,
                    'message_rate': f.message_rate,
                    'byte_rate': f.byte_rate,
                    'duration_s': f.duration.total_seconds(),
                    'total_messages': f.total_messages,
                    'command_types': f.command_types
                }
                for f in active_flows
            ]
        }