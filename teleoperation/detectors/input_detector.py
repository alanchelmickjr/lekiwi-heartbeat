#!/usr/bin/env python3
"""
Input Device Detector
Monitors joystick, gamepad, and keyboard input for teleoperation detection.
"""

import asyncio
import logging
import os
import struct
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Try to import evdev for Linux input monitoring
try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False
    logger.warning("evdev not available - input detection limited")


@dataclass
class InputSession:
    """Represents an input device session."""
    session_id: str
    device_name: str
    device_type: str  # 'joystick', 'gamepad', 'keyboard', 'mouse'
    device_path: str
    started_at: datetime
    last_input: Optional[datetime] = None
    input_count: int = 0
    axis_events: int = 0
    button_events: int = 0
    key_events: int = 0
    operator_id: Optional[str] = None
    
    # Teleoperation-specific metrics
    movement_commands: int = 0
    emergency_stops: int = 0
    mode_switches: int = 0
    
    @property
    def is_active(self) -> bool:
        """Check if input session is active."""
        if not self.last_input:
            return False
        # Active if input within last 2 seconds
        return (datetime.now() - self.last_input) < timedelta(seconds=2)
    
    @property
    def duration(self) -> timedelta:
        """Get session duration."""
        return datetime.now() - self.started_at
    
    @property
    def input_rate(self) -> float:
        """Calculate input events per second."""
        duration_s = self.duration.total_seconds()
        if duration_s <= 0:
            return 0.0
        return self.input_count / duration_s


