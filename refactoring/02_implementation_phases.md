# Implementation Phases - Detailed Breakdown

## Phase 1: Foundation Layer (Week 1)

### Critical Path Items

These modules form the foundation and must be completed first:

#### 1.1 State Manager Module

**Implementation Steps**:
```
Day 1-2: Database Schema & Event Store
  - Design event schema
  - Create PostgreSQL tables
  - Implement event append logic
  - Add event validation
  # TEST: Event persistence works
  # TEST: Schema validation enforced

Day 2-3: Aggregate Management
  - Implement aggregate base class
  - Create robot aggregate
  - Add state reconstruction
  - Implement snapshots
  # TEST: Aggregates rebuild from events
  # TEST: Snapshots reduce rebuild time

Day 3-4: Cache Layer
  - Redis connection pool
  - Cache warming strategy
  - TTL management
  - Cache invalidation
  # TEST: Cache improves query speed 10x
  # TEST: Cache invalidation cascades properly
```

**Resource Requirements**:
- 1 Senior Backend Engineer
- PostgreSQL 14+ instance
- Redis 6+ instance
- 16GB RAM for development

#### 1.2 Event Bus Module

**Implementation Steps**:
```
Day 1: Message Broker Setup
  - Install NATS/RabbitMQ
  - Configure exchanges/topics
  - Set up clustering
  # TEST: Broker handles 10K msgs/sec
  # TEST: Clustering provides HA

Day 2-3: Publisher Implementation
  - Event serialization
  - Priority queues
  - Retry logic
  - Dead letter queue
  # TEST: Priority messages delivered first
  # TEST: Failed messages retry with backoff

Day 3-4: Subscriber Framework
  - Topic filtering
  - Handler registration
  - Error handling
  - Acknowledgments
  # TEST: Subscribers filter correctly
  # TEST: No message loss on errors
```

#### 1.3 Data Layer Module

**Implementation Steps**:
```
Day 1-2: Connection Management
  - Connection pooling
  - Health checks
  - Failover logic
  # TEST: Pool maintains connections
  # TEST: Automatic failover works

Day 2-3: Query Optimization
  - Query builder
  - Index management
  - Query caching
  # TEST: Queries use indexes
  # TEST: N+1 queries prevented

Day 3-4: Transaction Support
  - Transaction wrapper
  - Rollback handling
  - Distributed transactions
  # TEST: Transactions atomic
  # TEST: Rollbacks clean up properly
```

### Parallel Work Streams

These can be worked on simultaneously by different team members:

**Stream A**: Database Setup (DevOps)
- Provision PostgreSQL cluster
- Configure replication
- Set up backups
- Create monitoring

**Stream B**: Message Broker Setup (DevOps)
- Deploy NATS/RabbitMQ
- Configure clustering
- Set up monitoring
- Create topics/exchanges

**Stream C**: Development Environment (All)
- Docker Compose setup
- Local development configs
- Test data generation
- CI/CD pipeline setup

## Phase 2: Communication Layer (Week 1-2)

### 2.1 WebSocket Gateway

**Implementation Timeline**:
```
Day 1-2: Core Server
  - WebSocket server setup
  - Connection handling
  - Authentication middleware
  # TEST: Server accepts connections
  # TEST: Auth blocks invalid tokens

Day 3-4: Connection Management
  - Connection pooling
  - Heartbeat/ping-pong
  - Reconnection logic
  # TEST: Dead connections cleaned up
  # TEST: Reconnection works smoothly

Day 5-6: Message Routing
  - Topic subscriptions
  - Message filtering
  - Broadcasting
  # TEST: Messages routed correctly
  # TEST: Broadcast scales to 1000s

Day 7: Load Testing
  - Stress test with 10K connections
  - Measure latency/throughput
  - Optimize bottlenecks
  # TEST: Handles 10K concurrent
  # TEST: p99 latency < 100ms
```

### 2.2 Protocol Adapter

