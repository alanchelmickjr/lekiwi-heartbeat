# Lekiwi Heartbeat System Migration Plan
## From Legacy Polling to Production Event-Driven Architecture

**Version**: 1.0.0  
**Date**: 2025-01-29  
**Target**: Zero-downtime migration with gradual rollout

---

## Executive Summary

This migration plan transitions the Lekiwi Heartbeat robot deployment system from its current broken state (serial polling, in-memory state, incorrect teleoperation status) to a production-grade event-driven architecture with persistent state management, real-time monitoring, and WebSocket-based communication.

### Key Objectives
- **Zero Downtime**: Maintain continuous service availability
- **Gradual Rollout**: 10% → 25% → 50% → 100% phased migration
- **Full Rollback**: Capability at any phase
- **Data Integrity**: Preserve all robot state during migration
- **Dual Robot Support**: Lekiwi and XLE robots

### Timeline
- **Phase 0**: Pre-migration Preparation (Week 1)
- **Phase 1**: Parallel Deployment (Week 2)
- **Phase 2**: 10% Canary (Week 3)
- **Phase 3**: 25% Rollout (Week 4)
- **Phase 4**: 50% Rollout (Week 5)
- **Phase 5**: 100% Migration (Week 6)
- **Phase 6**: Legacy Decommission (Week 7-8)

---

## Phase 0: Pre-Migration Preparation

### Infrastructure Setup

#### 1. Database Preparation
```bash
# PostgreSQL setup
sudo apt-get install postgresql-14 postgresql-contrib
sudo systemctl enable postgresql
sudo -u postgres psql -c "CREATE DATABASE lekiwi_heartbeat;"
sudo -u postgres psql -c "CREATE USER lekiwi_admin WITH ENCRYPTED PASSWORD 'secure_password';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE lekiwi_heartbeat TO lekiwi_admin;"

# Apply migration schema
psql -U lekiwi_admin -d lekiwi_heartbeat -f migrations/001_initial_schema.sql

# Redis setup
sudo apt-get install redis-server
sudo systemctl enable redis-server
sudo sed -i 's/# maxmemory <bytes>/maxmemory 2gb/' /etc/redis/redis.conf
sudo sed -i 's/# maxmemory-policy noeviction/maxmemory-policy allkeys-lru/' /etc/redis/redis.conf
sudo systemctl restart redis-server
```

#### 2. Environment Configuration
```yaml
# config/migration_config.yaml
migration:
  phase: 0
  legacy_system:
    enabled: true
    endpoint: "http://localhost:8000"
    health_check: "/health"
  
  new_system:
    enabled: false
    endpoint: "http://localhost:8001"
    health_check: "/api/v2/health"
    
  database:
    postgres:
      host: localhost
      port: 5432
      database: lekiwi_heartbeat
      user: lekiwi_admin
      pool_size: 20
    
    redis:
      host: localhost
      port: 6379
      db: 0
      ttl: 3600
  
  rollout:
    canary_percentage: 0
    feature_flags:
      event_driven_discovery: false
      persistent_state: false
      websocket_monitoring: false
      teleoperation_optimization: false
```

### Team Preparation

#### Roles & Responsibilities
| Role | Team Member | Responsibilities |
|------|-------------|-----------------|
| Migration Lead | TBD | Overall coordination, decision making |
| Infrastructure Engineer | TBD | Database, Redis, networking setup |
| Backend Engineer | TBD | Service deployment, data migration |
| DevOps Engineer | TBD | Monitoring, logging, rollback procedures |
| QA Engineer | TBD | Validation testing, performance testing |
| On-Call Support | TBD | 24/7 monitoring during migration |

### Pre-Migration Checklist

- [ ] **Infrastructure**
  - [ ] PostgreSQL installed and configured
  - [ ] Redis installed and configured
  - [ ] Network firewall rules updated
  - [ ] SSL certificates generated
  - [ ] Backup systems verified

- [ ] **Monitoring**
  - [ ] Prometheus metrics configured
  - [ ] Grafana dashboards created
  - [ ] Alert rules defined
  - [ ] Log aggregation setup (ELK/Loki)

