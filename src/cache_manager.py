"""Redis cache manager for robot state and static data."""

import json
import pickle
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Union
from uuid import UUID
import hashlib

import redis
from redis import ConnectionPool, Redis
from redis.exceptions import RedisError
import redis.asyncio as aioredis

from .models.robot_state import Robot, RobotState, RobotType


class CacheManager:
    """Redis cache manager with connection pooling and retry logic."""
    
    def __init__(self, 
                 host: str = 'localhost',
                 port: int = 6379,
                 db: int = 0,
                 password: Optional[str] = None,
                 max_connections: int = 50,
                 socket_timeout: int = 5,
                 socket_connect_timeout: int = 5,
                 retry_on_timeout: bool = True,
                 retry_on_error: List[Exception] = None):
        """Initialize Redis cache manager with connection pooling."""
        
        self.config = {
            'host': host,
            'port': port,
            'db': db,
            'password': password,
            'socket_timeout': socket_timeout,
            'socket_connect_timeout': socket_connect_timeout,
            'retry_on_timeout': retry_on_timeout,
            'retry_on_error': retry_on_error or [RedisError],
            'max_connections': max_connections,
            'decode_responses': False  # We'll handle encoding/decoding
        }
        
        # Create connection pool for synchronous operations
        self.pool = ConnectionPool(**self.config)
        self.redis_client = Redis(connection_pool=self.pool)
        
        # Create async connection pool
        self.async_pool = aioredis.ConnectionPool(**self.config)
        self.async_client = None
        
        # Cache key prefixes
        self.KEY_PREFIX = "lekiwi:"
        self.ROBOT_KEY = f"{self.KEY_PREFIX}robot:"
        self.ROBOT_SET = f"{self.KEY_PREFIX}robots:all"
        self.ROBOT_BY_STATE = f"{self.KEY_PREFIX}robots:state:"
        self.ROBOT_BY_TYPE = f"{self.KEY_PREFIX}robots:type:"
        self.ROBOT_BY_IP = f"{self.KEY_PREFIX}robots:ip:"
        self.DISCOVERY_SESSION = f"{self.KEY_PREFIX}discovery:"
        self.METRICS_KEY = f"{self.KEY_PREFIX}metrics:"
        self.LOCK_KEY = f"{self.KEY_PREFIX}lock:"
        
        # Default TTLs
        self.DEFAULT_TTL = 300  # 5 minutes for dynamic data
        self.STATIC_TTL = 3600  # 1 hour for static data
        self.DISCOVERY_TTL = 60  # 1 minute for discovery results
        self.METRICS_TTL = 86400  # 24 hours for metrics
    
    async def initialize_async(self):
        """Initialize async Redis client."""
        if not self.async_client:
            self.async_client = aioredis.Redis(connection_pool=self.async_pool)
    
    def _get_robot_key(self, robot_id: Union[UUID, str]) -> str:
        """Get cache key for robot."""
        return f"{self.ROBOT_KEY}{str(robot_id)}"
    
    def _get_state_key(self, state: RobotState) -> str:
        """Get cache key for robots by state."""
        return f"{self.ROBOT_BY_STATE}{state.value}"
    
    def _get_type_key(self, robot_type: RobotType) -> str:
        """Get cache key for robots by type."""
        return f"{self.ROBOT_BY_TYPE}{robot_type.value}"
    
    def _get_ip_key(self, ip_address: str) -> str:
        """Get cache key for robot by IP."""
        return f"{self.ROBOT_BY_IP}{ip_address}"
    
    def _serialize(self, data: Any) -> bytes:
        """Serialize data for storage."""
        if isinstance(data, (dict, list)):
            # Use JSON for simple types
            return json.dumps(data, default=str).encode('utf-8')
        else:
            # Use pickle for complex objects
            return pickle.dumps(data)
    
    def _deserialize(self, data: bytes, use_json: bool = True) -> Any:
        """Deserialize data from storage."""
        if data is None:
            return None
        
        if use_json:
            try:
                return json.loads(data.decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Fall back to pickle
                return pickle.loads(data)
        else:
            return pickle.loads(data)
    
    # Synchronous methods
    
    def set_robot(self, robot: Robot, ttl: Optional[int] = None) -> bool:
        """Cache robot state."""
        try:
            key = self._get_robot_key(robot.robot_id)
            data = self._serialize(robot.to_dict())
            ttl = ttl or self.DEFAULT_TTL
            
            # Set robot data
            result = self.redis_client.setex(key, ttl, data)
            
            # Add to robot set
            self.redis_client.sadd(self.ROBOT_SET, str(robot.robot_id))
            
            # Add to state index
            state_key = self._get_state_key(robot.state)
            self.redis_client.sadd(state_key, str(robot.robot_id))
            
            # Add to type index
            type_key = self._get_type_key(robot.robot_type)
            self.redis_client.sadd(type_key, str(robot.robot_id))
            
            # Add IP mapping
            ip_key = self._get_ip_key(robot.ip_address)
            self.redis_client.setex(ip_key, ttl, str(robot.robot_id))
            
            return bool(result)
        except RedisError as e:
            print(f"Redis error setting robot {robot.robot_id}: {e}")
            return False
    
    def get_robot(self, robot_id: Union[UUID, str]) -> Optional[Dict[str, Any]]:
        """Get robot from cache."""
        try:
            key = self._get_robot_key(robot_id)
            data = self.redis_client.get(key)
            return self._deserialize(data) if data else None
        except RedisError as e:
            print(f"Redis error getting robot {robot_id}: {e}")
            return None
    
    def get_robot_by_ip(self, ip_address: str) -> Optional[Dict[str, Any]]:
        """Get robot by IP address."""
        try:
            ip_key = self._get_ip_key(ip_address)
            robot_id = self.redis_client.get(ip_key)
            if robot_id:
                return self.get_robot(robot_id.decode('utf-8'))
            return None
        except RedisError as e:
            print(f"Redis error getting robot by IP {ip_address}: {e}")
            return None
    
    def get_robots_by_state(self, state: RobotState) -> List[Dict[str, Any]]:
        """Get all robots in a specific state."""
        try:
            state_key = self._get_state_key(state)
            robot_ids = self.redis_client.smembers(state_key)
            
            robots = []
            for robot_id in robot_ids:
                robot = self.get_robot(robot_id.decode('utf-8'))
                if robot:
                    robots.append(robot)
            
            return robots
        except RedisError as e:
            print(f"Redis error getting robots by state {state}: {e}")
            return []
    
    def get_robots_by_type(self, robot_type: RobotType) -> List[Dict[str, Any]]:
        """Get all robots of a specific type."""
        try:
            type_key = self._get_type_key(robot_type)
            robot_ids = self.redis_client.smembers(type_key)
            
            robots = []
            for robot_id in robot_ids:
                robot = self.get_robot(robot_id.decode('utf-8'))
                if robot:
                    robots.append(robot)
            
            return robots
        except RedisError as e:
            print(f"Redis error getting robots by type {robot_type}: {e}")
            return []
    
    def get_all_robots(self) -> List[Dict[str, Any]]:
        """Get all cached robots."""
        try:
            robot_ids = self.redis_client.smembers(self.ROBOT_SET)
            
            robots = []
            for robot_id in robot_ids:
                robot = self.get_robot(robot_id.decode('utf-8'))
                if robot:
                    robots.append(robot)
            
            return robots
        except RedisError as e:
            print(f"Redis error getting all robots: {e}")
            return []
    
    def delete_robot(self, robot_id: Union[UUID, str]) -> bool:
        """Remove robot from cache."""
        try:
            # Get robot data first to clean up indexes
            robot_data = self.get_robot(robot_id)
            
            # Delete robot data
            key = self._get_robot_key(robot_id)
            self.redis_client.delete(key)
            
            # Remove from robot set
            self.redis_client.srem(self.ROBOT_SET, str(robot_id))
            
            # Clean up indexes if we have robot data
            if robot_data:
                # Remove from state index
                if 'state' in robot_data:
                    state = RobotState(robot_data['state'])
                    state_key = self._get_state_key(state)
                    self.redis_client.srem(state_key, str(robot_id))
                
                # Remove from type index
                if 'robot_type' in robot_data:
                    robot_type = RobotType(robot_data['robot_type'])
                    type_key = self._get_type_key(robot_type)
                    self.redis_client.srem(type_key, str(robot_id))
                
                # Remove IP mapping
                if 'ip_address' in robot_data:
                    ip_key = self._get_ip_key(robot_data['ip_address'])
                    self.redis_client.delete(ip_key)
            
            return True
        except RedisError as e:
            print(f"Redis error deleting robot {robot_id}: {e}")
            return False
    
    def cache_discovery_session(self, session_id: str, data: Dict[str, Any], 
                               ttl: Optional[int] = None) -> bool:
        """Cache discovery session results."""
        try:
            key = f"{self.DISCOVERY_SESSION}{session_id}"
            ttl = ttl or self.DISCOVERY_TTL
            return bool(self.redis_client.setex(key, ttl, self._serialize(data)))
        except RedisError as e:
            print(f"Redis error caching discovery session {session_id}: {e}")
            return False
    
    def get_discovery_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get cached discovery session."""
        try:
            key = f"{self.DISCOVERY_SESSION}{session_id}"
            data = self.redis_client.get(key)
            return self._deserialize(data) if data else None
        except RedisError as e:
            print(f"Redis error getting discovery session {session_id}: {e}")
            return None
    
    def record_metric(self, metric_name: str, value: float, 
                     tags: Optional[Dict[str, str]] = None) -> bool:
        """Record a metric with timestamp."""
        try:
            timestamp = datetime.utcnow().isoformat()
            metric_data = {
                'name': metric_name,
                'value': value,
                'timestamp': timestamp,
                'tags': tags or {}
            }
            
            # Create metric key with hash of tags for uniqueness
            tag_hash = hashlib.md5(json.dumps(tags or {}, sort_keys=True).encode()).hexdigest()[:8]
            key = f"{self.METRICS_KEY}{metric_name}:{tag_hash}:{timestamp}"
            
            # Store metric with TTL
            result = self.redis_client.setex(key, self.METRICS_TTL, self._serialize(metric_data))
            
            # Also add to sorted set for time-based queries
            score = datetime.utcnow().timestamp()
            self.redis_client.zadd(f"{self.METRICS_KEY}timeline", {key: score})
            
            return bool(result)
        except RedisError as e:
            print(f"Redis error recording metric {metric_name}: {e}")
            return False
    
    def get_recent_metrics(self, metric_name: Optional[str] = None, 
                          minutes: int = 60) -> List[Dict[str, Any]]:
        """Get recent metrics within specified time window."""
        try:
            cutoff = (datetime.utcnow() - timedelta(minutes=minutes)).timestamp()
            
            # Get metric keys from timeline
            keys = self.redis_client.zrangebyscore(
                f"{self.METRICS_KEY}timeline", 
                cutoff, 
                '+inf'
            )
            
            metrics = []
            for key in keys:
                key_str = key.decode('utf-8')
                
                # Filter by metric name if specified
                if metric_name and not key_str.startswith(f"{self.METRICS_KEY}{metric_name}:"):
                    continue
                
                data = self.redis_client.get(key_str)
                if data:
                    metrics.append(self._deserialize(data))
            
            return sorted(metrics, key=lambda x: x['timestamp'], reverse=True)
        except RedisError as e:
            print(f"Redis error getting recent metrics: {e}")
            return []
    
    def acquire_lock(self, resource: str, ttl: int = 30) -> Optional[str]:
        """Acquire a distributed lock."""
        try:
            lock_key = f"{self.LOCK_KEY}{resource}"
            lock_id = str(UUID())
            
            # Set lock with NX (only if not exists) and EX (expiry)
            acquired = self.redis_client.set(lock_key, lock_id, nx=True, ex=ttl)
            
            return lock_id if acquired else None
        except RedisError as e:
            print(f"Redis error acquiring lock for {resource}: {e}")
            return None
    
    def release_lock(self, resource: str, lock_id: str) -> bool:
        """Release a distributed lock."""
        try:
            lock_key = f"{self.LOCK_KEY}{resource}"
            
            # Use Lua script to ensure atomic check and delete
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            
            result = self.redis_client.eval(lua_script, 1, lock_key, lock_id)
            return bool(result)
        except RedisError as e:
            print(f"Redis error releasing lock for {resource}: {e}")
            return False
    
    def clear_cache(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries matching pattern."""
        try:
            if pattern:
                keys = self.redis_client.keys(f"{self.KEY_PREFIX}{pattern}*")
            else:
                keys = self.redis_client.keys(f"{self.KEY_PREFIX}*")
            
            if keys:
                return self.redis_client.delete(*keys)
            return 0
        except RedisError as e:
            print(f"Redis error clearing cache: {e}")
            return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        try:
            info = self.redis_client.info()
            
            # Count entries by type
            robot_count = self.redis_client.scard(self.ROBOT_SET)
            
            # Count by state
            state_counts = {}
            for state in RobotState:
                state_key = self._get_state_key(state)
                state_counts[state.value] = self.redis_client.scard(state_key)
            
            # Count by type
            type_counts = {}
            for robot_type in RobotType:
                type_key = self._get_type_key(robot_type)
                type_counts[robot_type.value] = self.redis_client.scard(type_key)
            
            return {
                'connected': True,
                'used_memory': info.get('used_memory_human', 'N/A'),
                'connected_clients': info.get('connected_clients', 0),
                'total_commands_processed': info.get('total_commands_processed', 0),
                'robot_count': robot_count,
                'robots_by_state': state_counts,
                'robots_by_type': type_counts,
                'uptime_seconds': info.get('uptime_in_seconds', 0)
            }
        except RedisError as e:
            print(f"Redis error getting cache stats: {e}")
            return {'connected': False, 'error': str(e)}
    
    def close(self):
        """Close Redis connections."""
        try:
            self.redis_client.close()
            self.pool.disconnect()
            if self.async_client:
                self.async_client.close()
                self.async_pool.disconnect()
        except Exception as e:
            print(f"Error closing Redis connections: {e}")
    
    # Async methods
    
    async def async_set_robot(self, robot: Robot, ttl: Optional[int] = None) -> bool:
        """Async cache robot state."""
        await self.initialize_async()
        try:
            key = self._get_robot_key(robot.robot_id)
            data = self._serialize(robot.to_dict())
            ttl = ttl or self.DEFAULT_TTL
            
            # Use pipeline for atomic operations
            async with self.async_client.pipeline() as pipe:
                await pipe.setex(key, ttl, data)
                await pipe.sadd(self.ROBOT_SET, str(robot.robot_id))
                await pipe.sadd(self._get_state_key(robot.state), str(robot.robot_id))
                await pipe.sadd(self._get_type_key(robot.robot_type), str(robot.robot_id))
                await pipe.setex(self._get_ip_key(robot.ip_address), ttl, str(robot.robot_id))
                results = await pipe.execute()
            
            return all(results)
        except RedisError as e:
            print(f"Async Redis error setting robot {robot.robot_id}: {e}")
            return False
    
    async def async_get_robot(self, robot_id: Union[UUID, str]) -> Optional[Dict[str, Any]]:
        """Async get robot from cache."""
        await self.initialize_async()
        try:
            key = self._get_robot_key(robot_id)
            data = await self.async_client.get(key)
            return self._deserialize(data) if data else None
        except RedisError as e:
            print(f"Async Redis error getting robot {robot_id}: {e}")
            return None
    
    async def async_get_all_robots(self) -> List[Dict[str, Any]]:
        """Async get all cached robots."""
        await self.initialize_async()
        try:
            robot_ids = await self.async_client.smembers(self.ROBOT_SET)
            
            robots = []
            for robot_id in robot_ids:
                robot = await self.async_get_robot(robot_id.decode('utf-8'))
                if robot:
                    robots.append(robot)
            
            return robots
        except RedisError as e:
            print(f"Async Redis error getting all robots: {e}")
            return []