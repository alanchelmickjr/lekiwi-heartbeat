# Teleoperation Monitoring System

A high-performance, real-time teleoperation monitoring system for Lekiwi and XLE robots that accurately tracks robot usage with minimal performance impact.

## Features

### 🎯 Multi-Signal Detection
- **WebRTC Monitoring**: Tracks peer connections and active video streams
- **ZMQ Flow Detection**: Monitors control command message flow
- **Input Device Tracking**: Detects joystick, gamepad, and keyboard inputs
- **Network Pattern Analysis**: Identifies teleoperation traffic patterns
- **Operator Identification**: Tracks who is controlling the robot

### ⚡ Real-Time Updates
- **WebSocket Streaming**: Push-based status updates (no polling)
- **Event Broadcasting**: Instant notifications of state changes
- **Low Latency**: <100ms detection and notification target
- **Metrics Dashboard**: Real-time performance metrics

### 🚀 Performance Optimized
- **Minimal Overhead**: <1% CPU and <10MB RAM usage
- **Lock-Free Buffers**: Ring buffer for telemetry data
- **Shared Memory IPC**: Zero-copy inter-process communication
- **Async Operations**: Non-blocking I/O throughout

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Teleoperation Monitor                   │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Detection Layer                      │  │
│  ├──────────────────────────────────────────────────┤  │
│  │  WebRTC    ZMQ      Input     Network           │  │
│  │  Detector  Detector Detector  Detector          │  │
│  └──────────────────────────────────────────────────┘  │
│                         │                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Analysis Engine                      │  │
│  ├──────────────────────────────────────────────────┤  │
│  │  Signal Correlation │ Confidence Scoring         │  │
│  │  Pattern Recognition │ State Management          │  │
│  └──────────────────────────────────────────────────┘  │
│                         │                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │              Streaming Layer                      │  │
│  ├──────────────────────────────────────────────────┤  │
│  │  WebSocket Server │ Metrics Collector            │  │
│  │  Event Broadcasting │ Alert System               │  │
│  └──────────────────────────────────────────────────┘  │
│                         │                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │           Optimization Layer                      │  │
│  ├──────────────────────────────────────────────────┤  │
│  │  Shared Memory │ Ring Buffer │ IPC              │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Installation

### Prerequisites
```bash
# System requirements
- Python 3.8+
- Linux (for full input detection support)
- Root/sudo access (for network monitoring)

# Python packages
pip install -r requirements.txt
```

### Install Dependencies
```bash
pip install \
    aiohttp \
    psutil \
    pyzmq \
    numpy \
    evdev  # Linux only, for input detection
```

### Quick Start
```bash
# Run the teleoperation monitor
python teleoperation/monitor.py --robot-type lekiwi

# With custom WebSocket port
python teleoperation/monitor.py --robot-type xle --websocket-port 9000

# With debug logging
python teleoperation/monitor.py --log-level DEBUG
```

## Usage

### Basic Monitoring
```python
from teleoperation.monitor import TeleoperationMonitor

# Create monitor
monitor = TeleoperationMonitor(robot_type='lekiwi')

# Start monitoring
await monitor.start()

# Get current state
state = monitor.get_state()
print(f"Teleoperation active: {state.is_active}")
print(f"Operators: {state.operators}")
print(f"Confidence: {state.confidence}%")

# Get statistics
stats = monitor.get_stats()
print(f"Total detections: {stats['detections']}")
print(f"State changes: {stats['state_changes']}")

# Stop monitoring
await monitor.stop()
```

### WebSocket Client
```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8765/ws');

ws.onopen = () => {
    console.log('Connected to teleoperation monitor');
    
    // Subscribe to updates
    ws.send(JSON.stringify({
        type: 'subscribe',
        topics: ['state_update', 'operator_connected']
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch(data.type) {
        case 'state_update':
            console.log('State:', data.data.state);
            break;
        case 'operator_connected':
            console.log('Operator connected:', data.data);
            break;
        case 'latency_warning':
            console.warn('High latency:', data.data);
            break;
    }
};
```

### HTTP API Endpoints
```bash
# Get current status
curl http://localhost:8765/status

# Get metrics
curl http://localhost:8765/metrics

# Health check
curl http://localhost:8765/health
```

## Configuration

### Environment Variables
```bash
# Robot type (lekiwi or xle)
export ROBOT_TYPE=lekiwi

# WebSocket server port
export WEBSOCKET_PORT=8765

# Shared memory namespace
export SHM_NAMESPACE=teleoperation

# Log level
export LOG_LEVEL=INFO
```

### Configuration File
```python
config = {
    'robot_type': 'lekiwi',
    'websocket_port': 8765,
    
    # Detection thresholds
    'detection': {
        'confidence_threshold': 70,  # Minimum confidence for positive detection
        'detection_interval': 0.1,   # Detection loop interval (seconds)
        'update_interval': 0.5       # State broadcast interval (seconds)
    },
    
    # Port configurations
    'ports': {
        'zmq': {
            'control_commands': 5555,
            'state_feedback': 5556,
            'video_stream': 5557,
            'telemetry': 5558
        },
        'webrtc': {
            'stun': [3478, 19302],
            'turn': [3478, 5349],
            'media': range(10000, 60000)
        }
    },
    
    # Performance tuning
    'performance': {
        'buffer_size': 65536,       # Ring buffer size (bytes)
        'max_clients': 100,          # Max WebSocket clients
        'metrics_window': 60,        # Metrics aggregation window (seconds)
        'alert_cooldown': 30         # Alert cooldown period (seconds)
    }
}

monitor = TeleoperationMonitor(config=config)
```

