# Testing & Validation Strategy for Modular Refactoring

## Test-Driven Development Framework

### Core Testing Principles

1. **Write Tests First**: Every module starts with test specifications
2. **Test at Multiple Levels**: Unit → Integration → System → End-to-End
3. **Continuous Validation**: Automated testing on every commit
4. **Performance Benchmarks**: Every test includes performance criteria
5. **Rollback Triggers**: Failed tests automatically trigger rollback

## Module-Specific Test Suites

### 1. State Manager Tests

```python
# Unit Tests
class TestStateManager:
    
    def test_event_persistence(self):
        """Events must be persisted immutably"""
        # TEST: Event cannot be modified after storage
        event = create_robot_registered_event()
        event_id = state_manager.append(event)
        
        stored_event = state_manager.get_event(event_id)
        assert stored_event == event
        assert stored_event is not event  # Different object
        
        # Try to modify - should fail
        with pytest.raises(ImmutableError):
            stored_event.data["modified"] = True
    
    def test_aggregate_rebuilding(self):
        """Aggregates rebuild correctly from events"""
        # TEST: 1000 events rebuild in < 100ms
        events = [create_random_event() for _ in range(1000)]
        for event in events:
            state_manager.append(event)
        
        start_time = time.now()
        aggregate = state_manager.rebuild_aggregate(aggregate_id)
        rebuild_time = time.now() - start_time
        
        assert aggregate.version == 1000
        assert rebuild_time < 0.1  # 100ms
    
    def test_snapshot_optimization(self):
        """Snapshots reduce rebuild time by 10x"""
        # TEST: Snapshot + 100 events faster than 1000 events
        # Create aggregate with 900 events
        for i in range(900):
            state_manager.append(create_event())
        
        # Force snapshot at event 900
        state_manager.create_snapshot(aggregate_id)
        
        # Add 100 more events
        for i in range(100):
            state_manager.append(create_event())
        
        # Rebuild with snapshot should be 10x faster
        start_time = time.now()
        aggregate = state_manager.rebuild_aggregate(aggregate_id)
        snapshot_rebuild_time = time.now() - start_time
        
        # Compare to full rebuild
        state_manager.cache.clear()
        start_time = time.now()
        aggregate_full = state_manager.rebuild_aggregate_without_snapshot(aggregate_id)
        full_rebuild_time = time.now() - start_time
        
        assert snapshot_rebuild_time < full_rebuild_time / 10
        
    def test_concurrent_writes(self):
        """Concurrent writes don't cause conflicts"""
        # TEST: 100 concurrent writes all succeed
        import threading
        
        success_count = 0
        lock = threading.Lock()
        
        def write_event():
            nonlocal success_count
            event = create_random_event()
            event_id = state_manager.append(event)
            if event_id:
                with lock:
                    success_count += 1
        
        threads = [threading.Thread(target=write_event) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert success_count == 100
```

### 2. WebSocket Gateway Tests

```python
# Integration Tests
class TestWebSocketGateway:
    
    @pytest.mark.asyncio
    async def test_connection_limits(self):
        """Gateway handles 10,000 concurrent connections"""
        # TEST: Can establish 10K connections
        gateway = WebSocketGateway()
        connections = []
        
        for i in range(10000):
            ws = MockWebSocket()
            await gateway.connect(ws)
            connections.append(ws)
        
        assert gateway.connection_count() == 10000
        
        # TEST: Memory usage reasonable
        memory_usage = get_process_memory()
        assert memory_usage < 2000  # MB - ~200KB per connection
    
    @pytest.mark.asyncio
    async def test_message_latency(self):
        """Messages delivered with < 100ms p99 latency"""
        # TEST: 10,000 messages with latency tracking
        gateway = WebSocketGateway()
        latencies = []
        
        # Connect 100 clients
        clients = [await create_test_client() for _ in range(100)]
        
        # Send 100 messages per client
        for client in clients:
            for _ in range(100):
                start = time.now()
                response = await client.send_and_wait("ping")
                latency = time.now() - start
                latencies.append(latency)
        
        # Calculate p99
        p99_latency = percentile(latencies, 99)
        assert p99_latency < 0.1  # 100ms
    
    @pytest.mark.asyncio
    async def test_reconnection_handling(self):
        """Clients reconnect automatically with backoff"""
        # TEST: Disconnected client reconnects
        gateway = WebSocketGateway()
        client = await create_test_client()
        
        # Force disconnect
        await gateway.disconnect(client.id)
        
        # Client should reconnect with exponential backoff
        reconnect_times = []
        for attempt in range(5):
            start = time.now()
            await client.wait_for_reconnection()
            reconnect_time = time.now() - start
            reconnect_times.append(reconnect_time)
        
        # Verify exponential backoff
        for i in range(1, len(reconnect_times)):
            assert reconnect_times[i] > reconnect_times[i-1] * 1.5
    
    @pytest.mark.asyncio
    async def test_rate_limiting(self):
        """Rate limiting prevents abuse"""
        # TEST: Client sending too fast gets throttled
        gateway = WebSocketGateway()
        client = await create_test_client()
        
        # Send 1000 messages rapidly
        responses = []
        for _ in range(1000):
            response = await client.send_no_wait("data")
            responses.append(response)
        
        # Should have rate limit errors
        rate_limit_errors = [r for r in responses if r.error == "RATE_LIMITED"]
        assert len(rate_limit_errors) > 0
        
        # But not all should be errors
        assert len(rate_limit_errors) < 900  # Some should succeed
```

