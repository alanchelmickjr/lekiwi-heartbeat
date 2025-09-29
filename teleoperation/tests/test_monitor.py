#!/usr/bin/env python3
"""
Tests for Teleoperation Monitor
"""

import asyncio
import unittest
import time
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from teleoperation.monitor import TeleoperationMonitor, TeleoperationState


class TestTeleoperationState(unittest.TestCase):
    """Test TeleoperationState dataclass."""
    
    def test_initialization(self):
        """Test state initialization."""
        state = TeleoperationState()
        
        self.assertFalse(state.is_active)
        self.assertEqual(state.operators, [])
        self.assertEqual(state.confidence, 0.0)
        self.assertIsNone(state.start_time)
        
    def test_to_dict(self):
        """Test dictionary conversion."""
        state = TeleoperationState(
            is_active=True,
            operators=['operator1'],
            start_time=datetime.now(),
            confidence=85.5
        )
        
        data = state.to_dict()
        
        self.assertTrue(data['is_active'])
        self.assertEqual(data['operators'], ['operator1'])
        self.assertEqual(data['confidence'], 85.5)
        self.assertIn('start_time', data)


class TestTeleoperationMonitor(unittest.TestCase):
    """Test TeleoperationMonitor class."""
    
    def setUp(self):
        """Setup test fixtures."""
        self.monitor = TeleoperationMonitor(robot_type='lekiwi')
        
    def tearDown(self):
        """Cleanup after tests."""
        asyncio.run(self.cleanup())
    
    async def cleanup(self):
        """Async cleanup."""
        if self.monitor._running:
            await self.monitor.stop()
    
    @patch('teleoperation.monitor.WebRTCDetector')
    @patch('teleoperation.monitor.ZMQDetector')
    @patch('teleoperation.monitor.InputDetector')
    @patch('teleoperation.monitor.NetworkDetector')
    def test_initialization(self, mock_network, mock_input, mock_zmq, mock_webrtc):
        """Test monitor initialization."""
        monitor = TeleoperationMonitor(robot_type='xle')
        
        self.assertEqual(monitor.robot_type, 'xle')
        self.assertIsNotNone(monitor.webrtc_detector)
        self.assertIsNotNone(monitor.zmq_detector)
        self.assertIsNotNone(monitor.input_detector)
        self.assertIsNotNone(monitor.network_detector)
        self.assertFalse(monitor._running)
    
    def test_analyze_signals_no_activity(self):
        """Test signal analysis with no teleoperation activity."""
        signals = {
            'webrtc': {'active': False, 'connections': 0, 'operators': [], 'metrics': {}},
            'zmq': {'active': False, 'flows': 0, 'operators': [], 'metrics': {}},
            'input': {'active': False, 'sessions': 0, 'confidence': 0, 'metrics': {}},
            'network': {'active': False, 'flows': 0, 'confidence': 0, 'metrics': {}},
            'resources': {'cpu_percent': 10, 'memory_mb': 100, 'threads': 5}
        }
        
        analysis = self.monitor._analyze_signals(signals)
        
        self.assertFalse(analysis['is_teleoperation'])
        self.assertEqual(analysis['confidence'], 0.0)
        self.assertEqual(len(analysis['operators']), 0)
    
    def test_analyze_signals_webrtc_active(self):
        """Test signal analysis with active WebRTC."""
        signals = {
            'webrtc': {
                'active': True,
                'connections': 2,
                'operators': ['operator1'],
                'metrics': {'avg_rtt_ms': 25, 'total_bandwidth_mbps': 5.5}
            },
            'zmq': {'active': False, 'flows': 0, 'operators': [], 'metrics': {}},
            'input': {'active': False, 'sessions': 0, 'confidence': 0, 'metrics': {}},
            'network': {'active': False, 'flows': 0, 'confidence': 0, 'metrics': {}},
            'resources': {'cpu_percent': 15, 'memory_mb': 120, 'threads': 6}
        }
        
        analysis = self.monitor._analyze_signals(signals)
        
        self.assertTrue(analysis['is_teleoperation'])
        self.assertGreater(analysis['confidence'], 70)
        self.assertIn('operator1', analysis['operators'])
        self.assertIn('WebRTC', analysis['reasons'][0])
    
    def test_analyze_signals_multiple_active(self):
        """Test signal analysis with multiple active signals."""
        signals = {
            'webrtc': {
                'active': True,
                'connections': 1,
                'operators': ['operator1'],
                'metrics': {'avg_rtt_ms': 30}
            },
            'zmq': {
                'active': True,
                'flows': 3,
                'operators': ['operator1'],
                'metrics': {'total_message_rate': 50}
            },
            'input': {
                'active': True,
                'sessions': 1,
                'confidence': 75,
                'metrics': {}
            },
            'network': {
                'active': True,
                'flows': 5,
                'confidence': 80,
                'metrics': {}
            },
            'resources': {'cpu_percent': 25, 'memory_mb': 150, 'threads': 8}
        }
        
        analysis = self.monitor._analyze_signals(signals)
        
        self.assertTrue(analysis['is_teleoperation'])
        self.assertGreater(analysis['confidence'], 80)
        self.assertGreater(len(analysis['reasons']), 2)
    
    def test_update_state_transition(self):
        """Test state transitions."""
        # Initial state - not active
        self.monitor.state = TeleoperationState(is_active=False)
        
        # Teleoperation starts
        analysis = {
            'is_teleoperation': True,
            'confidence': 85.0,
            'operators': {'operator1'},
            'metrics': {
                'latency_ms': 20,
                'bandwidth_mbps': 5,
                'packet_loss_pct': 0.1,
                'fps': 30,
                'command_rate_hz': 50
            }
        }
        
        state_changed = self.monitor._update_state(analysis)
        
        self.assertTrue(state_changed)
        self.assertTrue(self.monitor.state.is_active)
        self.assertEqual(self.monitor.state.confidence, 85.0)
        self.assertIsNotNone(self.monitor.state.start_time)
        
        # Teleoperation continues
        state_changed = self.monitor._update_state(analysis)
        
        self.assertFalse(state_changed)
        self.assertTrue(self.monitor.state.is_active)
        
        # Teleoperation ends
        analysis['is_teleoperation'] = False
        analysis['confidence'] = 0.0
        
        state_changed = self.monitor._update_state(analysis)
        
        self.assertTrue(state_changed)
        self.assertFalse(self.monitor.state.is_active)
        self.assertIsNone(self.monitor.state.start_time)
    
    def test_extract_performance_metrics(self):
        """Test performance metrics extraction."""
        signals = {
            'webrtc': {
                'metrics': {
                    'avg_rtt_ms': 25.5,
                    'total_bandwidth_mbps': 8.2
                }
            },
            'zmq': {
                'metrics': {
                    'total_message_rate': 75.3
                }
            },
            'network': {
                'metrics': {
                    'total_bandwidth_mbps': 10.5,
                    'avg_packet_loss_pct': 0.5
                }
            }
        }
        
        metrics = self.monitor._extract_performance_metrics(signals)
        
        self.assertEqual(metrics['latency_ms'], 25.5)
        self.assertEqual(metrics['bandwidth_mbps'], 10.5)  # Takes max
        self.assertEqual(metrics['packet_loss_pct'], 0.5)
        self.assertEqual(metrics['command_rate_hz'], 75.3)


