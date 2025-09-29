# Lekiwi Heartbeat Migration Package

**Version**: 1.0.0  
**Created**: 2025-01-29  
**Purpose**: Zero-downtime migration from legacy polling system to event-driven architecture

---

## 📋 Executive Summary

This migration package provides a complete, production-ready plan to transition the Lekiwi Heartbeat robot deployment system from its current broken state (serial polling, in-memory state, incorrect teleoperation) to a new event-driven architecture with PostgreSQL/Redis persistence, WebSocket monitoring, and real-time teleoperation tracking.

### Key Features
- ✅ **Zero Downtime**: Parallel deployment with gradual traffic migration
- ✅ **Incremental Rollout**: 0% → 10% → 25% → 50% → 100% phased approach
- ✅ **Full Rollback**: Complete rollback capability at any phase
- ✅ **Automated Monitoring**: Prometheus + Grafana with automatic alerts
- ✅ **Data Integrity**: Continuous synchronization and validation
- ✅ **Dual Robot Support**: Handles both Lekiwi and XLE robots

---

## 🗂️ Package Contents

### 📄 Core Documents

| Document | Purpose | Location |
|----------|---------|----------|
| **Migration Plan** | Complete migration strategy with 6 phases | [`migration-plan.md`](migration-plan.md) |
| **Operator Runbook** | Step-by-step procedures for operators | [`runbooks/operator-runbook.md`](runbooks/operator-runbook.md) |
| **Pre-Migration Checklist** | Validation before starting | [`validation/checklist-phase-0.md`](validation/checklist-phase-0.md) |

### 🔧 Migration Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| **Traffic Splitter** | Gradually shift traffic between systems | `./scripts/update_traffic_split.sh <percentage>` |
| **Data Synchronizer** | Migrate data from legacy to new | `python3 scripts/sync_legacy_to_new.py` |
| **Universal Rollback** | Rollback from any phase | `./scripts/universal_rollback.sh <phase> <reason>` |

### 🐳 Infrastructure

| Component | Purpose | File |
|-----------|---------|------|
| **Docker Compose** | New system deployment | [`docker-compose.new.yml`](docker-compose.new.yml) |
| **Prometheus Config** | Metrics collection | [`monitoring/prometheus.yml`](monitoring/prometheus.yml) |
| **Alert Rules** | Automated monitoring | [`monitoring/alerts/migration-alerts.yml`](monitoring/alerts/migration-alerts.yml) |

---

## 🚀 Quick Start

### Prerequisites
```bash
# Verify system requirements
- PostgreSQL 14+
- Redis 7+
- Docker 20.10+
- Python 3.8+
- 16GB RAM minimum
- 100GB available disk space
```

### Phase Overview

| Phase | Duration | Traffic | Risk | Rollback Time |
|-------|----------|---------|------|---------------|
| **0: Preparation** | 1 week | 0% | Low | N/A |
| **1: Parallel Deploy** | 1 week | 0% (shadow) | Low | < 1 min |
| **2: Canary 10%** | 1 week | 10% | Medium | < 2 min |
| **3: Rollout 25%** | 1 week | 25% | Medium | < 2 min |
| **4: Rollout 50%** | 1 week | 50% | High | < 5 min |
| **5: Full 100%** | 1 week | 100% | High | < 10 min |
| **6: Decommission** | 2 weeks | 100% | Low | N/A |

### Starting Migration

#### Step 1: Pre-Migration Setup
```bash
# 1. Clone migration package
cd /app
git clone <repository> migration

# 2. Run pre-migration checks
cd migration
./validation/run_prechecks.sh

# 3. Setup infrastructure
docker-compose -f docker-compose.new.yml pull
./scripts/setup_databases.sh
```

#### Step 2: Deploy New System (Shadow Mode)
```bash
# Deploy services without traffic
docker-compose -f docker-compose.new.yml up -d

# Start data synchronization
python3 scripts/sync_legacy_to_new.py --continuous &

# Verify health
curl http://localhost:8001/api/v2/health
```

#### Step 3: Begin Traffic Migration
```bash
# Start with 10% canary
./scripts/update_traffic_split.sh 10

# Monitor metrics
open http://localhost:3000  # Grafana dashboard

# If stable after 1 hour, proceed to 25%
./scripts/update_traffic_split.sh 25
```

---

## 📊 Monitoring & Validation

### Key Metrics to Watch

| Metric | Threshold | Action if Exceeded |
|--------|-----------|-------------------|
| Error Rate | < 0.1% | Investigate, consider rollback |
| P99 Latency | < 100ms | Scale services, optimize queries |
| CPU Usage | < 80% | Scale horizontally |
| Memory Usage | < 85% | Increase limits, optimize |
| DB Connections | < 90% | Increase pool size |

### Dashboards
- **Grafana**: http://localhost:3000
- **Prometheus**: http://localhost:9090
- **Legacy System**: http://localhost:8000/metrics
- **New System**: http://localhost:8001/metrics

### Validation Commands
```bash
# Compare robot counts
curl http://localhost:8002/api/validation/robot-count

# Check data consistency
python3 validation/data_integrity_check.py

# Run A/B test
python3 validation/ab_test.py --iterations 1000
```

