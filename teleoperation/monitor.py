#!/usr/bin/env python3
"""
Teleoperation Monitor
Main service that coordinates all teleoperation detection and monitoring components.
"""

import asyncio
import logging
import signal
import sys
import os
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import json
import psutil

# Import detection modules
from teleoperation.detectors.webrtc_detector import WebRTCDetector
from teleoperation.detectors.zmq_detector import ZMQDetector
from teleoperation.detectors.input_detector import InputDetector
from teleoperation.detectors.network_detector import NetworkDetector

# Import streaming modules
from teleoperation.streaming.websocket_streamer import WebSocketStreamer, TeleopEventTypes
from teleoperation.streaming.metrics_collector import MetricsCollector

# Import optimization modules
from teleoperation.optimization.shared_memory import SharedMemoryManager
from teleoperation.optimization.ring_buffer import SharedRingBuffer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TeleoperationState:
    """Current teleoperation state."""
    is_active: bool = False
    operators: List[str] = None
    start_time: Optional[datetime] = None
    duration: Optional[timedelta] = None
    confidence: float = 0.0
    
    # Connection details
    webrtc_connections: int = 0
    zmq_flows: int = 0
    input_devices: int = 0
    network_flows: int = 0
    
    # Performance metrics
    latency_ms: float = 0.0
    bandwidth_mbps: float = 0.0
    packet_loss_pct: float = 0.0
    fps: float = 0.0
    command_rate_hz: float = 0.0
    
    # Resource usage
    cpu_usage_pct: float = 0.0
    memory_usage_mb: float = 0.0
    
    def __post_init__(self):
        if self.operators is None:
            self.operators = []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        data = asdict(self)
        # Convert datetime objects
        if self.start_time:
            data['start_time'] = self.start_time.isoformat()
        if self.duration:
            data['duration'] = self.duration.total_seconds()
        return data


