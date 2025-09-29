#!/usr/bin/env python3
"""
Metrics Collector
Collects and aggregates teleoperation performance metrics.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from collections import deque, defaultdict
import statistics

logger = logging.getLogger(__name__)


@dataclass
class TelemetryPoint:
    """Single telemetry data point."""
    timestamp: float  # Unix timestamp
    metric_name: str
    value: float
    tags: Dict[str, str] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class MetricSummary:
    """Summary statistics for a metric."""
    name: str
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float
    p95: float
    p99: float
    rate: float  # Per second
    
    @classmethod
    def from_values(cls, name: str, values: List[float], duration: float) -> 'MetricSummary':
        """Create summary from values."""
        if not values:
            return cls(
                name=name,
                count=0,
                mean=0,
                median=0,
                std_dev=0,
                min_value=0,
                max_value=0,
                p95=0,
                p99=0,
                rate=0
            )
        
        sorted_values = sorted(values)
        
        return cls(
            name=name,
            count=len(values),
            mean=statistics.mean(values),
            median=statistics.median(values),
            std_dev=statistics.stdev(values) if len(values) > 1 else 0,
            min_value=min(values),
            max_value=max(values),
            p95=sorted_values[int(len(values) * 0.95)] if values else 0,
            p99=sorted_values[int(len(values) * 0.99)] if values else 0,
            rate=len(values) / duration if duration > 0 else 0
        )


class MetricsCollector:
    """
    Collects and aggregates teleoperation metrics with minimal overhead.
    Uses ring buffers and batch processing for efficiency.
    """
    
    # Key metrics to track
    METRICS = {
        'latency_ms': {'window': 60, 'alert_threshold': 100},
        'bandwidth_mbps': {'window': 60, 'alert_threshold': 50},
        'packet_loss_pct': {'window': 60, 'alert_threshold': 5},
        'cpu_usage_pct': {'window': 60, 'alert_threshold': 80},
        'memory_usage_mb': {'window': 60, 'alert_threshold': 500},
        'fps': {'window': 30, 'alert_threshold': 15},  # Min FPS
        'command_rate_hz': {'window': 30, 'alert_threshold': 5},  # Min rate
        'connection_count': {'window': 60, 'alert_threshold': 10},
        'operator_count': {'window': 60, 'alert_threshold': 5}
    }
    
    def __init__(self, buffer_size: int = 10000):
        self.buffer_size = buffer_size
        
        # Ring buffer for telemetry points
        self.telemetry_buffer: Deque[TelemetryPoint] = deque(maxlen=buffer_size)
        
        # Metric-specific buffers for fast access
        self.metric_buffers: Dict[str, Deque[Tuple[float, float]]] = {
            metric: deque(maxlen=1000) for metric in self.METRICS
        }
        
        # Aggregated metrics
        self.summaries: Dict[str, MetricSummary] = {}
        
        # Alert tracking
        self.alerts: List[Dict] = []
        self.alert_callbacks = []
        
        # Performance tracking
        self.collection_stats = {
            'points_collected': 0,
            'points_dropped': 0,
            'aggregation_time_ms': 0,
            'last_aggregation': None
        }
        
        # Aggregation task
        self._running = False
        self._aggregation_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start metrics collection."""
        if self._running:
            return
            
        self._running = True
        self._aggregation_task = asyncio.create_task(self._aggregation_loop())
        logger.info("Metrics collector started")
    
    async def stop(self):
        """Stop metrics collection."""
        self._running = False
        
        if self._aggregation_task:
            self._aggregation_task.cancel()
            await asyncio.gather(self._aggregation_task, return_exceptions=True)
        
        logger.info("Metrics collector stopped")
    
    def record_metric(self, name: str, value: float, tags: Optional[Dict[str, str]] = None):
        """Record a metric value (non-blocking)."""
        try:
            timestamp = time.time()
            
            # Add to telemetry buffer
            point = TelemetryPoint(
                timestamp=timestamp,
                metric_name=name,
                value=value,
                tags=tags or {}
            )
            
            self.telemetry_buffer.append(point)
            
            # Add to metric-specific buffer if tracked
            if name in self.metric_buffers:
                self.metric_buffers[name].append((timestamp, value))
            
            self.collection_stats['points_collected'] += 1
            
        except Exception as e:
            logger.debug(f"Error recording metric: {e}")
            self.collection_stats['points_dropped'] += 1
    
    def record_latency(self, latency_ms: float, connection_id: Optional[str] = None):
        """Record network latency."""
        tags = {'connection_id': connection_id} if connection_id else {}
        self.record_metric('latency_ms', latency_ms, tags)
    
    def record_bandwidth(self, bandwidth_mbps: float, direction: str = 'both'):
        """Record bandwidth usage."""
        self.record_metric('bandwidth_mbps', bandwidth_mbps, {'direction': direction})
    
    def record_packet_loss(self, loss_pct: float):
        """Record packet loss percentage."""
        self.record_metric('packet_loss_pct', loss_pct)
    
    def record_fps(self, fps: float, stream_id: Optional[str] = None):
        """Record video frame rate."""
        tags = {'stream_id': stream_id} if stream_id else {}
        self.record_metric('fps', fps, tags)
    
    def record_command_rate(self, rate_hz: float):
        """Record command rate."""
        self.record_metric('command_rate_hz', rate_hz)
    
    def record_resource_usage(self, cpu_pct: float, memory_mb: float):
        """Record system resource usage."""
        self.record_metric('cpu_usage_pct', cpu_pct)
        self.record_metric('memory_usage_mb', memory_mb)
    
    def record_connections(self, count: int):
        """Record number of active connections."""
        self.record_metric('connection_count', count)
    
    def record_operators(self, count: int):
        """Record number of active operators."""
        self.record_metric('operator_count', count)
    
    async def _aggregation_loop(self):
        """Periodically aggregate metrics."""
        while self._running:
            try:
                start_time = time.time()
                
                # Aggregate metrics
                await self._aggregate_metrics()
                
                # Check for alerts
                await self._check_alerts()
                
                # Update aggregation stats
                aggregation_time_ms = (time.time() - start_time) * 1000
                self.collection_stats['aggregation_time_ms'] = aggregation_time_ms
                self.collection_stats['last_aggregation'] = datetime.now()
                
                # Aggregate every second
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in aggregation loop: {e}")
                await asyncio.sleep(5)
    
    async def _aggregate_metrics(self):
        """Aggregate metrics from buffers."""
        now = time.time()
        
        for metric_name, config in self.METRICS.items():
            window = config['window']
            
            # Get values within window
            if metric_name in self.metric_buffers:
                buffer = self.metric_buffers[metric_name]
                
                # Filter values within time window
                cutoff = now - window
                values = [
                    value for timestamp, value in buffer
                    if timestamp > cutoff
                ]
                
                # Create summary
                if values:
                    summary = MetricSummary.from_values(
                        name=metric_name,
                        values=values,
                        duration=window
                    )
                    self.summaries[metric_name] = summary
    
    async def _check_alerts(self):
        """Check for alert conditions."""
        now = datetime.now()
        
        for metric_name, config in self.METRICS.items():
            threshold = config['alert_threshold']
            
            if metric_name in self.summaries:
                summary = self.summaries[metric_name]
                
                # Check different alert conditions based on metric
                alert_triggered = False
                alert_reason = ""
                
                if metric_name in ['latency_ms', 'packet_loss_pct', 'cpu_usage_pct']:
                    # Alert if mean exceeds threshold
                    if summary.mean > threshold:
                        alert_triggered = True
                        alert_reason = f"Mean {summary.mean:.2f} exceeds threshold {threshold}"
                        
                elif metric_name in ['fps', 'command_rate_hz']:
                    # Alert if mean falls below threshold
                    if summary.mean < threshold and summary.count > 0:
                        alert_triggered = True
                        alert_reason = f"Mean {summary.mean:.2f} below threshold {threshold}"
                        
                elif metric_name == 'bandwidth_mbps':
                    # Alert if max exceeds threshold
                    if summary.max_value > threshold:
                        alert_triggered = True
                        alert_reason = f"Max {summary.max_value:.2f} exceeds threshold {threshold}"
                
                if alert_triggered:
                    alert = {
                        'timestamp': now,
                        'metric': metric_name,
                        'severity': 'warning',
                        'reason': alert_reason,
                        'summary': asdict(summary)
                    }
                    
                    self.alerts.append(alert)
                    
                    # Limit alert history
                    if len(self.alerts) > 100:
                        self.alerts.pop(0)
                    
                    # Trigger callbacks
                    for callback in self.alert_callbacks:
                        try:
                            await callback(alert)
                        except Exception as e:
                            logger.error(f"Error in alert callback: {e}")
    
    def add_alert_callback(self, callback):
        """Add callback for alerts."""
        self.alert_callbacks.append(callback)
    
    def get_summary(self, metric_name: str) -> Optional[MetricSummary]:
        """Get summary for a specific metric."""
        return self.summaries.get(metric_name)
    
    def get_all_summaries(self) -> Dict[str, MetricSummary]:
        """Get all metric summaries."""
        return self.summaries.copy()
    
    def get_recent_telemetry(self, count: int = 100) -> List[TelemetryPoint]:
        """Get recent telemetry points."""
        return list(self.telemetry_buffer)[-count:]
    
    def get_metrics(self) -> Dict:
        """Get current metrics state."""
        return {
            'summaries': {
                name: asdict(summary)
                for name, summary in self.summaries.items()
            },
            'alerts': self.alerts[-10:],  # Last 10 alerts
            'collection_stats': self.collection_stats,
            'buffer_usage': {
                'telemetry_buffer': len(self.telemetry_buffer),
                'metric_buffers': {
                    name: len(buffer)
                    for name, buffer in self.metric_buffers.items()
                }
            }
        }
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        
        for name, summary in self.summaries.items():
            # Clean metric name for Prometheus
            prom_name = name.replace('.', '_').replace('-', '_')
            
            # Export various statistics
            lines.append(f"# HELP {prom_name} {name} statistics")
            lines.append(f"# TYPE {prom_name} gauge")
            lines.append(f"{prom_name}_mean {summary.mean:.3f}")
            lines.append(f"{prom_name}_median {summary.median:.3f}")
            lines.append(f"{prom_name}_min {summary.min_value:.3f}")
            lines.append(f"{prom_name}_max {summary.max_value:.3f}")
            lines.append(f"{prom_name}_p95 {summary.p95:.3f}")
            lines.append(f"{prom_name}_p99 {summary.p99:.3f}")
            lines.append(f"{prom_name}_rate {summary.rate:.3f}")
            lines.append("")
        
        return '\n'.join(lines)