---

## 🔄 Rollback Procedures

### Immediate Rollback
```bash
# For any phase
./scripts/universal_rollback.sh <phase> "reason"

# Emergency (complete revert)
./scripts/universal_rollback.sh emergency "critical failure" true
```

### Rollback Decision Matrix

| Condition | Severity | Action | Command |
|-----------|----------|--------|---------|
| Error rate > 1% | Critical | Immediate rollback | `./scripts/universal_rollback.sh current_phase "high_errors"` |
| P99 > 500ms | High | Investigate, then rollback | `./scripts/universal_rollback.sh current_phase "performance"` |
| Data corruption | Critical | Full rollback + restore | `./scripts/universal_rollback.sh data_corruption "corruption"` |
| Service down > 5min | Critical | Rollback to previous phase | `./scripts/universal_rollback.sh current_phase "service_failure"` |

---

## 👥 Team Responsibilities

### Role Assignments

| Role | Primary Responsibility | Backup |
|------|----------------------|--------|
| **Migration Lead** | Overall coordination, decisions | Director of Engineering |
| **Infrastructure** | Database, Redis, networking | DevOps Team |
| **Backend** | Service deployment, data migration | Backend Team Lead |
| **Monitoring** | Metrics, alerts, dashboards | SRE Team |
| **QA** | Validation, testing | QA Lead |
| **On-Call** | 24/7 monitoring during migration | Rotating schedule |

### Communication Channels
- **Slack**: #migration-status (updates)
- **Slack**: #migration-alerts (automated)
- **Email**: migration-team@lekiwi.com
- **War Room**: Conference Room A (during critical phases)
- **Incident Call**: [Zoom link]

---

## 📈 Success Criteria

### Phase Completion Requirements

Each phase must meet these criteria before proceeding:

1. **Stability**: No critical alerts for 30+ minutes
2. **Performance**: Meeting all SLA requirements
3. **Accuracy**: Data validation passing 100%
4. **Monitoring**: All dashboards green
5. **Team Consensus**: Go/no-go vote passed

### Overall Migration Success

- ✅ Zero unplanned downtime
- ✅ < 0.01% increase in error rate
- ✅ No data loss
- ✅ All robots migrated successfully
- ✅ Teleoperation status 100% accurate
- ✅ Performance improvement > 50%
- ✅ Team trained on new system
- ✅ Legacy system safely decommissioned

---

## 🛠️ Troubleshooting

### Common Issues & Solutions

| Issue | Diagnosis | Solution |
|-------|-----------|----------|
| High error rate | Check logs: `tail -f /var/log/migration/error.log` | Restart service or rollback |
| Database exhaustion | `psql -c "SELECT count(*) FROM pg_stat_activity;"` | Kill idle connections, increase pool |
| Redis memory full | `redis-cli info memory` | Flush old keys, increase limit |
| WebSocket drops | `netstat -an \| grep 9001 \| wc -l` | Increase connection limits |
| Data mismatch | `python3 validation/data_integrity_check.py` | Run reconciliation script |

### Emergency Contacts

- **On-Call**: +1-XXX-XXX-XXXX
- **Migration Lead**: [Name] - [Email]
- **Database Admin**: [Name] - [Email]
- **AWS Support**: [Case URL]

---

## 📚 Additional Resources

### Documentation
- [System Architecture](../architecture/lekiwi-heartbeat-architecture.md)
- [Refactoring Strategy](../refactoring/01_modular_refactoring_strategy.md)
- [Factory Install System](../factory-install/docs/README.md)

### Training Materials
- [New System Overview](docs/training/system-overview.md)
- [Operator Training Video](https://link-to-video)
- [Troubleshooting Guide](docs/troubleshooting.md)

### Post-Migration
- [Performance Tuning Guide](docs/performance-tuning.md)
- [Capacity Planning](docs/capacity-planning.md)
- [Disaster Recovery Plan](docs/disaster-recovery.md)

---

## ✅ Final Checklist

Before starting migration:
- [ ] All team members trained
- [ ] Backup systems verified
- [ ] Rollback procedures tested
- [ ] Monitoring dashboards ready
- [ ] Communication channels setup
- [ ] Emergency contacts updated
- [ ] Stakeholders notified
- [ ] Maintenance window scheduled

---

## 📝 Notes

### Lessons from Testing
- Always verify backup restoration before starting
- Keep legacy system warm for at least 2 weeks post-migration
- Monitor closely during timezone changes (robot activity patterns differ)
- Have dedicated person watching dashboards during critical phases

### Known Limitations
- Maximum 10,000 concurrent WebSocket connections per server
- PostgreSQL connection pool limited to 200 connections
- Redis memory capped at 2GB (configurable)
- Data sync has 60-second lag in continuous mode

---

**Remember**: This is a marathon, not a sprint. Take breaks, communicate clearly, and don't hesitate to rollback if something doesn't feel right. The goal is a successful migration, not a fast one.

Good luck! 🚀

---

*Last Updated: 2025-01-29*  
*Version: 1.0.0*  
*Status: Ready for Production*