### 3. Lightweight Agent Tests

```python
# Resource Constraint Tests
class TestLightweightAgent:
    
    def test_memory_usage(self):
        """Agent uses less than 50MB RAM"""
        # TEST: Memory stays under limit during operation
        agent = LightweightAgent()
        agent.start()
        
        # Run for 60 seconds with monitoring
        memory_samples = []
        for _ in range(60):
            time.sleep(1)
            memory = get_agent_memory_usage()
            memory_samples.append(memory)
        
        # Check all samples
        assert max(memory_samples) < 50  # MB
        assert statistics.mean(memory_samples) < 40  # MB average
    
    def test_cpu_usage(self):
        """Agent uses less than 1% CPU average"""
        # TEST: CPU usage minimal during normal operation
        agent = LightweightAgent()
        agent.start()
        
        # Monitor CPU for 60 seconds
        cpu_samples = []
        for _ in range(60):
            time.sleep(1)
            cpu = get_agent_cpu_usage()
            cpu_samples.append(cpu)
        
        assert statistics.mean(cpu_samples) < 1.0  # 1% average
        assert max(cpu_samples) < 5.0  # 5% peak
    
    def test_network_bandwidth(self):
        """Agent uses less than 1KB/s average bandwidth"""
        # TEST: Network usage minimal
        agent = LightweightAgent()
        agent.start()
        
        # Monitor network for 60 seconds
        start_bytes = get_network_bytes()
        time.sleep(60)
        end_bytes = get_network_bytes()
        
        bandwidth = (end_bytes - start_bytes) / 60  # bytes/sec
        assert bandwidth < 1024  # 1KB/s
    
    def test_offline_queuing(self):
        """Agent queues data when offline"""
        # TEST: No data loss during disconnection
        agent = LightweightAgent()
        agent.start()
        
        # Generate events while online
        online_events = []
        for i in range(10):
            event = agent.generate_telemetry()
            online_events.append(event)
            time.sleep(1)
        
        # Disconnect network
        disable_network()
        
        # Generate events while offline
        offline_events = []
        for i in range(10):
            event = agent.generate_telemetry()
            offline_events.append(event)
            time.sleep(1)
        
        # Reconnect
        enable_network()
        time.sleep(5)  # Allow sync
        
        # Verify all events delivered
        server_events = get_server_received_events()
        assert len(server_events) == 20
```

### 4. Teleoperation Detection Tests

```python
# Teleoperation Detection Accuracy Tests
class TestTeleoperationDetection:
    
    def test_active_teleoperation_detected(self):
        """Active teleoperation detected within 1 second"""
        # TEST: Real teleoperation triggers detection
        robot = MockRobot()
        detector = TeleoperationDetector(robot)
        
        # Start teleoperation
        robot.start_teleoperation()
        
        # Should detect within 1 second
        start_time = time.now()
        while not detector.is_teleoperated():
            if time.now() - start_time > 1:
                pytest.fail("Detection took too long")
            time.sleep(0.1)
        
        assert detector.is_teleoperated()
    
    def test_no_false_positives_from_service(self):
        """Service running but not active doesn't trigger"""
        # TEST: Service state alone doesn't indicate teleoperation
        robot = MockRobot()
        detector = TeleoperationDetector(robot)
        
        # Start service but no actual teleoperation
        robot.start_service("teleop")
        time.sleep(2)
        
        assert not detector.is_teleoperated()
    
    def test_multiple_indicators_weighted(self):
        """Multiple indicators properly weighted"""
        # TEST: Scoring algorithm works correctly
        detector = TeleoperationDetector()
        
        # Test various combinations
        test_cases = [
            # (joy_cmds, video, webrtc, latency) -> expected
            (0, 0, 0, 0, False),  # Nothing active
            (10, 0, 0, 0, True),   # Joy commands alone sufficient
            (0, 1, 1, 30, True),   # Video + WebRTC sufficient
            (3, 0, 0, 100, False), # Some activity but not enough
            (5, 1, 1, 30, True),   # Everything active
        ]
        
        for joy, video, rtc, latency, expected in test_cases:
            score = detector.calculate_score(joy, video, rtc, latency)
            detected = score > detector.threshold
            assert detected == expected, f"Failed for inputs {joy},{video},{rtc},{latency}"
```

