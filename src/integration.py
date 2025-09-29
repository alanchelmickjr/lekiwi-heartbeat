"""Integration module for the new robust discovery and state management system."""

import asyncio
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import logging
import structlog
from prometheus_client import Counter, Histogram, Gauge, start_http_server

from .state_manager import StateManager
from .discovery_service import OptimizedDiscoveryService
from .cache_manager import CacheManager
from .models.robot_state import RobotState
from .events.base import EventBus, EventHandler, Event


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Prometheus metrics
discovery_duration = Histogram('robot_discovery_duration_seconds', 'Time spent discovering robots')
discovery_count = Counter('robots_discovered_total', 'Total number of robots discovered')
robot_state_transitions = Counter('robot_state_transitions_total', 'Total state transitions', ['from_state', 'to_state'])
active_robots = Gauge('active_robots', 'Number of active robots')
failed_robots = Gauge('failed_robots', 'Number of failed robots')
cache_hits = Counter('cache_hits_total', 'Total cache hits')
cache_misses = Counter('cache_misses_total', 'Total cache misses')


class RobotManagementSystem:
    """
    Main integration class for the robust robot management system.
    Coordinates discovery, state management, caching, and monitoring.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Initialize the robot management system."""
        self.config = self._load_config(config_path)
        self.state_manager = None
        self.discovery_service = None
        self.cache_manager = None
        self.event_bus = EventBus()
        self._running = False
        self._tasks = []
        
        # Register event handlers
        self._register_event_handlers()
    
    def _load_config(self, config_path: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from file or environment."""
        if config_path and Path(config_path).exists():
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        else:
            # Default configuration
            config = {
                'database': {
                    'host': os.getenv('DB_HOST', 'localhost'),
                    'port': int(os.getenv('DB_PORT', 5432)),
                    'database': os.getenv('DB_NAME', 'lekiwi_robots'),
                    'user': os.getenv('DB_USER', 'lekiwi'),
                    'password': os.getenv('DB_PASSWORD', 'lekiwi_secure_pass')
                },
                'redis': {
                    'host': os.getenv('REDIS_HOST', 'localhost'),
                    'port': int(os.getenv('REDIS_PORT', 6379)),
                    'db': int(os.getenv('REDIS_DB', 0)),
                    'password': os.getenv('REDIS_PASSWORD', None)
                },
                'discovery': {
                    'network': os.getenv('DISCOVERY_NETWORK', '192.168.88.0/24'),
                    'max_workers': 50,
                    'parallel_scans': 100,
                    'continuous_discovery': True,
                    'discovery_interval': 30
                },
                'metrics': {
                    'enabled': True,
                    'port': 9090
                }
            }
        
        return config
    
    def _register_event_handlers(self):
        """Register event handlers for system events."""
        
        class MetricsHandler(EventHandler):
            """Update metrics based on events."""
            
            def handle(self, event: Event) -> None:
                if event.event_type.value == 'robot_discovered':
                    discovery_count.inc()
                elif event.event_type.value.startswith('robot_'):
                    # Track state transitions
                    robot_state_transitions.labels(
                        from_state='unknown',
                        to_state=event.event_type.value
                    ).inc()
            
            def can_handle(self, event: Event) -> bool:
                return True
        
        class LoggingHandler(EventHandler):
            """Log all events."""
            
            def handle(self, event: Event) -> None:
                logger.info(
                    "Event processed",
                    event_type=event.event_type.value,
                    aggregate_id=str(event.aggregate_id),
                    timestamp=event.created_at.isoformat()
                )
            
            def can_handle(self, event: Event) -> bool:
                return True
        
        # Register handlers
        self.event_bus.register_global_handler(MetricsHandler())
        self.event_bus.register_global_handler(LoggingHandler())
    
    async def start(self):
        """Start the robot management system."""
        logger.info("Starting Robot Management System...")
        
        try:
            # Initialize cache manager
            if self.config.get('redis'):
                self.cache_manager = CacheManager(**self.config['redis'])
                await self.cache_manager.initialize_async()
                logger.info("Cache manager initialized")
            
            # Initialize state manager
            self.state_manager = StateManager(
                db_config=self.config['database'],
                cache_config=self.config.get('redis'),
                pool_size=20,
                max_queries=50
            )
            await self.state_manager.start()
            logger.info("State manager initialized")
            
            # Initialize discovery service
            self.discovery_service = OptimizedDiscoveryService(
                cache_manager=self.cache_manager,
                max_workers=self.config['discovery']['max_workers'],
                timeout=2.0
            )
            logger.info("Discovery service initialized")
            
            # Start metrics server
            if self.config.get('metrics', {}).get('enabled'):
                start_http_server(self.config['metrics']['port'])
                logger.info(f"Metrics server started on port {self.config['metrics']['port']}")
            
            # Start background tasks
            self._running = True
            
            # Start continuous discovery
            if self.config['discovery'].get('continuous_discovery'):
                task = asyncio.create_task(self._continuous_discovery())
                self._tasks.append(task)
            
            # Start health monitoring
            task = asyncio.create_task(self._monitor_robot_health())
            self._tasks.append(task)
            
            # Start metrics updater
            task = asyncio.create_task(self._update_metrics())
            self._tasks.append(task)
            
            logger.info("Robot Management System started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start system: {e}")
            await self.stop()
            raise
    
    async def stop(self):
        """Stop the robot management system."""
        logger.info("Stopping Robot Management System...")
        
        self._running = False
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Stop components
        if self.state_manager:
            await self.state_manager.stop()
        
        if self.cache_manager:
            self.cache_manager.close()
        
        logger.info("Robot Management System stopped")
    
    async def _continuous_discovery(self):
        """Run continuous robot discovery."""
        network = self.config['discovery']['network']
        interval = self.config['discovery']['discovery_interval']
        
        while self._running:
            try:
                with discovery_duration.time():
                    # Run discovery
                    results = await self.discovery_service.discover_network(
                        network=network,
                        parallel_scans=self.config['discovery']['parallel_scans']
                    )
                
                logger.info(
                    "Discovery completed",
                    robots_found=results['metrics']['robots_found'],
                    duration=results['duration_seconds'],
                    network=network
                )
                
                # Process discovered robots
                for robot_info in results['robots']:
                    await self._process_discovered_robot(robot_info)
                
                # Wait before next discovery
                await asyncio.sleep(interval)
                
            except Exception as e:
                logger.error(f"Error in continuous discovery: {e}")
                await asyncio.sleep(interval)
    
    async def _process_discovered_robot(self, robot_info: Dict[str, Any]):
        """Process a discovered robot."""
        try:
            # Check if robot already exists
            existing = await self.state_manager.get_robot_by_ip(robot_info['ip'])
            
            if not existing:
                # Create new robot
                robot_id = await self.state_manager.handle_robot_discovered(
                    ip_address=robot_info['ip'],
                    hostname=robot_info.get('hostname'),
                    robot_type=robot_info.get('robot_type', 'unknown'),
                    model=robot_info.get('model'),
                    discovery_method=robot_info.get('discovery_method', 'websocket'),
                    response_time_ms=robot_info.get('response_time_ms')
                )
                
                logger.info(f"New robot discovered: {robot_id} at {robot_info['ip']}")
                
                # Check if it needs provisioning
                if robot_info.get('requires_provisioning'):
                    await self._provision_robot(robot_id)
            else:
                # Update heartbeat for existing robot
                await self._update_robot_heartbeat(existing['robot_id'])
                
        except Exception as e:
            logger.error(f"Error processing discovered robot: {e}")
    
    async def _provision_robot(self, robot_id: str):
        """Provision a newly discovered robot."""
        try:
            # TODO: Implement actual provisioning logic
            # This would involve deploying software, configuring settings, etc.
            
            success = await self.state_manager.handle_robot_provisioned(
                robot_id=robot_id,
                deployment_version="1.0.0",
                config={'auto_provisioned': True}
            )
            
            if success:
                logger.info(f"Robot {robot_id} provisioned successfully")
            else:
                logger.warning(f"Failed to provision robot {robot_id}")
                
        except Exception as e:
            logger.error(f"Error provisioning robot {robot_id}: {e}")
    
    async def _update_robot_heartbeat(self, robot_id: str):
        """Update robot heartbeat."""
        # This would be called when we receive heartbeat from robot
        pass
    
    async def _monitor_robot_health(self):
        """Monitor health of all robots."""
        while self._running:
            try:
                # Get all robots
                robots = await self.state_manager.get_robots_by_state(RobotState.ACTIVE)
                
                for robot in robots:
                    # Check last heartbeat
                    if robot.get('last_heartbeat'):
                        last_heartbeat = datetime.fromisoformat(robot['last_heartbeat'])
                        age = (datetime.utcnow() - last_heartbeat).total_seconds()
                        
                        if age > 300:  # 5 minutes
                            # Mark as failed
                            await self.state_manager.handle_robot_failed(
                                robot_id=robot['robot_id'],
                                error_message="Heartbeat timeout",
                                failure_type="connection"
                            )
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Error monitoring robot health: {e}")
                await asyncio.sleep(30)
    
    async def _update_metrics(self):
        """Update Prometheus metrics."""
        while self._running:
            try:
                # Get metrics from state manager
                metrics = await self.state_manager.get_metrics()
                
                # Update gauges
                robot_states = metrics.get('robots', {}).get('by_state', {})
                active_robots.set(robot_states.get('active', 0))
                failed_robots.set(robot_states.get('failed', 0))
                
                await asyncio.sleep(10)  # Update every 10 seconds
                
            except Exception as e:
                logger.error(f"Error updating metrics: {e}")
                await asyncio.sleep(10)
    
    # Public API methods
    
    async def discover_robots(self, network: Optional[str] = None) -> Dict[str, Any]:
        """Manually trigger robot discovery."""
        network = network or self.config['discovery']['network']
        
        with discovery_duration.time():
            results = await self.discovery_service.discover_network(
                network=network,
                parallel_scans=self.config['discovery']['parallel_scans']
            )
        
        # Process discovered robots
        for robot_info in results['robots']:
            await self._process_discovered_robot(robot_info)
        
        return results
    
    async def get_robot(self, robot_id: str) -> Optional[Dict[str, Any]]:
        """Get robot by ID."""
        # Try cache first
        if self.cache_manager:
            cached = await self.cache_manager.async_get_robot(robot_id)
            if cached:
                cache_hits.inc()
                return cached
            cache_misses.inc()
        
        # Get from state manager
        return await self.state_manager.get_robot(robot_id)
    
    async def get_all_robots(self) -> List[Dict[str, Any]]:
        """Get all robots."""
        # Try cache first
        if self.cache_manager:
            cached = await self.cache_manager.async_get_all_robots()
            if cached:
                cache_hits.inc()
                return cached
            cache_misses.inc()
        
        # Get from state manager
        robots = []
        for state in RobotState:
            state_robots = await self.state_manager.get_robots_by_state(state)
            robots.extend(state_robots)
        
        return robots
    
    async def get_healthy_robots(self) -> List[Dict[str, Any]]:
        """Get all healthy robots."""
        return await self.state_manager.get_healthy_robots()
    
    async def get_deployable_robots(self) -> List[Dict[str, Any]]:
        """Get robots that can receive deployments."""
        return await self.state_manager.get_deployable_robots()
    
    async def mark_robot_failed(self, robot_id: str, error_message: str) -> bool:
        """Mark a robot as failed."""
        return await self.state_manager.handle_robot_failed(
            robot_id=robot_id,
            error_message=error_message,
            failure_type="manual"
        )
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get system metrics and statistics."""
        state_metrics = await self.state_manager.get_metrics()
        discovery_stats = self.discovery_service.get_discovery_stats()
        
        return {
            'state_management': state_metrics,
            'discovery': discovery_stats,
            'uptime': datetime.utcnow().isoformat()
        }


# FastAPI integration
def create_fastapi_routes(app, system: RobotManagementSystem):
    """Create FastAPI routes for the robot management system."""
    from fastapi import HTTPException, BackgroundTasks
    from fastapi.responses import JSONResponse
    
    @app.get("/api/v2/robots")
    async def list_robots():
        """List all robots using new system."""
        robots = await system.get_all_robots()
        return JSONResponse(content={'robots': robots, 'total': len(robots)})
    
    @app.get("/api/v2/robots/{robot_id}")
    async def get_robot(robot_id: str):
        """Get robot by ID."""
        robot = await system.get_robot(robot_id)
        if not robot:
            raise HTTPException(status_code=404, detail="Robot not found")
        return robot
    
    @app.post("/api/v2/discover")
    async def trigger_discovery(background_tasks: BackgroundTasks):
        """Trigger manual discovery."""
        background_tasks.add_task(system.discover_robots)
        return {"status": "Discovery started"}
    
    @app.get("/api/v2/robots/healthy")
    async def get_healthy_robots():
        """Get healthy robots."""
        robots = await system.get_healthy_robots()
        return {'robots': robots, 'total': len(robots)}
    
    @app.get("/api/v2/robots/deployable")
    async def get_deployable_robots():
        """Get deployable robots."""
        robots = await system.get_deployable_robots()
        return {'robots': robots, 'total': len(robots)}
    
    @app.get("/api/v2/metrics")
    async def get_metrics():
        """Get system metrics."""
        return await system.get_system_metrics()
    
    @app.post("/api/v2/robots/{robot_id}/fail")
    async def mark_robot_failed(robot_id: str, error_message: str = "Manual failure"):
        """Mark robot as failed."""
        success = await system.mark_robot_failed(robot_id, error_message)
        if not success:
            raise HTTPException(status_code=400, detail="Failed to mark robot as failed")
        return {"status": "Robot marked as failed"}


# Example usage
async def main():
    """Example of using the robot management system."""
    # Create system
    system = RobotManagementSystem(config_path='config/system_config.yaml')
    
    # Start system
    await system.start()
    
    try:
        # Let it run
        await asyncio.sleep(3600)  # Run for 1 hour
    finally:
        # Stop system
        await system.stop()


if __name__ == "__main__":
    asyncio.run(main())