# Lekiwi Heartbeat Migration Operator Runbook

**Version**: 1.0.0  
**Last Updated**: 2025-01-29  
**Critical Contacts**: See [Emergency Contacts](#emergency-contacts)

---

## Quick Reference

### Critical Commands
```bash
# Check system status
curl http://localhost:8000/health       # Legacy
curl http://localhost:8001/api/v2/health # New

# Update traffic split
./migration/scripts/update_traffic_split.sh <percentage>

# Emergency rollback
./migration/scripts/universal_rollback.sh emergency "reason"

# View logs
tail -f /var/log/migration/*.log
docker-compose logs -f <service-name>
```

### Current Phase Status
Check current migration phase:
```bash
grep "phase:" /app/config/migration_config.yaml
```

---

## Phase 1: Parallel Deployment

### Objectives
- Deploy new system alongside legacy
- Verify all services start correctly
- Enable shadow traffic mirroring

### Steps

#### 1.1 Pre-deployment Checks
```bash
# Verify legacy system health
curl -s http://localhost:8000/health | jq '.'

# Check resource availability
df -h
free -h
docker system df
```

#### 1.2 Deploy New Services
```bash
# Navigate to migration directory
cd /app/migration

# Deploy services
docker-compose -f docker-compose.new.yml up -d

# Wait for services to initialize (2-3 minutes)
sleep 180

# Check service status
docker-compose -f docker-compose.new.yml ps
```

#### 1.3 Verify Service Health
```bash
# Check each service endpoint
for port in 8001 8002 8003 8004; do
    echo "Checking service on port $port..."
    curl -s http://localhost:$port/health | jq '.'
done

# Verify database connectivity
docker exec postgres psql -U lekiwi_admin -d lekiwi_heartbeat -c "SELECT 1;"

# Verify Redis connectivity
docker exec redis redis-cli ping
```

#### 1.4 Enable Shadow Traffic
```bash
# Update NGINX configuration
sudo cp /app/migration/nginx/shadow-traffic.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/shadow-traffic.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo nginx -s reload
```

#### 1.5 Start Data Synchronization
```bash
# Run initial sync
python3 /app/migration/scripts/sync_legacy_to_new.py --batch-size 50

# Start continuous sync in background
nohup python3 /app/migration/scripts/sync_legacy_to_new.py \
    --continuous --interval 60 > /var/log/migration/sync.log 2>&1 &

# Note the PID for later
echo $! > /var/run/migration-sync.pid
```

### Monitoring During Phase 1
```bash
# Watch logs for errors
tail -f /var/log/migration/*.log | grep -E "ERROR|CRITICAL"

# Monitor resource usage
watch -n 5 'docker stats --no-stream'

# Check sync progress
tail -f /var/log/migration/sync.log
```

### Success Criteria
- [ ] All new services running
- [ ] No errors in logs for 10 minutes
- [ ] Shadow traffic being processed
- [ ] Data sync completed successfully

### Rollback (if needed)
```bash
# Stop new services
docker-compose -f docker-compose.new.yml down

# Remove shadow traffic config
sudo rm /etc/nginx/sites-enabled/shadow-traffic.conf
sudo nginx -s reload

# Stop sync process
kill $(cat /var/run/migration-sync.pid)
```

---

## Phase 2: 10% Canary Deployment

### Objectives
- Route 10% of production traffic to new system
- Monitor for errors and performance issues
- Validate data consistency

### Steps

#### 2.1 Pre-canary Checks
```bash
# Verify Phase 1 completion
./migration/scripts/verify_phase.sh 1

# Check current sync status
curl http://localhost:8002/api/sync/status

# Backup current state
./migration/scripts/backup_state.sh pre-canary-10
```

#### 2.2 Enable Canary Traffic
```bash
# Update traffic split to 10%
./migration/scripts/update_traffic_split.sh 10 "$USER"

# Verify traffic split
grep "weight=" /etc/nginx/conf.d/upstream.conf
```

#### 2.3 Enable Feature Flags
```bash
# Update feature flags for canary
python3 -c "
import yaml
with open('/app/config/migration_config.yaml', 'r+') as f:
    config = yaml.safe_load(f)
    config['rollout']['feature_flags']['event_driven_discovery'] = True
    config['rollout']['feature_flags']['persistent_state'] = True
    f.seek(0)
    yaml.dump(config, f)
    f.truncate()
"
```

#### 2.4 Monitor Canary Health

**Dashboard URLs**:
- Grafana: http://localhost:3000/d/migration-canary
- Prometheus: http://localhost:9090

**Key Metrics to Watch**:
```bash
# Error rate (should be < 0.1%)
curl -s http://localhost:9090/api/v1/query?query=rate(http_requests_total{status=~"5..",system="new"}[5m]) | jq '.data.result[0].value[1]'

# P99 latency (should be < 100ms)
curl -s http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,rate(http_request_duration_seconds_bucket{system="new"}[5m])) | jq '.data.result[0].value[1]'

# Robot count comparison
./migration/scripts/compare_robot_counts.sh
```

### Monitoring Commands
```bash
# Real-time error monitoring
watch -n 5 'curl -s http://localhost:8001/api/v2/metrics | grep error'

# Compare system responses
./migration/scripts/ab_test_validator.sh --runs 100

# Check data consistency
python3 /app/migration/validation/data_integrity_check.py
```

### Success Criteria
- [ ] Error rate < 0.1% for 30 minutes
- [ ] P99 latency < 100ms
- [ ] No data inconsistencies detected
- [ ] All robot types detected correctly

### Rollback Trigger Conditions
Execute rollback if ANY of these occur:
- Error rate > 1%
- P99 latency > 500ms
- Data corruption detected
- Critical service failure

**Rollback Command**:
```bash
./migration/scripts/universal_rollback.sh canary_10 "Reason for rollback"
```

---

## Phase 3: 25% Rollout

### Steps

#### 3.1 Scale New System
```bash
# Scale services for increased load
docker-compose -f docker-compose.new.yml up -d --scale discovery-service=3 --scale state-manager=2

# Verify scaling
docker-compose -f docker-compose.new.yml ps
```

#### 3.2 Increase Traffic
```bash
# Update to 25%
./migration/scripts/update_traffic_split.sh 25 "$USER"

# Run load test
./migration/tests/load_test.sh --target-rps 1000 --duration 300
```

### Monitoring
```bash
# Database connection pool usage
watch -n 5 'psql -U lekiwi_admin -c "SELECT count(*) FROM pg_stat_activity;"'

# Redis memory usage
watch -n 5 'redis-cli info memory | grep used_memory_human'

# Service health across all instances
for i in {1..3}; do
    docker exec discovery-service-$i curl -s http://localhost:8001/health
done
```

---

## Phase 4: 50% Rollout

### Steps

#### 4.1 Enable All Features
```bash
# Enable all feature flags
python3 /app/migration/scripts/feature_flags.py --enable-all

# Verify WebSocket connections
wscat -c ws://localhost:9001/ws
```

#### 4.2 Equal Traffic Split
```bash
# Update to 50%
./migration/scripts/update_traffic_split.sh 50 "$USER"
```

#### 4.3 A/B Testing Validation
```bash
# Run comprehensive comparison
python3 /app/migration/validation/ab_test.py --iterations 1000 --report
```

---

## Phase 5: 100% Migration

### Steps

#### 5.1 Full Cutover
```bash
# Final backup before cutover
./migration/scripts/backup_all.sh pre-100-cutover

# Update to 100%
./migration/scripts/update_traffic_split.sh 100 "$USER"

# Keep legacy in standby
docker-compose -f docker-compose.legacy.yml up -d
```

#### 5.2 Final Validation
```bash
# Run full validation suite
python3 /app/migration/validation/final_check.py

# Monitor for 1 hour
./migration/scripts/monitor_cutover.sh --duration 3600
```

---

## Emergency Procedures

### High Error Rate
```bash
# 1. Check specific errors
tail -n 100 /var/log/migration/error.log | grep -E "ERROR|CRITICAL"

# 2. Identify failing service
docker-compose -f docker-compose.new.yml ps

# 3. Restart problematic service
docker-compose -f docker-compose.new.yml restart <service-name>

# 4. If errors persist, rollback
./migration/scripts/universal_rollback.sh <current-phase> "High error rate"
```

### Database Connection Exhaustion
```bash
# 1. Check connection count
psql -U lekiwi_admin -c "SELECT count(*) FROM pg_stat_activity;"

# 2. Kill idle connections
psql -U lekiwi_admin -c "
SELECT pg_terminate_backend(pid) 
FROM pg_stat_activity 
WHERE state = 'idle' 
  AND state_change < current_timestamp - INTERVAL '10 minutes';"

# 3. Increase pool size if needed
docker-compose -f docker-compose.new.yml exec postgres \
    psql -c "ALTER SYSTEM SET max_connections = 300;"
docker-compose -f docker-compose.new.yml restart postgres
```

### Redis Memory Full
```bash
# 1. Check memory usage
redis-cli info memory

# 2. Flush old keys
redis-cli --scan --pattern "robot:*" | \
    xargs -L 1 redis-cli expire 60

# 3. Increase memory limit
docker-compose -f docker-compose.new.yml exec redis \
    redis-cli CONFIG SET maxmemory 4gb
```

### Complete System Failure
```bash
# EMERGENCY ROLLBACK - Do not wait
./migration/scripts/universal_rollback.sh emergency "Complete system failure" true

# Notify all stakeholders immediately
./migration/scripts/send_emergency_alert.sh "CRITICAL: Migration failed, emergency rollback initiated"
```

---

## Monitoring Dashboards

### Grafana Access
- URL: http://localhost:3000
- Username: admin
- Password: [See secrets manager]

### Key Dashboards
1. **Migration Overview**: Overall migration metrics
2. **Service Health**: Individual service status
3. **Database Performance**: PostgreSQL metrics
4. **Cache Performance**: Redis metrics
5. **Error Analysis**: Error rates and types

### Alert Channels
- Slack: #migration-alerts
- Email: migration-team@lekiwi.com
- PagerDuty: migration-oncall

---

## Troubleshooting Guide

### Service Won't Start
```bash
# Check logs
docker-compose -f docker-compose.new.yml logs <service-name>

# Check resource constraints
docker inspect <container-name> | grep -A 10 "Resources"

# Rebuild and restart
docker-compose -f docker-compose.new.yml build <service-name>
docker-compose -f docker-compose.new.yml up -d <service-name>
```

### Data Inconsistency
```bash
# Run reconciliation
python3 /app/migration/fixes/data_reconciliation.py

# Verify fix
python3 /app/migration/validation/data_integrity_check.py
```

### WebSocket Disconnections
```bash
# Check connection count
netstat -an | grep 9001 | wc -l

# Increase connection limits
sysctl -w net.core.somaxconn=10000
echo "net.core.somaxconn=10000" >> /etc/sysctl.conf
```

---

## Post-Migration Tasks

### After Successful Migration
1. Document lessons learned
2. Update monitoring thresholds
3. Schedule legacy decommissioning
4. Plan celebration! 🎉

### Performance Tuning
```bash
# Analyze query performance
psql -U lekiwi_admin -c "
SELECT query, calls, mean_time, max_time 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;"

# Optimize indexes
python3 /app/migration/optimization/index_advisor.py
```

---

## Emergency Contacts

### Primary Contacts
- **Migration Lead**: [Name] - [Phone] - [Email]
- **On-Call Lead**: [Name] - [Phone] - [Email]
- **Database Admin**: [Name] - [Phone] - [Email]

### Escalation Path
1. On-Call Engineer (5 min)
2. Team Lead (10 min)
3. Director of Engineering (20 min)
4. CTO (30 min)

### External Support
- AWS Support: [Case URL]
- PostgreSQL Consultant: [Contact]
- Redis Support: [Contact]

---

## Appendix

### Useful Queries

**Check robot distribution**:
```sql
SELECT 
    system,
    COUNT(*) as robot_count,
    AVG(response_time) as avg_response
FROM migration_tracking
WHERE timestamp > NOW() - INTERVAL '10 minutes'
GROUP BY system;
```

**Find slow queries**:
```sql
SELECT 
    query,
    calls,
    mean_time,
    total_time
FROM pg_stat_statements
WHERE mean_time > 100
ORDER BY mean_time DESC;
```

**Cache hit ratio**:
```bash
redis-cli info stats | grep keyspace_hits
redis-cli info stats | grep keyspace_misses
```

### Reference Links
- [Architecture Documentation](../architecture/lekiwi-heartbeat-architecture.md)
- [API Documentation](../docs/api/README.md)
- [Migration Plan](../migration-plan.md)
- [Rollback Procedures](../scripts/universal_rollback.sh)

---

**Remember**: Stay calm, follow the runbook, and don't hesitate to ask for help! 💪