### 5. Discovery Service Tests

```python
# Discovery Performance Tests
class TestDiscoveryService:
    
    def test_discovery_speed(self):
        """All robots discovered in < 5 seconds"""
        # TEST: Fast discovery of entire network
        discovery = DiscoveryService()
        
        # Add 50 mock robots to network
        mock_robots = [MockRobot(f"192.168.88.{i}") for i in range(1, 51)]
        
        # Start discovery
        start_time = time.now()
        discovered = discovery.discover()
        discovery_time = time.now() - start_time
        
        assert discovery_time < 5  # seconds
        assert len(discovered) == 50
    
    def test_parallel_discovery_methods(self):
        """All discovery methods run in parallel"""
        # TEST: Methods don't block each other
        discovery = DiscoveryService()
        
        # Track method execution times
        method_times = {}
        
        with patch_discovery_methods(method_times):
            discovery.discover()
        
        # All methods should start within 100ms
        start_times = [t['start'] for t in method_times.values()]
        assert max(start_times) - min(start_times) < 0.1
    
    def test_robot_type_detection(self):
        """Robot types correctly identified"""
        # TEST: LeKiwi vs XLERobot detection accurate
        discovery = DiscoveryService()
        
        # Create mixed robot types
        robots = [
            MockRobot("192.168.88.1", type="lekiwi"),
            MockRobot("192.168.88.2", type="xlerobot"),
            MockRobot("192.168.88.3", type="lekiwi-lite"),
        ]
        
        discovered = discovery.discover()
        
        for robot in discovered:
            expected_type = next(r.type for r in robots if r.ip == robot.ip)
            assert robot.type == expected_type
```

### 6. Deployment Engine Tests

```python
# Deployment Reliability Tests
class TestDeploymentEngine:
    
    def test_differential_deployment(self):
        """Only changed files are deployed"""
        # TEST: Efficient delta deployment
        engine = DeploymentEngine()
        robot = MockRobot()
        
        # Initial deployment
        files_v1 = create_test_files(100)  # 100 files
        engine.deploy(robot, files_v1)
        
        # Change only 5 files
        files_v2 = files_v1.copy()
        for i in range(5):
            files_v2[f"file_{i}.txt"] = "modified content"
        
        # Deploy changes
        deployment = engine.deploy(robot, files_v2)
        
        assert deployment.files_transferred == 5
        assert deployment.bytes_transferred < 10000  # Small transfer
    
    def test_automatic_rollback(self):
        """Failed deployments trigger rollback"""
        # TEST: Rollback on failure threshold
        engine = DeploymentEngine()
        robots = [MockRobot(f"192.168.88.{i}") for i in range(1, 11)]
        
        # Make 3 robots fail deployment
        for i in range(3):
            robots[i].will_fail_deployment = True
        
        # Deploy to all robots
        result = engine.deploy_batch(robots, test_package)
        
        # Should rollback if < 80% success
        assert result.status == "rolled_back"
        assert result.success_rate == 0.7  # 70%
        
        # All robots should be at previous version
        for robot in robots:
            assert robot.version == robot.previous_version
    
    def test_deployment_speed(self):
        """Deployments complete in < 2 minutes"""
        # TEST: Fast parallel deployment
        engine = DeploymentEngine()
        robots = [MockRobot(f"192.168.88.{i}") for i in range(1, 101)]
        
        # Deploy 10MB package to 100 robots
        package = create_test_package(10 * 1024 * 1024)  # 10MB
        
        start_time = time.now()
        result = engine.deploy_batch(robots, package)
        deployment_time = time.now() - start_time
        
        assert deployment_time < 120  # 2 minutes
        assert result.success_rate > 0.95  # 95% success
```

## End-to-End Integration Tests