class TestTeleoperationMonitorAsync(unittest.TestCase):
    """Test async methods of TeleoperationMonitor."""
    
    def setUp(self):
        """Setup test fixtures."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        
    def tearDown(self):
        """Cleanup after tests."""
        self.loop.close()
    
    @patch('teleoperation.monitor.SharedMemoryManager')
    @patch('teleoperation.monitor.SharedRingBuffer')
    async def test_start_stop(self, mock_buffer, mock_memory):
        """Test starting and stopping the monitor."""
        monitor = TeleoperationMonitor()
        
        # Mock detector starts
        monitor.webrtc_detector.start = AsyncMock()
        monitor.zmq_detector.start = AsyncMock()
        monitor.input_detector.start = AsyncMock()
        monitor.network_detector.start = AsyncMock()
        
        # Mock streamer starts
        monitor.websocket_streamer.start = AsyncMock()
        monitor.metrics_collector.start = AsyncMock()
        
        # Start monitor
        await monitor.start()
        
        self.assertTrue(monitor._running)
        self.assertIsNotNone(monitor._monitor_task)
        
        # Stop monitor
        monitor.webrtc_detector.stop = AsyncMock()
        monitor.zmq_detector.stop = AsyncMock()
        monitor.input_detector.stop = AsyncMock()
        monitor.network_detector.stop = AsyncMock()
        monitor.websocket_streamer.stop = AsyncMock()
        monitor.metrics_collector.stop = AsyncMock()
        
        await monitor.stop()
        
        self.assertFalse(monitor._running)
    
    async def test_collect_signals(self):
        """Test signal collection from detectors."""
        monitor = TeleoperationMonitor()
        
        # Mock detector responses
        monitor.webrtc_detector.get_active_connections = Mock(return_value=[])
        monitor.webrtc_detector.get_operator_sessions = Mock(return_value={})
        monitor.webrtc_detector.get_metrics = Mock(return_value={})
        
        monitor.zmq_detector.get_active_flows = Mock(return_value=[])
        monitor.zmq_detector.get_operator_flows = Mock(return_value={})
        monitor.zmq_detector.get_metrics = Mock(return_value={})
        
        monitor.input_detector.get_active_sessions = Mock(return_value=[])
        monitor.input_detector.get_teleoperation_confidence = Mock(return_value=0)
        monitor.input_detector.get_metrics = Mock(return_value={})
        
        monitor.network_detector.get_active_flows = Mock(return_value=[])
        monitor.network_detector.teleoperation_detected = False
        monitor.network_detector.detection_confidence = 0
        monitor.network_detector.get_metrics = Mock(return_value={})
        
        signals = await monitor._collect_signals()
        
        self.assertIn('webrtc', signals)
        self.assertIn('zmq', signals)
        self.assertIn('input', signals)
        self.assertIn('network', signals)
        self.assertIn('resources', signals)


class AsyncMock(MagicMock):
    """Async mock for testing."""
    async def __call__(self, *args, **kwargs):
        return super(AsyncMock, self).__call__(*args, **kwargs)


class BenchmarkTests(unittest.TestCase):
    """Performance benchmark tests."""
    
    def test_detection_latency(self):
        """Test detection latency is under 100ms."""
        monitor = TeleoperationMonitor()
        
        # Mock signal collection
        signals = {
            'webrtc': {'active': True, 'connections': 1, 'operators': ['op1'], 'metrics': {}},
            'zmq': {'active': False, 'flows': 0, 'operators': [], 'metrics': {}},
            'input': {'active': False, 'sessions': 0, 'confidence': 0, 'metrics': {}},
            'network': {'active': False, 'flows': 0, 'confidence': 0, 'metrics': {}},
            'resources': {'cpu_percent': 10, 'memory_mb': 100, 'threads': 5}
        }
        
        # Measure detection time
        start = time.time()
        
        analysis = monitor._analyze_signals(signals)
        monitor._update_state(analysis)
        
        elapsed = (time.time() - start) * 1000  # Convert to ms
        
        self.assertLess(elapsed, 100, f"Detection took {elapsed:.2f}ms, should be <100ms")
    
    def test_memory_usage(self):
        """Test memory usage is under 10MB."""
        import psutil
        
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Create monitor and components
        monitor = TeleoperationMonitor()
        
        # Simulate some operations
        for _ in range(100):
            state = TeleoperationState(
                is_active=True,
                operators=['op1', 'op2'],
                confidence=85.5
            )
            state.to_dict()
        
        current_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = current_memory - initial_memory
        
        self.assertLess(memory_increase, 10, f"Memory increased by {memory_increase:.2f}MB, should be <10MB")
    
    def test_cpu_usage(self):
        """Test CPU usage is under 1%."""
        import psutil
        
        monitor = TeleoperationMonitor()
        
        # Mock signals
        signals = {
            'webrtc': {'active': False, 'connections': 0, 'operators': [], 'metrics': {}},
            'zmq': {'active': False, 'flows': 0, 'operators': [], 'metrics': {}},
            'input': {'active': False, 'sessions': 0, 'confidence': 0, 'metrics': {}},
            'network': {'active': False, 'flows': 0, 'confidence': 0, 'metrics': {}},
            'resources': {'cpu_percent': 0, 'memory_mb': 0, 'threads': 0}
        }
        
        # Measure CPU over multiple iterations
        process = psutil.Process()
        cpu_samples = []
        
        for _ in range(10):
            start_cpu = process.cpu_percent()
            
            # Perform operations
            for _ in range(10):
                analysis = monitor._analyze_signals(signals)
                monitor._update_state(analysis)
            
            time.sleep(0.1)
            end_cpu = process.cpu_percent()
            
            cpu_samples.append(end_cpu)
        
        avg_cpu = sum(cpu_samples) / len(cpu_samples)
        
        self.assertLess(avg_cpu, 1.0, f"Average CPU usage {avg_cpu:.2f}%, should be <1%")


if __name__ == '__main__':
    unittest.main()