**Implementation Timeline**:
```
Day 1-2: Legacy Endpoint Mapping
  - Map all current endpoints
  - Create compatibility layer
  - Response format conversion
  # TEST: All legacy endpoints work
  # TEST: Response format unchanged

Day 3-4: Caching Strategy
  - TTL configuration
  - Cache key design
  - Invalidation rules
  # TEST: Cache hit rate > 80%
  # TEST: Stale data prevented

Day 5: Integration Testing
  - Test with real robots
  - Verify backward compatibility
  - Performance comparison
  # TEST: Old clients work unchanged
  # TEST: No performance degradation
```

## Phase 3: Robot Agent (Week 2)

### 3.1 Lightweight Agent Core

**Memory Optimization Strategy**:
```python
# Memory Budget Allocation (Total: 50MB)
MEMORY_BUDGET = {
    "process_overhead": 10,  # MB - Python runtime
    "websocket_client": 5,   # MB - Connection handling
    "telemetry_buffer": 10,  # MB - Ring buffer for metrics
    "local_state": 5,        # MB - SQLite cache
    "command_queue": 5,      # MB - Pending commands
    "working_memory": 15     # MB - Processing buffer
}
```

**Implementation Steps**:
```
Day 1-2: Core Agent Structure
  - Single-file Python script
  - Minimal dependencies
  - Memory-mapped buffers
  # TEST: Total RAM < 50MB
  # TEST: Starts in < 5 seconds

Day 3-4: Connection Management
  - WebSocket client
  - Exponential backoff
  - Local queue for offline
  # TEST: Reconnects automatically
  # TEST: No data loss when offline

Day 5-6: Telemetry Collection
  - System metrics gathering
  - Delta compression
  - Batch sending
  # TEST: CPU usage < 1%
  # TEST: Network usage < 1KB/s avg
```

### 3.2 Teleoperation Detection

**Detection Algorithm**:
```python
# Multi-Signal Teleoperation Detection
TELEOPERATION_INDICATORS = {
    "joy_commands": {
        "weight": 0.4,
        "threshold": 5,  # msgs/sec
        "source": "/cmd_vel topic"
    },
    "video_streams": {
        "weight": 0.3,
        "threshold": 1,  # active streams
        "source": "port 8554 connections"
    },
    "webrtc_peers": {
        "weight": 0.2,
        "threshold": 1,  # peer connections
        "source": "WebRTC stats"
    },
    "control_latency": {
        "weight": 0.1,
        "threshold": 50,  # ms
        "source": "command round-trip"
    }
}

# TEST: Detects teleoperation within 1 second
# TEST: No false positives from service status
# TEST: Works for both LeKiwi and XLERobot
```

## Phase 4: Core Services (Week 2-3)

### 4.1 Discovery Service

**Parallel Discovery Methods**:
```python
DISCOVERY_METHODS = [
    {
        "name": "mDNS",
        "timeout": 2,
        "priority": 1,
        "implementation": "avahi/bonjour"
    },
    {
        "name": "ARP Scan",
        "timeout": 3,
        "priority": 2,
        "implementation": "arp -a parallel"
    },
    {
        "name": "Known IPs",
        "timeout": 5,
        "priority": 3,
        "implementation": "parallel SSH probe"
    },
    {
        "name": "DHCP Leases",
        "timeout": 1,
        "priority": 4,
        "implementation": "parse DHCP server"
    }
]
```

**Implementation Steps**:
```
Day 1-2: mDNS Discovery
  - Avahi integration
  - Service broadcasting
  - Listener implementation
  # TEST: Finds mDNS robots in 2s
  # TEST: Handles network changes

Day 3-4: Network Scanning
  - Parallel IP scanning
  - SSH fingerprinting
  - Robot type detection
  # TEST: Scans /24 in < 5s
  # TEST: Identifies robot types

Day 5-6: Registration Pipeline
  - Automatic registration
  - Metadata collection
  - State initialization
  # TEST: New robots auto-register
  # TEST: Metadata complete
```