- [ ] **Testing**
  - [ ] Load testing completed
  - [ ] Failover testing validated
  - [ ] Data migration scripts tested
  - [ ] Rollback procedures tested

- [ ] **Documentation**
  - [ ] Runbooks reviewed
  - [ ] Emergency contacts updated
  - [ ] Architecture diagrams current
  - [ ] Team trained on new system

---

## Phase 1: Parallel Deployment

### Objective
Deploy new system alongside legacy system without handling any traffic.

### Implementation Steps

1. **Deploy New Services**
```bash
# Deploy new event-driven discovery service
docker-compose -f docker-compose.new.yml up -d discovery-service

# Deploy state manager with PostgreSQL/Redis
docker-compose -f docker-compose.new.yml up -d state-manager

# Deploy WebSocket monitoring service
docker-compose -f docker-compose.new.yml up -d websocket-monitor

# Deploy teleoperation optimization service
docker-compose -f docker-compose.new.yml up -d teleoperation-service
```

2. **Configure Load Balancer**
```nginx
# /etc/nginx/sites-available/lekiwi-heartbeat
upstream legacy_backend {
    server localhost:8000 weight=100;  # 100% traffic to legacy
}

upstream new_backend {
    server localhost:8001 weight=0;    # 0% traffic to new (shadow mode)
}

server {
    listen 80;
    server_name heartbeat.lekiwi.com;
    
    location / {
        proxy_pass http://legacy_backend;
        
        # Shadow traffic to new system (async)
        mirror /shadow;
        mirror_request_body on;
    }
    
    location /shadow {
        internal;
        proxy_pass http://new_backend$request_uri;
        proxy_set_header X-Shadow-Request true;
    }
    
    location /api/v2/ {
        # Direct access to new API for testing
        proxy_pass http://new_backend;
    }
}
```

3. **Data Synchronization**
```python
# migration/sync_legacy_to_new.py
import asyncio
import aioredis
import asyncpg
from datetime import datetime

class DataSynchronizer:
    def __init__(self):
        self.legacy_api = "http://localhost:8000"
        self.postgres = None
        self.redis = None
        
    async def connect(self):
        self.postgres = await asyncpg.connect(
            'postgresql://lekiwi_admin:secure_password@localhost/lekiwi_heartbeat'
        )
        self.redis = await aioredis.create_redis_pool('redis://localhost')
    
    async def sync_robot_states(self):
        """Sync robot states from legacy to new system"""
        # Fetch from legacy
        legacy_robots = await self.fetch_legacy_robots()
        
        # Insert into PostgreSQL
        for robot in legacy_robots:
            await self.postgres.execute("""
                INSERT INTO robots (id, name, type, ip_address, status, last_seen)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE
                SET status = $4, last_seen = $6
            """, robot['id'], robot['name'], robot['type'], 
                robot['ip'], robot['status'], datetime.now())
            
            # Cache in Redis
            await self.redis.setex(
                f"robot:{robot['id']}", 
                3600, 
                json.dumps(robot)
            )
```

### Validation Criteria
- [ ] New services running without errors
- [ ] Shadow traffic being processed
- [ ] Metrics collection working
- [ ] No impact on legacy system performance
- [ ] Data sync maintaining consistency

---

## Phase 2: 10% Canary Deployment

### Objective
Route 10% of traffic to new system, monitor for issues.

### Implementation

1. **Update Load Balancer**
```bash
# migration/scripts/update_traffic_split.sh
#!/bin/bash
PERCENTAGE=$1
LEGACY_WEIGHT=$((100 - PERCENTAGE))
NEW_WEIGHT=$PERCENTAGE

cat > /etc/nginx/conf.d/upstream.conf <<EOF
upstream legacy_backend {
    server localhost:8000 weight=$LEGACY_WEIGHT;
}

upstream new_backend {
    server localhost:8001 weight=$NEW_WEIGHT;
}
EOF

nginx -t && nginx -s reload
echo "Traffic split updated: Legacy=$LEGACY_WEIGHT%, New=$NEW_WEIGHT%"
```