## Detection Methods

### 1. WebRTC Detection
Monitors WebRTC peer connections by:
- Tracking STUN/TURN server connections
- Monitoring RTP/RTCP media streams
- Detecting browser/Electron WebRTC processes
- Analyzing connection statistics (RTT, bandwidth, packet loss)

### 2. ZMQ Detection
Monitors ZeroMQ message flows by:
- Subscribing to control command topics
- Analyzing message patterns and rates
- Detecting bidirectional command/feedback flows
- Identifying operator IDs in message headers

### 3. Input Detection
Tracks input devices by:
- Monitoring `/dev/input` devices (Linux)
- Detecting joystick/gamepad connections
- Tracking keyboard teleoperation keys
- Analyzing input patterns and rates

### 4. Network Detection
Analyzes network traffic patterns by:
- Identifying video streaming flows (high bandwidth)
- Detecting control command flows (low latency)
- Correlating multiple flows
- Checking for teleoperation-specific patterns

## Performance Metrics

### Key Metrics Tracked
- **Latency**: Network round-trip time (target: <100ms)
- **Bandwidth**: Video and control bandwidth usage
- **Packet Loss**: Network packet loss percentage
- **FPS**: Video stream frame rate
- **Command Rate**: Control command frequency (Hz)
- **CPU Usage**: Monitor process CPU usage (target: <1%)
- **Memory Usage**: Monitor process memory (target: <10MB)

### Alerts
The system generates alerts for:
- High latency (>100ms)
- Excessive bandwidth usage (>50 Mbps)
- Packet loss (>5%)
- Low FPS (<15 fps)
- Low command rate (<5 Hz)
- Resource usage spikes

## Testing

### Run Tests
```bash
# Run all tests
python -m pytest teleoperation/tests/

# Run specific test file
python teleoperation/tests/test_monitor.py

# Run with coverage
python -m pytest --cov=teleoperation teleoperation/tests/

# Run benchmarks
python teleoperation/tests/test_monitor.py BenchmarkTests
```

### Test Coverage
- Unit tests for all detectors
- Integration tests for monitor coordination
- Performance benchmarks
- WebSocket streaming tests
- Shared memory tests

## Troubleshooting

### Common Issues

#### 1. Permission Denied for Network Monitoring
```bash
# Run with sudo for full network monitoring
sudo python teleoperation/monitor.py

# Or add capability (Linux)
sudo setcap cap_net_raw+ep $(which python3)
```

#### 2. Input Detection Not Working
```bash
# Check if evdev is installed (Linux)
pip install evdev

# Add user to input group
sudo usermod -a -G input $USER

# Logout and login again
```

#### 3. High CPU Usage
```python
# Increase detection interval
config = {
    'detection': {
        'detection_interval': 0.5,  # Reduce frequency
        'update_interval': 1.0
    }
}
```

#### 4. WebSocket Connection Issues
```bash
# Check if port is in use
lsof -i :8765

# Use different port
python teleoperation/monitor.py --websocket-port 9000
```

## Advanced Usage

### Custom Detectors
```python
from teleoperation.detectors.base import BaseDetector

class CustomDetector(BaseDetector):
    async def start(self):
        # Initialize detection
        pass
    
    async def detect(self):
        # Perform detection
        return {
            'active': True,
            'confidence': 85.0,
            'operator': 'custom_op'
        }
    
    async def stop(self):
        # Cleanup
        pass

# Add to monitor
monitor.add_detector('custom', CustomDetector())
```

### Custom Metrics
```python
# Record custom metrics
monitor.metrics_collector.record_metric(
    name='custom_metric',
    value=42.5,
    tags={'source': 'custom'}
)

# Add custom alert
def custom_alert_check(metrics):
    if metrics.get('custom_metric', 0) > 100:
        return {
            'severity': 'critical',
            'message': 'Custom metric exceeded threshold'
        }

monitor.metrics_collector.add_alert_check(custom_alert_check)
```

### Shared Memory Access
```python
from teleoperation.optimization.shared_memory import SharedMemoryManager

# Attach to existing shared memory
shm = SharedMemoryManager()
shm.initialize(create=False)

# Read current state
state = shm.read_state()
print(f"Teleoperation active: {state['is_active']}")

# Read metrics
metrics = shm.read_metrics()
print(f"Latency: {metrics['latency_ms']}ms")
```

## API Reference

### TeleoperationMonitor
Main monitoring service that coordinates all components.

**Methods:**
- `start()`: Start monitoring
- `stop()`: Stop monitoring
- `get_state()`: Get current teleoperation state
- `get_stats()`: Get monitoring statistics

### TeleoperationState
Current teleoperation state dataclass.

**Attributes:**
- `is_active`: Whether teleoperation is active
- `operators`: List of active operators
- `confidence`: Detection confidence (0-100)
- `start_time`: When teleoperation started
- `duration`: Current session duration
- Various metrics (latency, bandwidth, etc.)

### WebSocketStreamer
Real-time status streaming via WebSocket.

**Events:**
- `state_update`: State changed
- `operator_connected`: New operator
- `operator_disconnected`: Operator left
- `teleoperation_started`: Session started
- `teleoperation_stopped`: Session ended
- Various warning events

### MetricsCollector
Performance metrics collection and aggregation.

**Methods:**
- `record_metric()`: Record a metric value
- `get_summary()`: Get metric summary
- `add_alert_callback()`: Add alert handler

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

For issues, questions, or contributions, please open an issue on GitHub.