### 4.2 Deployment Engine

**Differential Deployment Algorithm**:
```python
# Smart Deployment Strategy
DEPLOYMENT_STRATEGY = {
    "diff_calculation": {
        "method": "rsync --dry-run",
        "compression": "zstd",
        "checksum": "xxhash"
    },
    "batch_size": 5,
    "parallel_uploads": 3,
    "rollback_threshold": 0.8,  # 80% success required
    "health_check_timeout": 30,
    "deployment_timeout": 120
}
```

**Implementation Steps**:
```
Day 1-2: Diff Engine
  - File comparison
  - Delta generation
  - Compression pipeline
  # TEST: Diffs accurate
  # TEST: 90% size reduction

Day 3-4: Deployment Orchestration
  - Batch management
  - Parallel execution
  - Progress tracking
  # TEST: Deploys 100 robots in parallel
  # TEST: Progress accurately reported

Day 5-6: Rollback System
  - Snapshot before deploy
  - Automatic rollback triggers
  - Recovery procedures
  # TEST: Rollback in < 30s
  # TEST: No partial states
```

## Phase 5: Integration (Week 3)

### 5.1 API Gateway

**RESTful + GraphQL Implementation**:
```
Day 1-2: FastAPI Setup
  - OpenAPI documentation
  - Request validation
  - Response serialization
  # TEST: All endpoints documented
  # TEST: Validation rejects bad data

Day 3-4: GraphQL Layer
  - Schema definition
  - Resolver implementation
  - Subscription support
  # TEST: Queries optimized
  # TEST: Subscriptions real-time

Day 5: Security Layer
  - JWT authentication
  - Rate limiting
  - CORS configuration
  # TEST: Auth required everywhere
  # TEST: Rate limits enforced
```

### 5.2 Migration Tools

**Zero-Downtime Migration**:
```python
# Migration State Machine
MIGRATION_STATES = [
    "PREPARING",      # Set up new system
    "DUAL_WRITE",     # Write to both systems
    "DUAL_READ",      # Read from both, prefer new
    "NEW_PRIMARY",    # New system primary
    "OLD_READONLY",   # Old system read-only
    "DECOMMISSION"    # Remove old system
]

# TEST: Each state transition safe
# TEST: Can rollback from any state
# TEST: No data loss during migration
```

## Critical Dependencies

### Technical Dependencies

| Component | Version | Purpose | Alternative |
|-----------|---------|---------|-------------|
| PostgreSQL | 14+ | Event store | MySQL 8+ |
| Redis | 6+ | Cache layer | Memcached |
| NATS | 2.8+ | Message bus | RabbitMQ 3.9+ |
| Python | 3.9+ | Agent/Services | Go 1.18+ |
| Node.js | 16+ | WebSocket Gateway | Go 1.18+ |
| Docker | 20+ | Containerization | Podman |

### Team Dependencies

| Phase | Team Members | Skills Required |
|-------|--------------|-----------------|
| Foundation | 2 Backend Engineers | PostgreSQL, Event Sourcing |
| Communication | 1 Backend, 1 Frontend | WebSockets, Real-time systems |
| Agent | 1 Embedded Engineer | Python, Resource optimization |
| Services | 2 Backend Engineers | Distributed systems, Go/Python |
| Integration | 1 Full-stack Engineer | REST, GraphQL, React |

## Risk Mitigation

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| WebSocket connection instability | Medium | High | Implement robust reconnection, fallback to polling |
| Agent memory exceeds 50MB | Medium | Medium | Use Rust for agent, continuous profiling |
| State reconstruction slow | Low | High | Implement snapshots, cache aggressively |
| Message broker overload | Low | High | Use clustering, implement backpressure |
| Deployment failures | Medium | High | Automated rollback, health checks |

### Mitigation Strategies