2. **Enable Feature Flags**
```python
# migration/feature_flags.py
import yaml

def update_feature_flags(phase):
    config = yaml.safe_load(open('config/migration_config.yaml'))
    
    if phase == 'canary_10':
        config['rollout']['canary_percentage'] = 10
        config['rollout']['feature_flags']['event_driven_discovery'] = True
        config['rollout']['feature_flags']['persistent_state'] = True
        
    with open('config/migration_config.yaml', 'w') as f:
        yaml.dump(config, f)
```

3. **Monitoring Dashboard**
```python
# migration/monitoring/canary_metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Metrics for canary analysis
request_count = Counter('migration_requests_total', 
                       'Total requests', ['system', 'endpoint'])
request_duration = Histogram('migration_request_duration_seconds',
                            'Request duration', ['system', 'endpoint'])
error_rate = Gauge('migration_error_rate', 
                  'Error rate percentage', ['system'])
robot_count = Gauge('migration_robot_count',
                   'Number of robots', ['system', 'type'])
```

### Success Criteria
- [ ] Error rate < 0.1% for new system
- [ ] P99 latency < 100ms
- [ ] No data inconsistencies
- [ ] All robot types detected correctly
- [ ] Teleoperation status accurate

### Rollback Trigger
```bash
# migration/scripts/rollback_canary.sh
#!/bin/bash
if [ "$1" == "emergency" ]; then
    # Immediate rollback
    ./update_traffic_split.sh 0
    
    # Disable feature flags
    python3 -c "
import yaml
config = yaml.safe_load(open('config/migration_config.yaml'))
config['rollout']['canary_percentage'] = 0
for flag in config['rollout']['feature_flags']:
    config['rollout']['feature_flags'][flag] = False
yaml.dump(config, open('config/migration_config.yaml', 'w'))
"
    
    # Alert team
    curl -X POST https://hooks.slack.com/services/XXX \
        -H 'Content-Type: application/json' \
        -d '{"text":"🚨 EMERGENCY ROLLBACK: Canary deployment rolled back"}'
fi
```

---

## Phase 3: 25% Rollout

### Objective
Increase traffic to 25%, validate performance at scale.

### Implementation

1. **Scale New System**
```yaml
# docker-compose.scale.yml
version: '3.8'
services:
  discovery-service:
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '2'
          memory: 2G
        
  state-manager:
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '1'
          memory: 1G
```

2. **Performance Testing**
```python
# migration/tests/load_test.py
import asyncio
import aiohttp
import random

async def load_test_discovery(session, robot_count=1000):
    """Simulate robot discovery load"""
    tasks = []
    for i in range(robot_count):
        robot_ip = f"192.168.1.{random.randint(1, 254)}"
        task = session.get(f"http://localhost:8001/api/v2/discover/{robot_ip}")
        tasks.append(task)
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success = sum(1 for r in results if not isinstance(r, Exception))
    print(f"Discovery Success Rate: {success/robot_count*100:.2f}%")
```

### Validation
- [ ] 25% traffic handling smoothly
- [ ] Database connection pool stable
- [ ] Redis cache hit rate > 80%
- [ ] WebSocket connections stable
- [ ] No memory leaks detected

---

## Phase 4: 50% Rollout

### Objective
Equal traffic split, validate full feature parity.

### Implementation

1. **Enable All Features**
```yaml
# All feature flags enabled
rollout:
  canary_percentage: 50
  feature_flags:
    event_driven_discovery: true
    persistent_state: true
    websocket_monitoring: true
    teleoperation_optimization: true
```

2. **A/B Testing Validation**
```python
# migration/validation/ab_test.py
class ABTestValidator:
    async def compare_systems(self):
        """Compare legacy vs new system responses"""
        legacy_resp = await self.query_legacy("/robots")
        new_resp = await self.query_new("/api/v2/robots")
        
        # Compare robot counts
        assert len(legacy_resp) == len(new_resp), "Robot count mismatch"
        
        # Compare individual robots
        for legacy_robot in legacy_resp:
            new_robot = self.find_robot(new_resp, legacy_robot['id'])
            assert new_robot, f"Robot {legacy_robot['id']} missing in new system"
            assert legacy_robot['status'] == new_robot['status'], "Status mismatch"
```

