"""State manager with CQRS pattern and event sourcing."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import UUID, uuid4
import logging

import asyncpg
from asyncpg.pool import Pool
import backoff

from .events.base import Event, EventType, EventStore, EventBus
from .events.robot_events import (
    RobotDiscoveredEvent,
    RobotProvisionedEvent,
    RobotActivatedEvent,
    RobotFailedEvent,
    create_event,
    EVENT_CLASSES
)
from .models.robot_state import Robot, RobotState, RobotType, RobotStateMachine
from .cache_manager import CacheManager


# Configure logging
logger = logging.getLogger(__name__)


class PostgresEventStore(EventStore):
    """PostgreSQL implementation of event store."""
    
    def __init__(self, pool: Pool):
        self.pool = pool
    
    @backoff.on_exception(
        backoff.expo,
        asyncpg.PostgresConnectionError,
        max_tries=3,
        max_time=10
    )
    async def append(self, event: Event) -> None:
        """Append an event to the store with retry logic."""
        query = """
            INSERT INTO events (
                event_id, event_type, aggregate_id, aggregate_type,
                event_data, metadata, created_at, created_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                event.event_id,
                event.event_type.value,
                event.aggregate_id,
                event.aggregate_type,
                json.dumps(event.to_dict()),
                json.dumps(event.metadata),
                event.created_at,
                event.created_by
            )
    
    async def get_events(self, aggregate_id: UUID, 
                        from_version: Optional[int] = None) -> List[Event]:
        """Get events for an aggregate."""
        query = """
            SELECT event_type, event_data, created_at
            FROM events
            WHERE aggregate_id = $1
            ORDER BY created_at ASC
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, aggregate_id)
        
        events = []
        for row in rows:
            event_type = EventType(row['event_type'])
            event_class = EVENT_CLASSES.get(event_type)
            if event_class:
                event_data = json.loads(row['event_data'])
                event = event_class.from_dict(event_data)
                events.append(event)
        
        return events
    
    async def get_all_events(self, event_type: Optional[EventType] = None,
                            from_timestamp: Optional[datetime] = None) -> List[Event]:
        """Get all events, optionally filtered."""
        query = "SELECT event_type, event_data FROM events WHERE 1=1"
        params = []
        
        if event_type:
            query += " AND event_type = $1"
            params.append(event_type.value)
        
        if from_timestamp:
            param_num = len(params) + 1
            query += f" AND created_at >= ${param_num}"
            params.append(from_timestamp)
        
        query += " ORDER BY created_at ASC"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        
        events = []
        for row in rows:
            event_type = EventType(row['event_type'])
            event_class = EVENT_CLASSES.get(event_type)
            if event_class:
                event_data = json.loads(row['event_data'])
                event = event_class.from_dict(event_data)
                events.append(event)
        
        return events


class RobotRepository:
    """Repository for robot read model (CQRS query side)."""
    
    def __init__(self, pool: Pool, cache: Optional[CacheManager] = None):
        self.pool = pool
        self.cache = cache
    
    async def save(self, robot: Robot) -> None:
        """Save robot state to read model."""
        query = """
            INSERT INTO robot_states (
                robot_id, ip_address, hostname, robot_type, state,
                model, firmware_version, deployment_version,
                last_heartbeat, last_state_change, failure_count,
                config, capabilities, metadata,
                discovered_at, provisioned_at, activated_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
            ON CONFLICT (robot_id) DO UPDATE SET
                state = EXCLUDED.state,
                last_heartbeat = EXCLUDED.last_heartbeat,
                last_state_change = EXCLUDED.last_state_change,
                failure_count = EXCLUDED.failure_count,
                config = EXCLUDED.config,
                capabilities = EXCLUDED.capabilities,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
        """
        
        robot_dict = robot.to_dict()
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                robot.robot_id,
                robot.ip_address,
                robot.hostname,
                robot.robot_type.value,
                robot.state.value,
                robot.model,
                robot.firmware_version,
                robot.deployment_version,
                robot.last_heartbeat,
                robot.last_state_change,
                robot.failure_count,
                json.dumps(robot.config),
                json.dumps(robot.capabilities),
                json.dumps(robot.metadata),
                robot.discovered_at,
                robot.provisioned_at,
                robot.activated_at,
                robot.updated_at
            )
        
        # Update cache
        if self.cache:
            await self.cache.async_set_robot(robot)
    
    async def get_by_id(self, robot_id: UUID) -> Optional[Robot]:
        """Get robot by ID."""
        # Check cache first
        if self.cache:
            cached = await self.cache.async_get_robot(robot_id)
            if cached:
                return self._dict_to_robot(cached)
        
        query = """
            SELECT * FROM robot_states WHERE robot_id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, robot_id)
        
        if row:
            robot = self._row_to_robot(row)
            
            # Update cache
            if self.cache:
                await self.cache.async_set_robot(robot)
            
            return robot
        
        return None
    
    async def get_by_ip(self, ip_address: str) -> Optional[Robot]:
        """Get robot by IP address."""
        # Check cache first
        if self.cache:
            cached = await self.cache.async_get_robot_by_ip(ip_address)
            if cached:
                return self._dict_to_robot(cached)
        
        query = """
            SELECT * FROM robot_states WHERE ip_address = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, ip_address)
        
        if row:
            robot = self._row_to_robot(row)
            
            # Update cache
            if self.cache:
                await self.cache.async_set_robot(robot)
            
            return robot
        
        return None
    
    async def get_by_state(self, state: RobotState) -> List[Robot]:
        """Get robots by state."""
        query = """
            SELECT * FROM robot_states WHERE state = $1
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, state.value)
        
        return [self._row_to_robot(row) for row in rows]
    
    async def get_all(self) -> List[Robot]:
        """Get all robots."""
        query = "SELECT * FROM robot_states"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)
        
        return [self._row_to_robot(row) for row in rows]
    
    def _row_to_robot(self, row: asyncpg.Record) -> Robot:
        """Convert database row to Robot object."""
        return Robot(
            robot_id=row['robot_id'],
            ip_address=row['ip_address'],
            hostname=row['hostname'],
            robot_type=RobotType(row['robot_type']),
            state=RobotState(row['state']),
            model=row['model'],
            firmware_version=row['firmware_version'],
            deployment_version=row['deployment_version'],
            last_heartbeat=row['last_heartbeat'],
            last_state_change=row['last_state_change'],
            failure_count=row['failure_count'],
            consecutive_failures=row.get('consecutive_failures', 0),
            config=json.loads(row['config']) if row['config'] else {},
            capabilities=json.loads(row['capabilities']) if row['capabilities'] else {},
            metadata=json.loads(row['metadata']) if row['metadata'] else {},
            discovered_at=row['discovered_at'],
            provisioned_at=row['provisioned_at'],
            activated_at=row['activated_at'],
            updated_at=row['updated_at']
        )
    
    def _dict_to_robot(self, data: Dict[str, Any]) -> Robot:
        """Convert dictionary to Robot object."""
        return Robot(
            robot_id=UUID(data['robot_id']),
            ip_address=data['ip_address'],
            hostname=data.get('hostname'),
            robot_type=RobotType(data.get('robot_type', 'unknown')),
            state=RobotState(data.get('state', 'discovered')),
            model=data.get('model'),
            firmware_version=data.get('firmware_version'),
            deployment_version=data.get('deployment_version'),
            last_heartbeat=datetime.fromisoformat(data['last_heartbeat']) if data.get('last_heartbeat') else None,
            last_state_change=datetime.fromisoformat(data['last_state_change']) if data.get('last_state_change') else datetime.utcnow(),
            failure_count=data.get('failure_count', 0),
            consecutive_failures=data.get('consecutive_failures', 0),
            config=data.get('config', {}),
            capabilities=data.get('capabilities', {}),
            metadata=data.get('metadata', {}),
            discovered_at=datetime.fromisoformat(data['discovered_at']) if data.get('discovered_at') else datetime.utcnow(),
            provisioned_at=datetime.fromisoformat(data['provisioned_at']) if data.get('provisioned_at') else None,
            activated_at=datetime.fromisoformat(data['activated_at']) if data.get('activated_at') else None,
            updated_at=datetime.fromisoformat(data['updated_at']) if data.get('updated_at') else datetime.utcnow()
        )