class InputDetector:
    """
    Detects and monitors input devices used for teleoperation.
    Tracks joystick, gamepad, and keyboard inputs.
    """
    
    # Common teleoperation input patterns
    TELEOP_KEYS = {
        'movement': ['w', 'a', 's', 'd', 'up', 'down', 'left', 'right'],
        'speed': ['shift', 'ctrl', 'pageup', 'pagedown'],
        'emergency': ['space', 'esc', 'e'],
        'mode': ['1', '2', '3', '4', 'm', 'tab']
    }
    
    # Joystick/gamepad axis mappings
    AXIS_MAPPINGS = {
        0: 'left_x',    # Left stick X
        1: 'left_y',    # Left stick Y
        2: 'right_x',   # Right stick X
        3: 'right_y',   # Right stick Y
        4: 'trigger_l', # Left trigger
        5: 'trigger_r'  # Right trigger
    }
    
    def __init__(self, robot_type: str = "lekiwi"):
        self.robot_type = robot_type
        self.sessions: Dict[str, InputSession] = {}
        self.active_devices: Set[str] = set()
        self._running = False
        self._monitor_tasks: List[asyncio.Task] = []
        
        # Track input patterns
        self.input_patterns = {
            'movement_pattern': [],  # Recent movement inputs
            'button_pattern': [],    # Recent button presses
            'teleoperation_score': 0.0  # Confidence score
        }
        
        # Device monitoring
        self.monitored_devices: Dict[str, any] = {}
    
    async def start(self):
        """Start input monitoring."""
        if self._running:
            return
            
        self._running = True
        
        # Start device discovery
        discovery_task = asyncio.create_task(self._device_discovery_loop())
        self._monitor_tasks.append(discovery_task)
        
        # Start input monitoring based on platform
        if HAS_EVDEV and os.name == 'posix':
            monitor_task = asyncio.create_task(self._monitor_evdev())
            self._monitor_tasks.append(monitor_task)
        else:
            # Fallback to file-based monitoring
            monitor_task = asyncio.create_task(self._monitor_devices())
            self._monitor_tasks.append(monitor_task)
        
        # Start pattern analysis
        analysis_task = asyncio.create_task(self._analyze_patterns())
        self._monitor_tasks.append(analysis_task)
        
        logger.info("Input detector started")
    
    async def stop(self):
        """Stop input monitoring."""
        self._running = False
        
        # Cancel monitoring tasks
        for task in self._monitor_tasks:
            task.cancel()
        
        await asyncio.gather(*self._monitor_tasks, return_exceptions=True)
        
        # Close devices
        for device in self.monitored_devices.values():
            try:
                if hasattr(device, 'close'):
                    device.close()
            except:
                pass
        
        logger.info("Input detector stopped")
    
    async def _device_discovery_loop(self):
        """Discover and track input devices."""
        while self._running:
            try:
                devices = await self._discover_devices()
                
                for device_path, device_info in devices.items():
                    if device_path not in self.monitored_devices:
                        # New device found
                        await self._setup_device_monitoring(device_path, device_info)
                
                # Check for removed devices
                current_devices = set(devices.keys())
                monitored = set(self.monitored_devices.keys())
                removed = monitored - current_devices
                
                for device_path in removed:
                    await self._remove_device(device_path)
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"Error in device discovery: {e}")
                await asyncio.sleep(10)
    
    async def _discover_devices(self) -> Dict[str, Dict]:
        """Discover available input devices."""
        devices = {}
        
        try:
            if HAS_EVDEV and os.name == 'posix':
                # Use evdev for Linux
                for path in list_devices():
                    try:
                        device = InputDevice(path)
                        
                        # Check if it's a relevant device
                        capabilities = device.capabilities()
                        is_joystick = ecodes.EV_ABS in capabilities
                        is_keyboard = ecodes.EV_KEY in capabilities
                        
                        if is_joystick or is_keyboard:
                            devices[path] = {
                                'name': device.name,
                                'path': path,
                                'type': 'joystick' if is_joystick else 'keyboard',
                                'phys': device.phys,
                                'capabilities': capabilities
                            }
                        
                        device.close()
                        
                    except Exception as e:
                        logger.debug(f"Could not check device {path}: {e}")
            
            else:
                # Fallback: Check /dev/input for Linux or equivalent
                if os.path.exists('/dev/input'):
                    for entry in Path('/dev/input').iterdir():
                        if entry.name.startswith('js'):  # Joystick
                            devices[str(entry)] = {
                                'name': entry.name,
                                'path': str(entry),
                                'type': 'joystick'
                            }
                        elif entry.name.startswith('event'):  # Generic input
                            devices[str(entry)] = {
                                'name': entry.name,
                                'path': str(entry),
                                'type': 'input'
                            }
                
        except Exception as e:
            logger.error(f"Error discovering devices: {e}")
        
        return devices
    
    async def _setup_device_monitoring(self, device_path: str, device_info: Dict):
        """Setup monitoring for a device."""
        try:
            session_id = f"input_{device_info['type']}_{Path(device_path).name}"
            
            session = InputSession(
                session_id=session_id,
                device_name=device_info['name'],
                device_type=device_info['type'],
                device_path=device_path,
                started_at=datetime.now()
            )
            
            self.sessions[session_id] = session
            self.monitored_devices[device_path] = device_info
            
            logger.info(f"Monitoring input device: {device_info['name']} ({device_info['type']})")
            
        except Exception as e:
            logger.error(f"Error setting up device monitoring: {e}")
    
    async def _remove_device(self, device_path: str):
        """Remove device from monitoring."""
        try:
            if device_path in self.monitored_devices:
                del self.monitored_devices[device_path]
            
            # Find and remove session
            for session_id, session in list(self.sessions.items()):
                if session.device_path == device_path:
                    del self.sessions[session_id]
                    logger.info(f"Stopped monitoring device: {session.device_name}")
                    break
                    
        except Exception as e:
            logger.error(f"Error removing device: {e}")
    
    async def _monitor_evdev(self):
        """Monitor input using evdev (Linux)."""
        while self._running:
            try:
                for device_path, device_info in list(self.monitored_devices.items()):
                    try:
                        device = InputDevice(device_path)
                        
                        # Non-blocking read
                        while device.read_one():
                            event = device.read_one()
                            if event:
                                await self._process_evdev_event(device_path, event)
                        
                        device.close()
                        
                    except Exception as e:
                        logger.debug(f"Error reading {device_path}: {e}")
                
                await asyncio.sleep(0.01)  # 10ms polling
                
            except Exception as e:
                logger.error(f"Error in evdev monitoring: {e}")
                await asyncio.sleep(1)
    
    async def _monitor_devices(self):
        """Fallback device monitoring without evdev."""
        while self._running:
            try:
                # Monitor joystick devices directly
                for device_path in list(self.monitored_devices.keys()):
                    if 'js' in device_path:
                        await self._read_joystick(device_path)
                
                await asyncio.sleep(0.01)  # 10ms polling
                
            except Exception as e:
                logger.error(f"Error in device monitoring: {e}")
                await asyncio.sleep(1)
    
    async def _read_joystick(self, device_path: str):
        """Read joystick input from device file."""
        try:
            # Find session
            session = None
            for s in self.sessions.values():
                if s.device_path == device_path:
                    session = s
                    break
            
            if not session:
                return
            
            # Try to read joystick events (Linux joystick API)
            with open(device_path, 'rb') as f:
                # Non-blocking read
                os.set_blocking(f.fileno(), False)
                
                try:
                    # Joystick event structure: timestamp(4) + value(2) + type(1) + number(1)
                    data = f.read(8)
                    if data and len(data) == 8:
                        timestamp, value, event_type, number = struct.unpack('IhBB', data)
                        
                        # Process event
                        await self._process_joystick_event(session, event_type, number, value)
                        
                except BlockingIOError:
                    pass  # No data available
                    
        except Exception as e:
            logger.debug(f"Error reading joystick {device_path}: {e}")
    
    async def _process_evdev_event(self, device_path: str, event):
        """Process an evdev event."""
        try:
            # Find session
            session = None
            for s in self.sessions.values():
                if s.device_path == device_path:
                    session = s
                    break
            
            if not session:
                return
            
            # Update session
            session.last_input = datetime.now()
            session.input_count += 1
            
            if event.type == ecodes.EV_KEY:  # Button/key press
                session.key_events += 1
                
                # Check for teleoperation keys
                key_name = ecodes.KEY[event.code] if event.code in ecodes.KEY else str(event.code)
                if self._is_teleop_key(key_name):
                    session.movement_commands += 1
                
            elif event.type == ecodes.EV_ABS:  # Absolute axis (joystick)
                session.axis_events += 1
                
                # Track movement axes
                if event.code in [ecodes.ABS_X, ecodes.ABS_Y, ecodes.ABS_RX, ecodes.ABS_RY]:
                    session.movement_commands += 1
            
            # Add to pattern history
            self.input_patterns['movement_pattern'].append({
                'timestamp': datetime.now(),
                'type': event.type,
                'code': event.code,
                'value': event.value
            })
            
            # Limit pattern history size
            if len(self.input_patterns['movement_pattern']) > 100:
                self.input_patterns['movement_pattern'].pop(0)
                
        except Exception as e:
            logger.debug(f"Error processing evdev event: {e}")
    
    async def _process_joystick_event(self, session: InputSession, event_type: int, number: int, value: int):
        """Process a joystick event."""
        try:
            session.last_input = datetime.now()
            session.input_count += 1
            
            # Event types: 1=button, 2=axis
            if event_type == 1:  # Button
                session.button_events += 1
                
                # Check for emergency stop (typically button 0 or 1)
                if number in [0, 1] and value == 1:
                    session.emergency_stops += 1
                    
            elif event_type == 2:  # Axis
                session.axis_events += 1
                
                # Track movement axes (typically 0-3)
                if number < 4:
                    session.movement_commands += 1
            
            # Add to pattern history
            self.input_patterns['movement_pattern'].append({
                'timestamp': datetime.now(),
                'type': 'button' if event_type == 1 else 'axis',
                'number': number,
                'value': value
            })
            
            # Limit pattern history
            if len(self.input_patterns['movement_pattern']) > 100:
                self.input_patterns['movement_pattern'].pop(0)
                
        except Exception as e:
            logger.debug(f"Error processing joystick event: {e}")
    
    def _is_teleop_key(self, key_name: str) -> bool:
        """Check if key is commonly used for teleoperation."""
        key_lower = key_name.lower()
        
        for category, keys in self.TELEOP_KEYS.items():
            if any(k in key_lower for k in keys):
                return True
        
        return False
    
    async def _analyze_patterns(self):
        """Analyze input patterns for teleoperation detection."""
        while self._running:
            try:
                # Calculate teleoperation confidence score
                score = 0.0
                
                for session in self.sessions.values():
                    if session.is_active:
                        # Active input device
                        score += 20
                        
                        # Joystick/gamepad is strong indicator
                        if session.device_type in ['joystick', 'gamepad']:
                            score += 30
                        
                        # Regular movement commands
                        if session.movement_commands > 10:
                            score += 20
                        
                        # Sustained input rate
                        if session.input_rate > 5:  # >5 Hz
                            score += 15
                        
                        # Multiple input types (axes + buttons)
                        if session.axis_events > 0 and session.button_events > 0:
                            score += 15
                
                # Update teleoperation score
                self.input_patterns['teleoperation_score'] = min(score, 100)
                
                # Log if high confidence
                if score > 70:
                    active_sessions = [s for s in self.sessions.values() if s.is_active]
                    if active_sessions:
                        logger.info(f"Teleoperation detected via input devices (confidence: {score:.0f}%)")
                
                await asyncio.sleep(0.5)  # Analyze every 500ms
                
            except Exception as e:
                logger.error(f"Error analyzing patterns: {e}")
                await asyncio.sleep(1)
    
    def get_active_sessions(self) -> List[InputSession]:
        """Get list of active input sessions."""
        return [s for s in self.sessions.values() if s.is_active]
    
    def get_teleoperation_confidence(self) -> float:
        """Get teleoperation confidence score (0-100)."""
        return self.input_patterns['teleoperation_score']
    
    def get_metrics(self) -> Dict:
        """Get current input metrics."""
        active_sessions = self.get_active_sessions()
        
        return {
            'total_devices': len(self.monitored_devices),
            'active_sessions': len(active_sessions),
            'teleoperation_confidence': self.get_teleoperation_confidence(),
            'total_input_events': sum(s.input_count for s in active_sessions),
            'total_movement_commands': sum(s.movement_commands for s in active_sessions),
            'sessions': [
                {
                    'id': s.session_id,
                    'device': s.device_name,
                    'type': s.device_type,
                    'duration_s': s.duration.total_seconds(),
                    'input_rate': s.input_rate,
                    'input_count': s.input_count,
                    'movement_commands': s.movement_commands,
                    'axis_events': s.axis_events,
                    'button_events': s.button_events
                }
                for s in active_sessions
            ]
        }