### Data Integrity Check
```sql
-- migration/validation/data_integrity.sql
-- Check for orphaned records
SELECT r.* FROM robots r
LEFT JOIN robot_deployments rd ON r.id = rd.robot_id
WHERE rd.id IS NULL AND r.status = 'active';

-- Verify teleoperation status accuracy
SELECT 
    r.id,
    r.name,
    t.is_active as teleoperation_active,
    r.teleoperation_status
FROM robots r
LEFT JOIN teleoperation_sessions t ON r.id = t.robot_id
WHERE t.is_active != r.teleoperation_status;
```

---

## Phase 5: 100% Migration

### Objective
Complete migration to new system, legacy in standby.

### Implementation

1. **Full Cutover**
```bash
# migration/scripts/full_cutover.sh
#!/bin/bash

# Update traffic to 100% new system
./update_traffic_split.sh 100

# Keep legacy in hot standby
docker-compose -f docker-compose.legacy.yml up -d

# Monitor for 1 hour
echo "Monitoring full cutover for 1 hour..."
sleep 3600

# If stable, proceed to decommission planning
if [ $(curl -s http://localhost:8001/api/v2/health | jq -r '.status') == "healthy" ]; then
    echo "✅ Migration successful! Legacy system can be scheduled for decommission."
else
    echo "⚠️ Issues detected, keeping legacy in standby"
fi
```

2. **Final Validation**
```python
# migration/validation/final_check.py
async def final_validation():
    checks = {
        "all_robots_migrated": check_robot_migration(),
        "teleoperation_accurate": check_teleoperation_status(),
        "websockets_stable": check_websocket_connections(),
        "no_data_loss": check_data_integrity(),
        "performance_acceptable": check_performance_metrics()
    }
    
    for check, result in checks.items():
        if not result:
            raise Exception(f"Final validation failed: {check}")
    
    return True
```

---

## Phase 6: Legacy Decommissioning

### Objective
Safely remove legacy system after stability period.

### Timeline
- Week 7: Monitoring period
- Week 8: Backup and decommission

### Decommission Steps

1. **Final Backup**
```bash
# migration/scripts/final_backup.sh
#!/bin/bash
BACKUP_DIR="/backups/legacy_system_$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

# Backup legacy database
pg_dump legacy_db > $BACKUP_DIR/legacy_db.sql

# Backup legacy configs
cp -r /etc/lekiwi-legacy $BACKUP_DIR/configs

# Backup legacy logs
tar -czf $BACKUP_DIR/logs.tar.gz /var/log/lekiwi-legacy

# Create manifest
cat > $BACKUP_DIR/manifest.json <<EOF
{
  "date": "$(date -Iseconds)",
  "system_version": "legacy-final",
  "backup_contents": [
    "database",
    "configurations", 
    "logs"
  ]
}
EOF
```

2. **Service Removal**
```bash
# migration/scripts/decommission.sh
#!/bin/bash

# Stop services
systemctl stop lekiwi-legacy
docker-compose -f docker-compose.legacy.yml down

# Remove legacy code
mv /opt/lekiwi-legacy /opt/archived/lekiwi-legacy-$(date +%Y%m%d)

# Clean up ports
iptables -D INPUT -p tcp --dport 8000 -j ACCEPT

# Update DNS
# Remove legacy A records
```

---

## Rollback Procedures

### Universal Rollback Script
```bash
# migration/scripts/universal_rollback.sh
#!/bin/bash

PHASE=$1
REASON=$2

case $PHASE in
  "canary_10")
    ./update_traffic_split.sh 0
    ;;
  "rollout_25")
    ./update_traffic_split.sh 10
    ;;
  "rollout_50")
    ./update_traffic_split.sh 25
    ;;
  "full_100")
    ./update_traffic_split.sh 50
    ;;
  "emergency")
    # Full rollback to legacy
    ./update_traffic_split.sh 0
    systemctl restart lekiwi-legacy
    ;;
esac

# Log rollback
echo "$(date -Iseconds) - Rollback from $PHASE - Reason: $REASON" >> /var/log/migration_rollback.log

# Alert team
./send_alert.sh "Rollback initiated: Phase=$PHASE, Reason=$REASON"
```