```python
class TestEndToEndScenarios:
    
    @pytest.mark.integration
    def test_complete_robot_lifecycle(self):
        """Robot discovery → registration → deployment → monitoring"""
        # TEST: Full lifecycle works end-to-end
        
        # Start all services
        services = start_all_services()
        
        # Add robot to network
        robot = MockRobot("192.168.88.100")
        robot.start()
        
        # Should be discovered
        wait_for_condition(lambda: robot.ip in services.discovery.robots, timeout=5)
        
        # Should register automatically
        wait_for_condition(lambda: robot.ip in services.state.registered_robots, timeout=10)
        
        # Should receive heartbeats
        time.sleep(35)  # Wait for heartbeat interval
        assert services.state.get_robot(robot.ip).last_heartbeat_age() < 5
        
        # Deploy update
        deployment = services.deployment.deploy(robot.ip, test_package)
        wait_for_condition(lambda: deployment.status == "completed", timeout=120)
        
        # Verify telemetry flowing
        telemetry = services.state.get_robot_telemetry(robot.ip)
        assert len(telemetry) > 0
    
    @pytest.mark.integration
    def test_network_partition_recovery(self):
        """System recovers from network partition"""
        # TEST: Resilience to network issues
        
        services = start_all_services()
        robots = [MockRobot(f"192.168.88.{i}") for i in range(1, 11)]
        
        # All robots connected
        for robot in robots:
            robot.start()
        time.sleep(5)
        
        # Simulate network partition
        partition_network(robots[:5])  # First 5 robots isolated
        
        # System should detect offline robots
        time.sleep(35)  # Heartbeat timeout
        for i in range(5):
            assert services.state.get_robot(robots[i].ip).status == "offline"
        
        # Other robots still online
        for i in range(5, 10):
            assert services.state.get_robot(robots[i].ip).status == "online"
        
        # Restore network
        restore_network(robots[:5])
        
        # Robots should reconnect
        time.sleep(10)
        for robot in robots:
            assert services.state.get_robot(robot.ip).status == "online"
```

## Performance Benchmarks

```python
# Performance Benchmark Suite
class PerformanceBenchmarks:
    
    def benchmark_state_queries(self):
        """State queries must return in < 10ms p99"""
        # TEST: Query performance at scale
        state_manager = create_state_manager_with_data(
            robots=1000,
            events_per_robot=1000
        )
        
        query_times = []
        for _ in range(10000):
            robot_id = random.choice(range(1000))
            start = time.perf_counter()
            state = state_manager.query_state(f"robot_{robot_id}")
            query_time = (time.perf_counter() - start) * 1000  # ms
            query_times.append(query_time)
        
        p99 = percentile(query_times, 99)
        assert p99 < 10  # ms
    
    def benchmark_websocket_throughput(self):
        """WebSocket handles 100K messages/sec"""
        # TEST: Message throughput at scale
        gateway = WebSocketGateway()
        
        # Connect 1000 clients
        clients = [create_test_client() for _ in range(1000)]
        
        # Each sends 100 msgs/sec for 1 second
        start = time.now()
        messages_sent = 0
        
        while time.now() - start < 1.0:
            for client in clients:
                client.send_async("test_message")
                messages_sent += 1
        
        assert messages_sent >= 100000
    
    def benchmark_discovery_at_scale(self):
        """Discovery scales to 1000 robots"""
        # TEST: Discovery performance with large fleet
        discovery = DiscoveryService()
        
        # Simulate 1000 robots
        for i in range(1000):
            add_mock_mdns_service(f"robot_{i}")
        
        start = time.now()
        discovered = discovery.discover()
        discovery_time = time.now() - start
        
        assert len(discovered) == 1000
        assert discovery_time < 10  # seconds
```

## Continuous Validation

### CI/CD Pipeline Tests

```yaml
# .github/workflows/continuous-validation.yml
name: Continuous Validation

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        module: [state-manager, websocket-gateway, agent, discovery, deployment]
    steps:
      - uses: actions/checkout@v2
      - name: Run Unit Tests
        run: |
          pytest tests/unit/${{ matrix.module }} -v --cov --cov-report=xml
      - name: Check Coverage
        run: |
          coverage report --fail-under=80

  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Start Services
        run: docker-compose up -d
      - name: Run Integration Tests
        run: |
          pytest tests/integration -v --timeout=300
      - name: Check Service Health
        run: |
          ./scripts/health_check.sh

  performance-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Performance Benchmarks
        run: |
          pytest tests/performance -v --benchmark-only
      - name: Compare to Baseline
        run: |
          python scripts/compare_benchmarks.py --fail-if-slower

  resource-tests:
    runs-on: [self-hosted, raspberry-pi]
    steps:
      - uses: actions/checkout@v2
      - name: Test Agent Resources
        run: |
          ./tests/resources/test_agent_resources.sh
      - name: Verify Constraints
        run: |
          python scripts/verify_resource_constraints.py
```

