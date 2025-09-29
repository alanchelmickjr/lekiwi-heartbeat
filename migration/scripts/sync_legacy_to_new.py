#!/usr/bin/env python3
"""
Data Synchronization Script
Migrates robot data from legacy system to new PostgreSQL/Redis architecture
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import aiohttp
import asyncpg
import aioredis
import yaml
from dataclasses import dataclass, asdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/migration/data_sync.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class Robot:
    """Robot data model"""
    id: str
    name: str
    type: str  # 'lekiwi' or 'xle'
    ip_address: str
    mac_address: Optional[str]
    status: str  # 'online', 'offline', 'deploying', 'error'
    version: Optional[str]
    last_seen: datetime
    teleoperation_active: bool = False
    ssh_port: int = 22
    metadata: Dict = None

    def to_dict(self):
        data = asdict(self)
        data['last_seen'] = self.last_seen.isoformat()
        return data

class DataSynchronizer:
    """Handles data migration from legacy to new system"""
    
    def __init__(self, config_path: str = '/app/config/migration_config.yaml'):
        self.config = self._load_config(config_path)
        self.legacy_api = self.config['migration']['legacy_system']['endpoint']
        self.new_api = self.config['migration']['new_system']['endpoint']
        self.postgres_conn = None
        self.redis_pool = None
        self.session = None
        
        # Tracking
        self.sync_stats = {
            'robots_synced': 0,
            'robots_failed': 0,
            'deployments_synced': 0,
            'teleoperation_synced': 0,
            'errors': []
        }
    
    def _load_config(self, path: str) -> dict:
        """Load migration configuration"""
        try:
            with open(path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            sys.exit(1)
    
    async def connect(self):
        """Establish database connections"""
        try:
            # PostgreSQL connection
            db_config = self.config['migration']['database']['postgres']
            self.postgres_conn = await asyncpg.connect(
                host=db_config['host'],
                port=db_config['port'],
                database=db_config['database'],
                user=db_config['user'],
                password=db_config.get('password', 'secure_password')
            )
            logger.info("Connected to PostgreSQL")
            
            # Redis connection
            redis_config = self.config['migration']['database']['redis']
            self.redis_pool = await aioredis.create_redis_pool(
                f"redis://{redis_config['host']}:{redis_config['port']}/{redis_config['db']}",
                minsize=5,
                maxsize=10
            )
            logger.info("Connected to Redis")
            
            # HTTP session
            self.session = aiohttp.ClientSession()
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            raise
    
    async def disconnect(self):
        """Close all connections"""
        if self.postgres_conn:
            await self.postgres_conn.close()
        if self.redis_pool:
            self.redis_pool.close()
            await self.redis_pool.wait_closed()
        if self.session:
            await self.session.close()
    
    async def fetch_legacy_robots(self) -> List[Robot]:
        """Fetch all robots from legacy system"""
        robots = []
        try:
            async with self.session.get(f"{self.legacy_api}/robots") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    for robot_data in data:
                        # Transform legacy format to new format
                        robot = Robot(
                            id=robot_data.get('id', robot_data.get('ip_address')),
                            name=robot_data.get('name', f"robot-{robot_data.get('ip_address')}"),
                            type=self._detect_robot_type(robot_data),
                            ip_address=robot_data['ip_address'],
                            mac_address=robot_data.get('mac_address'),
                            status=self._map_status(robot_data.get('status', 'unknown')),
                            version=robot_data.get('version'),
                            last_seen=datetime.fromisoformat(robot_data.get('last_seen', datetime.now().isoformat())),
                            teleoperation_active=robot_data.get('teleoperation', False),
                            ssh_port=robot_data.get('ssh_port', 22),
                            metadata=robot_data.get('metadata', {})
                        )
                        robots.append(robot)
                        
            logger.info(f"Fetched {len(robots)} robots from legacy system")
            
        except Exception as e:
            logger.error(f"Failed to fetch legacy robots: {e}")
            self.sync_stats['errors'].append(str(e))
            
        return robots
    
    def _detect_robot_type(self, robot_data: dict) -> str:
        """Detect robot type from legacy data"""
        # Check various indicators
        if 'type' in robot_data:
            return robot_data['type'].lower()
        
        hostname = robot_data.get('hostname', '').lower()
        if 'xlerobot' in hostname or 'xle' in hostname:
            return 'xle'
        elif 'lekiwi' in hostname:
            return 'lekiwi'
        
        # Check by IP range if configured
        ip = robot_data.get('ip_address', '')
        if ip.startswith('192.168.50.'):  # XLE robots subnet
            return 'xle'
        elif ip.startswith('192.168.1.'):  # Lekiwi robots subnet
            return 'lekiwi'
        
        return 'unknown'
    
    def _map_status(self, legacy_status: str) -> str:
        """Map legacy status to new status values"""
        status_map = {
            'running': 'online',
            'stopped': 'offline',
            'updating': 'deploying',
            'failed': 'error',
            'unknown': 'offline'
        }
        return status_map.get(legacy_status.lower(), 'offline')
    
    async def sync_robot(self, robot: Robot) -> bool:
        """Sync a single robot to new system"""
        try:
            # Insert/update in PostgreSQL
            await self.postgres_conn.execute("""
                INSERT INTO robots (
                    id, name, type, ip_address, mac_address, 
                    status, version, last_seen, ssh_port, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    type = EXCLUDED.type,
                    ip_address = EXCLUDED.ip_address,
                    mac_address = EXCLUDED.mac_address,
                    status = EXCLUDED.status,
                    version = EXCLUDED.version,
                    last_seen = EXCLUDED.last_seen,
                    ssh_port = EXCLUDED.ssh_port,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
            """, robot.id, robot.name, robot.type, robot.ip_address,
                robot.mac_address, robot.status, robot.version,
                robot.last_seen, robot.ssh_port, 
                json.dumps(robot.metadata) if robot.metadata else '{}')
            
            # Cache in Redis with TTL
            cache_key = f"robot:{robot.id}"
            cache_data = json.dumps(robot.to_dict())
            ttl = self.config['migration']['database']['redis']['ttl']
            
            await self.redis_pool.setex(cache_key, ttl, cache_data)
            
            # Sync teleoperation status if active
            if robot.teleoperation_active:
                await self.sync_teleoperation_session(robot)
            
            logger.debug(f"Synced robot {robot.id} ({robot.name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync robot {robot.id}: {e}")
            self.sync_stats['errors'].append(f"Robot {robot.id}: {e}")
            return False
    
    async def sync_teleoperation_session(self, robot: Robot):
        """Sync active teleoperation session"""
        try:
            await self.postgres_conn.execute("""
                INSERT INTO teleoperation_sessions (
                    robot_id, started_at, is_active, 
                    operator_id, connection_quality
                ) VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (robot_id) WHERE is_active = true
                DO UPDATE SET
                    connection_quality = EXCLUDED.connection_quality,
                    last_activity = NOW()
            """, robot.id, datetime.now(), True, 
                'legacy_operator', 'good')
            
            self.sync_stats['teleoperation_synced'] += 1
            
        except Exception as e:
            logger.error(f"Failed to sync teleoperation for {robot.id}: {e}")
    
    async def sync_deployments(self):
        """Sync deployment history from legacy system"""
        try:
            async with self.session.get(f"{self.legacy_api}/deployments") as resp:
                if resp.status == 200:
                    deployments = await resp.json()
                    
                    for deployment in deployments:
                        await self.postgres_conn.execute("""
                            INSERT INTO robot_deployments (
                                robot_id, version, deployed_at, 
                                status, deployed_by, logs
                            ) VALUES ($1, $2, $3, $4, $5, $6)
                            ON CONFLICT DO NOTHING
                        """, deployment['robot_id'], deployment['version'],
                            datetime.fromisoformat(deployment['deployed_at']),
                            deployment['status'], deployment.get('deployed_by', 'system'),
                            deployment.get('logs', ''))
                        
                        self.sync_stats['deployments_synced'] += 1
                        
        except Exception as e:
            logger.error(f"Failed to sync deployments: {e}")
            self.sync_stats['errors'].append(f"Deployments: {e}")
    
    async def verify_sync(self) -> Dict:
        """Verify data consistency between systems"""
        verification = {
            'consistent': True,
            'issues': []
        }
        
        try:
            # Count robots in legacy
            async with self.session.get(f"{self.legacy_api}/robots/count") as resp:
                legacy_count = (await resp.json())['count'] if resp.status == 200 else 0
            
            # Count robots in new system
            new_count = await self.postgres_conn.fetchval(
                "SELECT COUNT(*) FROM robots"
            )
            
            if legacy_count != new_count:
                verification['consistent'] = False
                verification['issues'].append(
                    f"Robot count mismatch: Legacy={legacy_count}, New={new_count}"
                )
            
            # Check for missing robots
            legacy_robots = await self.fetch_legacy_robots()
            legacy_ids = {r.id for r in legacy_robots}
            
            new_ids = await self.postgres_conn.fetch(
                "SELECT id FROM robots"
            )
            new_ids = {r['id'] for r in new_ids}
            
            missing_in_new = legacy_ids - new_ids
            if missing_in_new:
                verification['consistent'] = False
                verification['issues'].append(
                    f"Missing robots in new system: {missing_in_new}"
                )
            
            extra_in_new = new_ids - legacy_ids
            if extra_in_new:
                verification['issues'].append(
                    f"Extra robots in new system (may be newly discovered): {extra_in_new}"
                )
            
        except Exception as e:
            verification['consistent'] = False
            verification['issues'].append(f"Verification error: {e}")
        
        return verification
    
    async def run_full_sync(self, batch_size: int = 50):
        """Run complete synchronization"""
        logger.info("Starting full data synchronization...")
        start_time = datetime.now()
        
        try:
            # Connect to databases
            await self.connect()
            
            # Fetch and sync robots
            robots = await self.fetch_legacy_robots()
            
            # Process in batches
            for i in range(0, len(robots), batch_size):
                batch = robots[i:i+batch_size]
                
                tasks = [self.sync_robot(robot) for robot in batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Track results
                for result in results:
                    if isinstance(result, Exception):
                        self.sync_stats['robots_failed'] += 1
                    elif result:
                        self.sync_stats['robots_synced'] += 1
                    else:
                        self.sync_stats['robots_failed'] += 1
                
                # Progress update
                progress = (i + len(batch)) / len(robots) * 100
                logger.info(f"Sync progress: {progress:.1f}% ({i+len(batch)}/{len(robots)} robots)")
                
                # Small delay between batches
                await asyncio.sleep(0.5)
            
            # Sync deployment history
            await self.sync_deployments()
            
            # Verify synchronization
            verification = await self.verify_sync()
            
            # Calculate duration
            duration = (datetime.now() - start_time).total_seconds()
            
            # Final report
            logger.info("=" * 60)
            logger.info("DATA SYNCHRONIZATION COMPLETE")
            logger.info("=" * 60)
            logger.info(f"Duration: {duration:.2f} seconds")
            logger.info(f"Robots synced: {self.sync_stats['robots_synced']}")
            logger.info(f"Robots failed: {self.sync_stats['robots_failed']}")
            logger.info(f"Deployments synced: {self.sync_stats['deployments_synced']}")
            logger.info(f"Teleoperation sessions: {self.sync_stats['teleoperation_synced']}")
            logger.info(f"Data consistent: {verification['consistent']}")
            
            if verification['issues']:
                logger.warning("Verification issues:")
                for issue in verification['issues']:
                    logger.warning(f"  - {issue}")
            
            if self.sync_stats['errors']:
                logger.error("Errors encountered:")
                for error in self.sync_stats['errors'][:10]:  # Show first 10 errors
                    logger.error(f"  - {error}")
            
            # Write stats to file
            with open('/var/log/migration/sync_stats.json', 'w') as f:
                json.dump({
                    'timestamp': datetime.now().isoformat(),
                    'duration_seconds': duration,
                    'stats': self.sync_stats,
                    'verification': verification
                }, f, indent=2)
            
            return verification['consistent']
            
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return False
            
        finally:
            await self.disconnect()

async def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync data from legacy to new system')
    parser.add_argument('--config', default='/app/config/migration_config.yaml',
                      help='Path to migration config file')
    parser.add_argument('--batch-size', type=int, default=50,
                      help='Batch size for processing')
    parser.add_argument('--continuous', action='store_true',
                      help='Run in continuous sync mode')
    parser.add_argument('--interval', type=int, default=60,
                      help='Sync interval in seconds (for continuous mode)')
    
    args = parser.parse_args()
    
    synchronizer = DataSynchronizer(args.config)
    
    if args.continuous:
        logger.info(f"Starting continuous sync with {args.interval}s interval")
        while True:
            try:
                success = await synchronizer.run_full_sync(args.batch_size)
                if not success:
                    logger.warning("Sync completed with issues")
                
                logger.info(f"Sleeping for {args.interval} seconds...")
                await asyncio.sleep(args.interval)
                
            except KeyboardInterrupt:
                logger.info("Continuous sync stopped by user")
                break
            except Exception as e:
                logger.error(f"Sync error: {e}")
                await asyncio.sleep(args.interval)
    else:
        # Run once
        success = await synchronizer.run_full_sync(args.batch_size)
        sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())