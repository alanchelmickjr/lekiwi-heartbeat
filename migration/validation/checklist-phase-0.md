# Phase 0: Pre-Migration Validation Checklist

**Date**: _______________  
**Validator**: _______________  
**Phase**: Pre-Migration Preparation

## Infrastructure Readiness

### Database Setup
- [ ] PostgreSQL 14 installed and running
- [ ] Database `lekiwi_heartbeat` created
- [ ] User `lekiwi_admin` created with proper permissions
- [ ] Connection pooling configured (max_connections >= 200)
- [ ] Backup strategy in place
- [ ] Replication configured (if applicable)

### Redis Setup
- [ ] Redis 7+ installed and running
- [ ] Memory limit configured (2GB minimum)
- [ ] Eviction policy set to `allkeys-lru`
- [ ] Persistence configured (if required)
- [ ] Redis Sentinel configured (for HA)

### Network Configuration
- [ ] Firewall rules updated for new ports
  - [ ] 8001 (Discovery Service)
  - [ ] 8002 (State Manager)
  - [ ] 8003 (WebSocket Monitor)
  - [ ] 8004 (Teleoperation Service)
  - [ ] 5432 (PostgreSQL)
  - [ ] 6379 (Redis)
- [ ] SSL certificates generated and installed
- [ ] Load balancer (NGINX) installed and configured
- [ ] DNS entries prepared (but not activated)

### Monitoring Setup
- [ ] Prometheus installed and configured
- [ ] Grafana installed with dashboards
- [ ] Alert rules configured
- [ ] Log aggregation working (ELK/Loki)
- [ ] Metrics endpoints verified

## Application Readiness

### Docker Images
- [ ] All service images built successfully
- [ ] Images pushed to registry
- [ ] Image tags documented
- [ ] Security scanning completed

### Configuration Files
- [ ] `migration_config.yaml` created
- [ ] Environment variables documented
- [ ] Secrets management configured
- [ ] Feature flags initialized (all disabled)

### Scripts and Tools
- [ ] Migration scripts executable
  - [ ] `update_traffic_split.sh`
  - [ ] `sync_legacy_to_new.py`
  - [ ] `universal_rollback.sh`
- [ ] Backup scripts tested
- [ ] Monitoring scripts ready

## Testing Verification

### Unit Tests
- [ ] Discovery service tests passing
- [ ] State manager tests passing
- [ ] WebSocket monitor tests passing
- [ ] Teleoperation service tests passing

### Integration Tests
- [ ] Database connectivity verified
- [ ] Redis connectivity verified
- [ ] Inter-service communication tested
- [ ] Legacy API compatibility confirmed

### Load Tests
- [ ] Target load defined (______ requests/sec)
- [ ] Load test scenarios created
- [ ] Performance baselines established
- [ ] Resource limits validated

## Documentation Review

### Technical Documentation
- [ ] Architecture diagrams updated
- [ ] API documentation complete
- [ ] Database schema documented
- [ ] Network topology documented

### Operational Documentation
- [ ] Runbooks reviewed and updated
- [ ] Troubleshooting guides prepared
- [ ] Rollback procedures documented
- [ ] Contact list updated

## Team Readiness

### Training
- [ ] Team briefed on new architecture
- [ ] Hands-on training completed
- [ ] Access credentials distributed
- [ ] Emergency procedures reviewed

### Communication
- [ ] Slack channels configured
- [ ] Alert routing configured
- [ ] Escalation paths defined
- [ ] Stakeholders notified

## Risk Assessment

### Identified Risks
- [ ] Risk register updated
- [ ] Mitigation strategies defined
- [ ] Contingency plans prepared
- [ ] Rollback triggers defined

### Dependencies
- [ ] External service dependencies verified
- [ ] Third-party API limits checked
- [ ] License compliance verified
- [ ] Resource availability confirmed

## Final Verification

### Go/No-Go Criteria
- [ ] All critical items checked
- [ ] Performance benchmarks met
- [ ] Security scan passed
- [ ] Team consensus achieved

### Sign-offs
- [ ] Technical Lead: _______________
- [ ] Operations Lead: _______________
- [ ] Product Owner: _______________
- [ ] Migration Lead: _______________

## Notes
_____________________________________
_____________________________________
_____________________________________

**Decision**: ☐ PROCEED  ☐ DELAY  ☐ ABORT

**Reason**: _________________________