class TeleoperationMonitor:
    """
    Main teleoperation monitoring service.
    Coordinates all detection modules and provides unified monitoring.
    """
    
    def __init__(self, robot_type: str = "lekiwi", config: Optional[Dict] = None):
        self.robot_type = robot_type
        self.config = config or {}
        
        # Initialize detectors
        self.webrtc_detector = WebRTCDetector(robot_type)
        self.zmq_detector = ZMQDetector(robot_type)
        self.input_detector = InputDetector(robot_type)
        self.network_detector = NetworkDetector(robot_type)
        
        # Initialize streaming
        ws_port = self.config.get('websocket_port', 8765)
        self.websocket_streamer = WebSocketStreamer(port=ws_port)
        self.metrics_collector = MetricsCollector()
        
        # Initialize optimization
        self.shared_memory = SharedMemoryManager()
        self.telemetry_buffer = SharedRingBuffer(
            name="teleoperation_telemetry",
            capacity=65536,
            create=True
        )
        
        # Current state
        self.state = TeleoperationState()
        self.previous_state = None
        
        # Control
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Performance settings
        self.detection_interval = 0.1  # 100ms detection target
        self.update_interval = 0.5     # 500ms state update
        
        # Statistics
        self.stats = {
            'detections': 0,
            'state_changes': 0,
            'total_runtime': 0,
            'teleoperation_time': 0
        }
    
    async def start(self):
        """Start teleoperation monitoring."""
        logger.info(f"Starting teleoperation monitor for {self.robot_type} robot")
        
        try:
            # Initialize shared memory
            self.shared_memory.initialize(create=True)
            
            # Start detectors
            await self.webrtc_detector.start()
            await self.zmq_detector.start()
            await self.input_detector.start()
            await self.network_detector.start()
            
            # Start streaming
            await self.websocket_streamer.start()
            await self.metrics_collector.start()
            
            # Setup alert callback
            self.metrics_collector.add_alert_callback(self._handle_metric_alert)
            
            # Start main monitoring loop
            self._running = True
            self._monitor_task = asyncio.create_task(self._monitor_loop())
            
            logger.info("Teleoperation monitor started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start teleoperation monitor: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Stop teleoperation monitoring."""
        logger.info("Stopping teleoperation monitor")
        
        self._running = False
        
        # Stop monitoring task
        if self._monitor_task:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
        
        # Stop detectors
        await self.webrtc_detector.stop()
        await self.zmq_detector.stop()
        await self.input_detector.stop()
        await self.network_detector.stop()
        
        # Stop streaming
        await self.websocket_streamer.stop()
        await self.metrics_collector.stop()
        
        # Cleanup optimization
        self.shared_memory.cleanup()
        self.telemetry_buffer.cleanup()
        
        logger.info("Teleoperation monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        last_update = datetime.now()
        
        while self._running:
            try:
                start_time = datetime.now()
                
                # Collect detection signals
                signals = await self._collect_signals()
                
                # Analyze signals
                analysis = self._analyze_signals(signals)
                
                # Update state
                state_changed = self._update_state(analysis)
                
                # Record telemetry
                self._record_telemetry(signals, analysis)
                
                # Update shared memory
                self._update_shared_memory()
                
                # Broadcast updates if needed
                if state_changed or (datetime.now() - last_update).total_seconds() > self.update_interval:
                    await self._broadcast_state()
                    last_update = datetime.now()
                
                # Calculate sleep time to maintain detection interval
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(0, self.detection_interval - elapsed)
                
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1)
    
    async def _collect_signals(self) -> Dict[str, Any]:
        """Collect signals from all detectors."""
        signals = {}
        
        # WebRTC signals
        webrtc_connections = self.webrtc_detector.get_active_connections()
        webrtc_operators = self.webrtc_detector.get_operator_sessions()
        signals['webrtc'] = {
            'active': len(webrtc_connections) > 0,
            'connections': len(webrtc_connections),
            'operators': list(webrtc_operators.keys()),
            'metrics': self.webrtc_detector.get_metrics()
        }
        
        # ZMQ signals
        zmq_flows = self.zmq_detector.get_active_flows()
        zmq_operators = self.zmq_detector.get_operator_flows()
        signals['zmq'] = {
            'active': len(zmq_flows) > 0,
            'flows': len(zmq_flows),
            'operators': list(zmq_operators.keys()),
            'metrics': self.zmq_detector.get_metrics()
        }
        
        # Input signals
        input_sessions = self.input_detector.get_active_sessions()
        input_confidence = self.input_detector.get_teleoperation_confidence()
        signals['input'] = {
            'active': len(input_sessions) > 0,
            'sessions': len(input_sessions),
            'confidence': input_confidence,
            'metrics': self.input_detector.get_metrics()
        }
        
        # Network signals
        network_flows = self.network_detector.get_active_flows()
        network_detected = self.network_detector.teleoperation_detected
        signals['network'] = {
            'active': network_detected,
            'flows': len(network_flows),
            'confidence': self.network_detector.detection_confidence,
            'metrics': self.network_detector.get_metrics()
        }
        
        # System resources
        process = psutil.Process()
        signals['resources'] = {
            'cpu_percent': process.cpu_percent(),
            'memory_mb': process.memory_info().rss / 1024 / 1024,
            'threads': process.num_threads()
        }
        
        return signals
    
    def _analyze_signals(self, signals: Dict) -> Dict:
        """Analyze collected signals to determine teleoperation state."""
        analysis = {
            'is_teleoperation': False,
            'confidence': 0.0,
            'operators': set(),
            'reasons': []
        }
        
        # Calculate confidence from multiple signals
        confidence_scores = []
        
        # WebRTC signal (strong indicator)
        if signals['webrtc']['active']:
            confidence_scores.append(90)
            analysis['reasons'].append(f"WebRTC: {signals['webrtc']['connections']} connections")
            analysis['operators'].update(signals['webrtc']['operators'])
        
        # ZMQ signal (strong indicator)
        if signals['zmq']['active']:
            # Check for teleoperation pattern in ZMQ
            zmq_metrics = signals['zmq']['metrics']
            if zmq_metrics.get('total_message_rate', 0) > 10:  # >10 Hz
                confidence_scores.append(85)
                analysis['reasons'].append(f"ZMQ: {zmq_metrics['total_message_rate']:.1f} Hz")
                analysis['operators'].update(signals['zmq']['operators'])
        
        # Input signal (moderate indicator)
        if signals['input']['active']:
            input_confidence = signals['input']['confidence']
            if input_confidence > 50:
                confidence_scores.append(input_confidence)
                analysis['reasons'].append(f"Input: {input_confidence:.0f}% confidence")
        
        # Network signal (supporting indicator)
        if signals['network']['active']:
            network_confidence = signals['network']['confidence']
            if network_confidence > 60:
                confidence_scores.append(network_confidence * 0.8)  # Weight lower
                analysis['reasons'].append(f"Network: {network_confidence:.0f}% confidence")
        
        # Calculate overall confidence
        if confidence_scores:
            # Use weighted average with emphasis on highest score
            max_score = max(confidence_scores)
            avg_score = sum(confidence_scores) / len(confidence_scores)
            analysis['confidence'] = max_score * 0.7 + avg_score * 0.3
            
            # Determine if teleoperation is active
            if analysis['confidence'] > 70:
                analysis['is_teleoperation'] = True
            elif analysis['confidence'] > 50 and len(confidence_scores) >= 2:
                # Multiple moderate signals
                analysis['is_teleoperation'] = True
        
        # Extract performance metrics
        analysis['metrics'] = self._extract_performance_metrics(signals)
        
        return analysis
    
    def _extract_performance_metrics(self, signals: Dict) -> Dict:
        """Extract performance metrics from signals."""
        metrics = {
            'latency_ms': 0.0,
            'bandwidth_mbps': 0.0,
            'packet_loss_pct': 0.0,
            'fps': 0.0,
            'command_rate_hz': 0.0
        }
        
        # Extract from WebRTC
        if 'webrtc' in signals:
            webrtc_metrics = signals['webrtc']['metrics']
            if 'avg_rtt_ms' in webrtc_metrics:
                metrics['latency_ms'] = webrtc_metrics['avg_rtt_ms']
            if 'total_bandwidth_mbps' in webrtc_metrics:
                metrics['bandwidth_mbps'] += webrtc_metrics['total_bandwidth_mbps']
        
        # Extract from ZMQ
        if 'zmq' in signals:
            zmq_metrics = signals['zmq']['metrics']
            if 'total_message_rate' in zmq_metrics:
                metrics['command_rate_hz'] = zmq_metrics['total_message_rate']
        
        # Extract from Network
        if 'network' in signals:
            network_metrics = signals['network']['metrics']
            if 'total_bandwidth_mbps' in network_metrics:
                metrics['bandwidth_mbps'] = max(
                    metrics['bandwidth_mbps'],
                    network_metrics['total_bandwidth_mbps']
                )
            if 'avg_packet_loss_pct' in network_metrics:
                metrics['packet_loss_pct'] = network_metrics['avg_packet_loss_pct']
        
        return metrics
    
    def _update_state(self, analysis: Dict) -> bool:
        """Update teleoperation state based on analysis."""
        self.previous_state = TeleoperationState(**asdict(self.state))
        
        # Update active status
        was_active = self.state.is_active
        self.state.is_active = analysis['is_teleoperation']
        self.state.confidence = analysis['confidence']
        
        # Update operators
        self.state.operators = list(analysis['operators'])
        
        # Update timing
        if self.state.is_active and not was_active:
            # Teleoperation started
            self.state.start_time = datetime.now()
            logger.info(f"Teleoperation started - Operators: {self.state.operators}, Confidence: {self.state.confidence:.0f}%")
            
        elif not self.state.is_active and was_active:
            # Teleoperation ended
            if self.state.start_time:
                self.state.duration = datetime.now() - self.state.start_time
                self.stats['teleoperation_time'] += self.state.duration.total_seconds()
            logger.info(f"Teleoperation ended - Duration: {self.state.duration}")
            self.state.start_time = None
            
        elif self.state.is_active:
            # Update duration
            if self.state.start_time:
                self.state.duration = datetime.now() - self.state.start_time
        
        # Update metrics
        metrics = analysis['metrics']
        self.state.latency_ms = metrics['latency_ms']
        self.state.bandwidth_mbps = metrics['bandwidth_mbps']
        self.state.packet_loss_pct = metrics['packet_loss_pct']
        self.state.fps = metrics['fps']
        self.state.command_rate_hz = metrics['command_rate_hz']
        
        # Update connection counts
        self.state.webrtc_connections = analysis.get('webrtc_connections', 0)
        self.state.zmq_flows = analysis.get('zmq_flows', 0)
        self.state.input_devices = analysis.get('input_devices', 0)
        self.state.network_flows = analysis.get('network_flows', 0)
        
        # Check if state changed
        state_changed = was_active != self.state.is_active
        if state_changed:
            self.stats['state_changes'] += 1
        
        self.stats['detections'] += 1
        
        return state_changed
    
    def _record_telemetry(self, signals: Dict, analysis: Dict):
        """Record telemetry data."""
        # Record to metrics collector
        if 'metrics' in analysis:
            metrics = analysis['metrics']
            self.metrics_collector.record_latency(metrics['latency_ms'])
            self.metrics_collector.record_bandwidth(metrics['bandwidth_mbps'])
            self.metrics_collector.record_packet_loss(metrics['packet_loss_pct'])
            self.metrics_collector.record_fps(metrics['fps'])
            self.metrics_collector.record_command_rate(metrics['command_rate_hz'])
        
        # Record resource usage
        if 'resources' in signals:
            resources = signals['resources']
            self.metrics_collector.record_resource_usage(
                resources['cpu_percent'],
                resources['memory_mb']
            )
        
        # Write to ring buffer
        telemetry_data = {
            'timestamp': datetime.now().isoformat(),
            'is_active': self.state.is_active,
            'confidence': self.state.confidence,
            'operators': self.state.operators,
            'metrics': analysis.get('metrics', {})
        }
        
        self.telemetry_buffer.write(
            item_type=1,  # Telemetry type
            data=json.dumps(telemetry_data).encode('utf-8')
        )
    
    def _update_shared_memory(self):
        """Update shared memory with current state."""
        try:
            # Write state
            self.shared_memory.write_state(self.state.to_dict())
            
            # Write metrics
            metrics = {
                'latency_ms': self.state.latency_ms,
                'bandwidth_mbps': self.state.bandwidth_mbps,
                'packet_loss_pct': self.state.packet_loss_pct,
                'fps': self.state.fps,
                'command_rate_hz': self.state.command_rate_hz,
                'cpu_usage_pct': self.state.cpu_usage_pct,
                'memory_usage_mb': self.state.memory_usage_mb
            }
            self.shared_memory.write_metrics(metrics)
            
        except Exception as e:
            logger.error(f"Error updating shared memory: {e}")
    
    async def _broadcast_state(self):
        """Broadcast state update via WebSocket."""
        try:
            await self.websocket_streamer.update_teleoperation_state({
                'teleoperation_active': self.state.is_active,
                'operators': self.state.operators,
                'confidence': self.state.confidence,
                'connections': {
                    'webrtc': self.state.webrtc_connections,
                    'zmq': self.state.zmq_flows,
                    'input': self.state.input_devices,
                    'network': self.state.network_flows
                },
                'metrics': {
                    'latency_ms': self.state.latency_ms,
                    'bandwidth_mbps': self.state.bandwidth_mbps,
                    'packet_loss_pct': self.state.packet_loss_pct,
                    'fps': self.state.fps,
                    'command_rate_hz': self.state.command_rate_hz
                }
            })
            
            # Broadcast specific events
            if self.state.is_active and not self.previous_state.is_active:
                await self.websocket_streamer.broadcast_event(
                    TeleopEventTypes.TELEOPERATION_STARTED,
                    {'operators': self.state.operators}
                )
            elif not self.state.is_active and self.previous_state.is_active:
                await self.websocket_streamer.broadcast_event(
                    TeleopEventTypes.TELEOPERATION_STOPPED,
                    {'duration': self.state.duration.total_seconds() if self.state.duration else 0}
                )
                
        except Exception as e:
            logger.error(f"Error broadcasting state: {e}")
    
    async def _handle_metric_alert(self, alert: Dict):
        """Handle metric alerts."""
        logger.warning(f"Metric alert: {alert['metric']} - {alert['reason']}")
        
        # Broadcast alert
        event_type = None
        if 'latency' in alert['metric']:
            event_type = TeleopEventTypes.LATENCY_WARNING
        elif 'bandwidth' in alert['metric']:
            event_type = TeleopEventTypes.BANDWIDTH_WARNING
        elif 'packet_loss' in alert['metric']:
            event_type = TeleopEventTypes.PACKET_LOSS_WARNING
        
        if event_type:
            await self.websocket_streamer.broadcast_event(event_type, alert)
    
    def get_state(self) -> TeleoperationState:
        """Get current teleoperation state."""
        return self.state
    
    def get_stats(self) -> Dict:
        """Get monitoring statistics."""
        return {
            **self.stats,
            'current_state': self.state.to_dict(),
            'detector_metrics': {
                'webrtc': self.webrtc_detector.get_metrics(),
                'zmq': self.zmq_detector.get_metrics(),
                'input': self.input_detector.get_metrics(),
                'network': self.network_detector.get_metrics()
            },
            'streaming_metrics': self.websocket_streamer.get_metrics(),
            'collector_metrics': self.metrics_collector.get_metrics(),
            'memory_stats': self.shared_memory.get_memory_stats(),
            'buffer_stats': self.telemetry_buffer.stats
        }


async def main():
    """Main entry point."""
    # Parse arguments
    import argparse
    parser = argparse.ArgumentParser(description='Teleoperation Monitor')
    parser.add_argument('--robot-type', choices=['lekiwi', 'xle'], default='lekiwi')
    parser.add_argument('--websocket-port', type=int, default=8765)
    parser.add_argument('--log-level', default='INFO')
    args = parser.parse_args()
    
    # Configure logging
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Create monitor
    config = {
        'websocket_port': args.websocket_port
    }
    monitor = TeleoperationMonitor(robot_type=args.robot_type, config=config)
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}")
        asyncio.create_task(monitor.stop())
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start monitor
    await monitor.start()
    
    # Run forever
    try:
        while True:
            await asyncio.sleep(1)
            
            # Log periodic stats
            if monitor.stats['detections'] % 60 == 0:  # Every minute
                stats = monitor.get_stats()
                logger.info(f"Monitor stats: {json.dumps(stats['current_state'], indent=2)}")
                
    except KeyboardInterrupt:
        pass
    finally:
        await monitor.stop()


if __name__ == '__main__':
    asyncio.run(main())