class CircuitBreakerRepository:
    """Repository for circuit breaker state."""
    
    def __init__(self, pool: Pool):
        self.pool = pool
    
    async def get_state(self, robot_id: UUID) -> Optional[Dict[str, Any]]:
        """Get circuit breaker state for robot."""
        query = """
            SELECT * FROM circuit_breakers WHERE robot_id = $1
        """
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, robot_id)
        
        if row:
            return dict(row)
        return None
    
    async def update_state(self, robot_id: UUID, state: str, 
                          failure_count: int = 0,
                          next_retry_at: Optional[datetime] = None) -> None:
        """Update circuit breaker state."""
        query = """
            INSERT INTO circuit_breakers (
                robot_id, state, failure_count, last_failure_at,
                next_retry_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (robot_id) DO UPDATE SET
                state = EXCLUDED.state,
                failure_count = EXCLUDED.failure_count,
                last_failure_at = EXCLUDED.last_failure_at,
                next_retry_at = EXCLUDED.next_retry_at,
                updated_at = EXCLUDED.updated_at
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                robot_id,
                state,
                failure_count,
                datetime.utcnow() if failure_count > 0 else None,
                next_retry_at,
                datetime.utcnow()
            )
    
    async def record_success(self, robot_id: UUID) -> None:
        """Record successful operation."""
        query = """
            UPDATE circuit_breakers 
            SET consecutive_successes = consecutive_successes + 1,
                last_success_at = $2,
                updated_at = $2
            WHERE robot_id = $1
        """
        
        async with self.pool.acquire() as conn:
            await conn.execute(query, robot_id, datetime.utcnow())


class StateManager:
    """
    Main state manager implementing CQRS pattern with event sourcing.
    Coordinates between event store, read model, cache, and state machine.
    """
    
    def __init__(self,
                 db_config: Dict[str, Any],
                 cache_config: Optional[Dict[str, Any]] = None,
                 pool_size: int = 20,
                 max_queries: int = 50,
                 command_timeout: float = 10.0):
        """
        Initialize state manager with database and cache configuration.
        
        Args:
            db_config: PostgreSQL connection config
            cache_config: Redis connection config (optional)
            pool_size: Connection pool size
            max_queries: Max queries per connection
            command_timeout: Timeout for commands
        """
        self.db_config = db_config
        self.cache_config = cache_config
        self.pool_size = pool_size
        self.max_queries = max_queries
        self.command_timeout = command_timeout
        
        # Components (initialized in start())
        self.pool: Optional[Pool] = None
        self.event_store: Optional[PostgresEventStore] = None
        self.event_bus: Optional[EventBus] = None
        self.robot_repo: Optional[RobotRepository] = None
        self.circuit_repo: Optional[CircuitBreakerRepository] = None
        self.cache: Optional[CacheManager] = None
        self.state_machine: Optional[RobotStateMachine] = None
        
        # Metrics
        self.metrics = {
            'commands_processed': 0,
            'queries_processed': 0,
            'events_stored': 0,
            'errors': 0
        }
    
    async def start(self) -> None:
        """Start the state manager and initialize all components."""
        # Create database connection pool with retry logic
        self.pool = await self._create_pool_with_retry()
        
        # Initialize components
        self.event_store = PostgresEventStore(self.pool)
        self.event_bus = EventBus()
        self.robot_repo = RobotRepository(self.pool, self.cache)
        self.circuit_repo = CircuitBreakerRepository(self.pool)
        self.state_machine = RobotStateMachine()
        
        # Initialize cache if configured
        if self.cache_config:
            self.cache = CacheManager(**self.cache_config)
            await self.cache.initialize_async()
        
        # Load existing robots into state machine
        await self._load_robots()
        
        logger.info("State manager started successfully")
    
    async def stop(self) -> None:
        """Stop the state manager and clean up resources."""
        if self.pool:
            await self.pool.close()
        
        if self.cache:
            self.cache.close()
        
        logger.info("State manager stopped")
    
    @backoff.on_exception(
        backoff.expo,
        asyncpg.PostgresConnectionError,
        max_tries=5,
        max_time=30
    )
    async def _create_pool_with_retry(self) -> Pool:
        """Create database connection pool with retry logic."""
        return await asyncpg.create_pool(
            **self.db_config,
            min_size=10,
            max_size=self.pool_size,
            max_queries=self.max_queries,
            command_timeout=self.command_timeout
        )
    
    async def _load_robots(self) -> None:
        """Load existing robots from database into state machine."""
        robots = await self.robot_repo.get_all()
        for robot in robots:
            self.state_machine.add_robot(robot)
        
        logger.info(f"Loaded {len(robots)} robots into state machine")
    
    # Command handlers (write side)
    
    async def handle_robot_discovered(self, 
                                     ip_address: str,
                                     hostname: Optional[str] = None,
                                     robot_type: str = "unknown",
                                     **kwargs) -> UUID:
        """Handle robot discovery command."""
        try:
            # Check if robot already exists
            existing = await self.robot_repo.get_by_ip(ip_address)
            if existing:
                logger.warning(f"Robot already exists at {ip_address}")
                return existing.robot_id
            
            # Create discovery event
            robot_id = uuid4()
            event = RobotDiscoveredEvent(
                aggregate_id=robot_id,
                ip_address=ip_address,
                hostname=hostname,
                robot_type=robot_type,
                **kwargs
            )
            
            # Store event
            await self.event_store.append(event)
            
            # Process event in state machine
            self.state_machine.process_event(event)
            
            # Get updated robot state
            robot = self.state_machine.get_robot(robot_id)
            if robot:
                # Save to read model
                await self.robot_repo.save(robot)
                
                # Initialize circuit breaker
                await self.circuit_repo.update_state(robot_id, 'closed')
            
            # Publish event
            await self.event_bus.publish(event)
            
            self.metrics['commands_processed'] += 1
            self.metrics['events_stored'] += 1
            
            logger.info(f"Robot discovered: {robot_id} at {ip_address}")
            return robot_id
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error handling robot discovery: {e}")
            raise
    
    async def handle_robot_provisioned(self,
                                      robot_id: UUID,
                                      firmware_version: Optional[str] = None,
                                      deployment_version: Optional[str] = None,
                                      **kwargs) -> bool:
        """Handle robot provisioning command."""
        try:
            # Get robot
            robot = self.state_machine.get_robot(robot_id)
            if not robot:
                logger.error(f"Robot {robot_id} not found")
                return False
            
            # Create provisioned event
            event = RobotProvisionedEvent(
                aggregate_id=robot_id,
                firmware_version=firmware_version,
                deployment_version=deployment_version,
                **kwargs
            )
            
            # Apply event
            if not robot.apply_event(event):
                logger.warning(f"Cannot provision robot {robot_id} in state {robot.state}")
                return False
            
            # Store event
            await self.event_store.append(event)
            
            # Save to read model
            await self.robot_repo.save(robot)
            
            # Publish event
            await self.event_bus.publish(event)
            
            self.metrics['commands_processed'] += 1
            self.metrics['events_stored'] += 1
            
            logger.info(f"Robot provisioned: {robot_id}")
            return True
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error handling robot provisioning: {e}")
            raise
    
    async def handle_robot_failed(self,
                                 robot_id: UUID,
                                 error_message: str,
                                 failure_type: str = "unknown") -> bool:
        """Handle robot failure command."""
        try:
            # Get robot
            robot = self.state_machine.get_robot(robot_id)
            if not robot:
                logger.error(f"Robot {robot_id} not found")
                return False
            
            # Create failed event
            event = RobotFailedEvent(
                aggregate_id=robot_id,
                error_message=error_message,
                failure_type=failure_type,
                retry_count=robot.consecutive_failures
            )
            
            # Apply event
            robot.apply_event(event)
            
            # Update circuit breaker
            circuit_state = await self.circuit_repo.get_state(robot_id)
            if circuit_state:
                failure_count = circuit_state['failure_count'] + 1
                
                # Determine circuit breaker state
                if failure_count >= 5:
                    # Open circuit
                    next_retry = datetime.utcnow() + timedelta(minutes=5)
                    await self.circuit_repo.update_state(
                        robot_id, 'open', failure_count, next_retry
                    )
                elif failure_count >= 3:
                    # Half-open
                    next_retry = datetime.utcnow() + timedelta(minutes=1)
                    await self.circuit_repo.update_state(
                        robot_id, 'half_open', failure_count, next_retry
                    )
                else:
                    # Still closed
                    await self.circuit_repo.update_state(
                        robot_id, 'closed', failure_count
                    )
            
            # Store event
            await self.event_store.append(event)
            
            # Save to read model
            await self.robot_repo.save(robot)
            
            # Publish event
            await self.event_bus.publish(event)
            
            self.metrics['commands_processed'] += 1
            self.metrics['events_stored'] += 1
            
            logger.warning(f"Robot failed: {robot_id} - {error_message}")
            return True
            
        except Exception as e:
            self.metrics['errors'] += 1
            logger.error(f"Error handling robot failure: {e}")
            raise
    
    # Query handlers (read side)
    
    async def get_robot(self, robot_id: UUID) -> Optional[Dict[str, Any]]:
        """Get robot by ID."""
        self.metrics['queries_processed'] += 1
        
        robot = await self.robot_repo.get_by_id(robot_id)
        return robot.to_dict() if robot else None
    
    async def get_robot_by_ip(self, ip_address: str) -> Optional[Dict[str, Any]]:
        """Get robot by IP address."""
        self.metrics['queries_processed'] += 1
        
        robot = await self.robot_repo.get_by_ip(ip_address)
        return robot.to_dict() if robot else None
    
    async def get_robots_by_state(self, state: RobotState) -> List[Dict[str, Any]]:
        """Get all robots in a specific state."""
        self.metrics['queries_processed'] += 1
        
        robots = await self.robot_repo.get_by_state(state)
        return [robot.to_dict() for robot in robots]
    
    async def get_healthy_robots(self) -> List[Dict[str, Any]]:
        """Get all healthy robots."""
        self.metrics['queries_processed'] += 1
        
        robots = self.state_machine.get_healthy_robots()
        return [robot.to_dict() for robot in robots]
    
    async def get_deployable_robots(self) -> List[Dict[str, Any]]:
        """Get robots that can receive deployments."""
        self.metrics['queries_processed'] += 1
        
        robots = self.state_machine.get_deployable_robots()
        return [robot.to_dict() for robot in robots]
    
    async def get_circuit_breaker_state(self, robot_id: UUID) -> Optional[Dict[str, Any]]:
        """Get circuit breaker state for robot."""
        self.metrics['queries_processed'] += 1
        
        return await self.circuit_repo.get_state(robot_id)
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get state manager metrics."""
        cache_stats = self.cache.get_cache_stats() if self.cache else {}
        
        return {
            'state_manager': self.metrics,
            'cache': cache_stats,
            'robots': {
                'total': len(self.state_machine.robots),
                'by_state': {
                    state.value: len(self.state_machine.get_robots_by_state(state))
                    for state in RobotState
                }
            }
        }
    
    # Utility methods
    
    async def rebuild_from_events(self, robot_id: UUID) -> Optional[Robot]:
        """Rebuild robot state from events."""
        events = await self.event_store.get_events(robot_id)
        if events:
            robot = Robot.from_events(events)
            await self.robot_repo.save(robot)
            return robot
        return None
    
    @asynccontextmanager
    async def transaction(self):
        """Context manager for database transactions."""
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                yield conn