```python
# Automated Risk Detection
RISK_MONITORS = {
    "memory_monitor": {
        "threshold": 45,  # MB - alert at 90% of budget
        "action": "alert_and_gc()"
    },
    "connection_monitor": {
        "threshold": 0.95,  # 95% connection success
        "action": "switch_to_polling()"
    },
    "deployment_monitor": {
        "threshold": 0.8,  # 80% success rate
        "action": "pause_and_rollback()"
    }
}
```

## Validation Criteria

### Phase Completion Checklist

**Phase 1 Complete When**:
- [ ] Event store accepting 1000 events/sec
- [ ] State queries return in < 10ms
- [ ] Cache hit ratio > 90%
- [ ] Message bus handles 10K msgs/sec
- [ ] Zero message loss under load

**Phase 2 Complete When**:
- [ ] WebSocket gateway handles 10K connections
- [ ] p99 latency < 100ms
- [ ] Protocol adapter maintains compatibility
- [ ] Reconnection works reliably
- [ ] Rate limiting prevents abuse

**Phase 3 Complete When**:
- [ ] Agent uses < 50MB RAM
- [ ] Agent CPU < 1% average
- [ ] Teleoperation detected correctly
- [ ] Offline queue prevents data loss
- [ ] Updates without restart

**Phase 4 Complete When**:
- [ ] Discovery finds all robots in < 5s
- [ ] Deployments complete in < 2 min
- [ ] Automatic rollback works
- [ ] Parallel deployments successful
- [ ] Health checks accurate

**Phase 5 Complete When**:
- [ ] API gateway fully documented
- [ ] GraphQL subscriptions work
- [ ] Migration tools tested
- [ ] Zero-downtime migration proven
- [ ] All legacy endpoints supported

## Rollout Strategy

### Progressive Rollout Plan

```yaml
Week 1:
  - Deploy foundation to staging
  - Run parallel with old system
  - Monitor for issues
  - Fix any bugs found

Week 2:
  - Deploy agent to 5 test robots
  - Monitor resource usage
  - Verify telemetry flow
  - Test reconnection scenarios

Week 3:
  - Expand to 25% of fleet
  - Monitor at scale
  - Test deployment engine
  - Verify rollback works

Week 4:
  - Expand to 50% of fleet
  - Run A/B comparison
  - Monitor all metrics
  - Prepare for full rollout

Week 5:
  - Deploy to 100% of fleet
  - Keep old system as backup
  - Monitor for 48 hours
  - Celebrate success!

Week 6:
  - Decommission old system
  - Archive old data
  - Update documentation
  - Post-mortem review
```

## Success Metrics Dashboard

```python
# Real-time Success Metrics
SUCCESS_METRICS = {
    "discovery": {
        "target": "< 5 seconds",
        "query": "SELECT avg(discovery_time) FROM discoveries WHERE time > now() - '5m'"
    },
    "agent_memory": {
        "target": "< 50MB",
        "query": "SELECT max(memory_usage) FROM agents WHERE time > now() - '5m'"
    },
    "deployment_time": {
        "target": "< 120 seconds",
        "query": "SELECT avg(deployment_duration) FROM deployments WHERE time > now() - '1h'"
    },
    "websocket_latency": {
        "target": "< 100ms p99",
        "query": "SELECT percentile(latency, 0.99) FROM websocket_metrics WHERE time > now() - '5m'"
    },
    "error_rate": {
        "target": "< 0.1%",
        "query": "SELECT count(errors) / count(*) FROM api_requests WHERE time > now() - '5m'"
    }
}
```

## Conclusion

This detailed implementation plan provides:

1. **Clear daily tasks** for each module
2. **Parallel work streams** to maximize efficiency
3. **Specific test criteria** for validation
4. **Risk mitigation** strategies
5. **Progressive rollout** to minimize impact

The modular approach ensures that each component can be developed, tested, and deployed independently, reducing risk and allowing for rapid iteration. The focus on "doing more with less" is evident in the lightweight agent design and efficient communication protocols.

Total estimated timeline: 4 weeks for development, 2 weeks for rollout, achieving a 10-20x improvement in performance while reducing resource usage by 75%.