### Production Validation

```python
# Production Health Checks
class ProductionValidation:
    
    def validate_deployment_health(self):
        """Continuous health validation in production"""
        checks = [
            ("discovery_time", lambda: get_metric("discovery.p99") < 5),
            ("agent_memory", lambda: get_metric("agent.memory.max") < 50),
            ("websocket_latency", lambda: get_metric("websocket.p99") < 100),
            ("deployment_success", lambda: get_metric("deployment.success_rate") > 0.95),
            ("error_rate", lambda: get_metric("api.error_rate") < 0.001),
        ]
        
        failed_checks = []
        for name, check in checks:
            if not check():
                failed_checks.append(name)
        
        if failed_checks:
            trigger_alert(f"Production validation failed: {failed_checks}")
            if len(failed_checks) > 2:
                initiate_rollback()
```

## Rollback Triggers

```python
# Automatic Rollback Conditions
ROLLBACK_TRIGGERS = {
    "high_error_rate": {
        "condition": lambda: get_metric("error_rate") > 0.05,
        "threshold_duration": 60,  # seconds
        "action": "immediate_rollback"
    },
    "memory_exceeded": {
        "condition": lambda: get_metric("agent.memory") > 75,  # MB
        "threshold_duration": 300,  # 5 minutes
        "action": "gradual_rollback"
    },
    "deployment_failures": {
        "condition": lambda: get_metric("deployment.success_rate") < 0.8,
        "threshold_duration": 0,  # immediate
        "action": "pause_and_investigate"
    },
    "websocket_degradation": {
        "condition": lambda: get_metric("websocket.p99") > 500,  # ms
        "threshold_duration": 120,  # 2 minutes
        "action": "switch_to_polling"
    }
}

def monitor_rollback_triggers():
    """Continuously monitor for rollback conditions"""
    while True:
        for trigger_name, config in ROLLBACK_TRIGGERS.items():
            if config["condition"]():
                # Start timing the condition
                if trigger_name not in violation_timers:
                    violation_timers[trigger_name] = time.now()
                
                # Check if threshold duration exceeded
                duration = time.now() - violation_timers[trigger_name]
                if duration > config["threshold_duration"]:
                    execute_rollback_action(config["action"])
                    alert_team(f"Rollback triggered: {trigger_name}")
            else:
                # Condition cleared
                violation_timers.pop(trigger_name, None)
        
        time.sleep(10)  # Check every 10 seconds
```

## Test Data Generation

```python
# Test Data Generators
class TestDataFactory:
    
    @staticmethod
    def create_robot_fleet(size=100):
        """Generate realistic robot fleet"""
        robots = []
        for i in range(size):
            robot_type = random.choice(["lekiwi", "xlerobot", "lekiwi-lite"])
            robot = {
                "id": f"robot_{i}",
                "ip": f"192.168.88.{i+1}",
                "mac": generate_mac_address(),
                "type": robot_type,
                "version": random.choice(["0.01", "0.02", "0.03"]),
                "status": random.choice(["online", "offline", "deploying"]),
                "teleoperated": random.random() < 0.1,  # 10% teleoperated
            }
            robots.append(robot)
        return robots
    
    @staticmethod
    def create_deployment_package(size_mb=10):
        """Generate deployment package for testing"""
        return {
            "version": f"1.{random.randint(0,99)}.{random.randint(0,999)}",
            "files": {
                f"file_{i}.py": generate_random_content(1024)
                for i in range(size_mb)
            },
            "checksums": {
                f"file_{i}.py": hashlib.sha256(content).hexdigest()
                for i, content in files.items()
            }
        }
```

## Validation Summary

This comprehensive testing strategy ensures:

1. **Every module has complete test coverage** (>80%)
2. **Performance requirements are continuously validated**
3. **Resource constraints are enforced** (50MB agent, <1% CPU)
4. **Automatic rollback on failures**
5. **End-to-end scenarios are tested**
6. **Production health is continuously monitored**

The test-driven approach with clear anchors ensures quality while the automated validation provides confidence for rapid deployment and iteration.