---

## Monitoring & Alerts

### Key Metrics
```yaml
# monitoring/alerts.yaml
alerts:
  - name: HighErrorRate
    expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.01
    severity: critical
    action: rollback
    
  - name: HighLatency
    expr: histogram_quantile(0.99, http_request_duration_seconds) > 0.1
    severity: warning
    
  - name: DatabaseConnectionExhausted
    expr: pg_connections_active / pg_connections_max > 0.9
    severity: critical
    action: scale
    
  - name: RedisMemoryHigh
    expr: redis_memory_used_bytes / redis_memory_max_bytes > 0.9
    severity: warning
```

### Dashboard Queries
```sql
-- Real-time migration status
SELECT 
    COUNT(*) FILTER (WHERE system = 'legacy') as legacy_count,
    COUNT(*) FILTER (WHERE system = 'new') as new_count,
    COUNT(*) FILTER (WHERE system = 'both') as both_count
FROM migration_tracking
WHERE timestamp > NOW() - INTERVAL '1 hour';

-- Error comparison
SELECT 
    system,
    COUNT(*) as error_count,
    AVG(response_time) as avg_latency
FROM request_logs
WHERE status >= 500 
    AND timestamp > NOW() - INTERVAL '10 minutes'
GROUP BY system;
```

---

## Troubleshooting Guide

### Common Issues

#### Issue: High error rate on new system
```bash
# Check service health
curl http://localhost:8001/api/v2/health | jq

# Check database connections
psql -U lekiwi_admin -c "SELECT count(*) FROM pg_stat_activity;"

# Check Redis
redis-cli ping

# Rollback if needed
./universal_rollback.sh current_phase "high_error_rate"
```

#### Issue: Data inconsistency
```python
# migration/fixes/data_reconciliation.py
async def reconcile_data():
    """Fix data inconsistencies between systems"""
    legacy_robots = await fetch_legacy_robots()
    new_robots = await fetch_new_robots()
    
    # Find missing robots
    missing = set(legacy_robots.keys()) - set(new_robots.keys())
    
    for robot_id in missing:
        await migrate_single_robot(robot_id)
```

#### Issue: WebSocket connection drops
```javascript
// migration/fixes/websocket_reconnect.js
class WebSocketManager {
    constructor() {
        this.reconnectAttempts = 0;
        this.maxReconnects = 5;
    }
    
    connect() {
        this.ws = new WebSocket('ws://localhost:8001/ws');
        
        this.ws.onerror = () => {
            if (this.reconnectAttempts < this.maxReconnects) {
                setTimeout(() => this.connect(), 1000 * Math.pow(2, this.reconnectAttempts));
                this.reconnectAttempts++;
            } else {
                this.fallbackToPolling();
            }
        };
    }
}
```

---

## Success Criteria

### Overall Migration Success
- [ ] Zero unplanned downtime
- [ ] < 0.01% error rate increase
- [ ] No data loss
- [ ] All robots successfully migrated
- [ ] Teleoperation status 100% accurate
- [ ] Performance improvement > 50%
- [ ] Team trained on new system

### Post-Migration Validation
- [ ] 7-day stability period passed
- [ ] All alerts resolved
- [ ] Documentation updated
- [ ] Legacy system safely archived
- [ ] Post-mortem completed

---

## Appendix

### Contact Information
- Migration Lead: [TBD]
- On-Call: [TBD]
- Escalation: [TBD]

### Resources
- [Architecture Documentation](../architecture/lekiwi-heartbeat-architecture.md)
- [Refactoring Strategy](../refactoring/01_modular_refactoring_strategy.md)
- [API Documentation](../docs/api/README.md)
- [Runbooks](./runbooks/)