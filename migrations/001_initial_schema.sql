-- Initial schema for robot state management with event sourcing
-- Supports both Lekiwi and XLE robots

-- Create enum types for robot states and event types
CREATE TYPE robot_state_enum AS ENUM (
    'discovered',
    'provisioning', 
    'ready',
    'active',
    'maintenance',
    'offline',
    'failed'
);

CREATE TYPE robot_type_enum AS ENUM (
    'lekiwi',
    'xlerobot',
    'unknown'
);

CREATE TYPE event_type_enum AS ENUM (
    'robot_discovered',
    'robot_provisioned',
    'robot_activated',
    'robot_deactivated',
    'robot_failed',
    'robot_recovered',
    'robot_maintenance_start',
    'robot_maintenance_end',
    'robot_heartbeat',
    'robot_config_changed',
    'deployment_started',
    'deployment_completed',
    'deployment_failed'
);

-- Event store table (append-only)
CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    event_id UUID UNIQUE NOT NULL DEFAULT gen_random_uuid(),
    event_type event_type_enum NOT NULL,
    aggregate_id UUID NOT NULL, -- Robot ID
    aggregate_type VARCHAR(50) NOT NULL DEFAULT 'robot',
    event_data JSONB NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(255),
    
    -- Indexes for fast queries
    INDEX idx_events_aggregate_id (aggregate_id),
    INDEX idx_events_event_type (event_type),
    INDEX idx_events_created_at (created_at DESC),
    INDEX idx_events_aggregate_type (aggregate_type)
);

-- Current robot state (read model - CQRS pattern)
CREATE TABLE IF NOT EXISTS robot_states (
    robot_id UUID PRIMARY KEY,
    ip_address INET NOT NULL UNIQUE,
    hostname VARCHAR(255),
    robot_type robot_type_enum NOT NULL DEFAULT 'unknown',
    state robot_state_enum NOT NULL DEFAULT 'discovered',
    
    -- Robot details
    model VARCHAR(255),
    firmware_version VARCHAR(50),
    deployment_version VARCHAR(50),
    
    -- State tracking
    last_heartbeat TIMESTAMP WITH TIME ZONE,
    last_state_change TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    failure_count INTEGER DEFAULT 0,
    
    -- Configuration
    config JSONB DEFAULT '{}',
    capabilities JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    -- Timestamps
    discovered_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    provisioned_at TIMESTAMP WITH TIME ZONE,
    activated_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- Indexes
    INDEX idx_robot_states_state (state),
    INDEX idx_robot_states_type (robot_type),
    INDEX idx_robot_states_last_heartbeat (last_heartbeat DESC),
    INDEX idx_robot_states_ip_address (ip_address)
);

-- Discovery sessions table
CREATE TABLE IF NOT EXISTS discovery_sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    discovered_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    duration_ms INTEGER,
    network_range VARCHAR(50),
    discovery_method VARCHAR(50) DEFAULT 'websocket',
    metadata JSONB DEFAULT '{}',
    
    INDEX idx_discovery_sessions_started_at (started_at DESC)
);

-- Robot discovery results (temporary staging)
CREATE TABLE IF NOT EXISTS discovery_results (
    id SERIAL PRIMARY KEY,
    session_id UUID REFERENCES discovery_sessions(session_id) ON DELETE CASCADE,
    ip_address INET NOT NULL,
    hostname VARCHAR(255),
    robot_type VARCHAR(50),
    ssh_banner TEXT,
    model VARCHAR(255),
    discovered_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    response_time_ms INTEGER,
    metadata JSONB DEFAULT '{}',
    
    INDEX idx_discovery_results_session_id (session_id),
    INDEX idx_discovery_results_ip_address (ip_address),
    UNIQUE(session_id, ip_address)
);

-- Circuit breaker state for each robot
CREATE TABLE IF NOT EXISTS circuit_breakers (
    robot_id UUID PRIMARY KEY REFERENCES robot_states(robot_id) ON DELETE CASCADE,
    state VARCHAR(20) NOT NULL DEFAULT 'closed', -- closed, open, half_open
    failure_count INTEGER DEFAULT 0,
    last_failure_at TIMESTAMP WITH TIME ZONE,
    last_success_at TIMESTAMP WITH TIME ZONE,
    next_retry_at TIMESTAMP WITH TIME ZONE,
    consecutive_successes INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_circuit_breakers_state (state),
    INDEX idx_circuit_breakers_next_retry_at (next_retry_at)
);

-- Deployment history
CREATE TABLE IF NOT EXISTS deployment_history (
    deployment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    robot_id UUID REFERENCES robot_states(robot_id) ON DELETE CASCADE,
    version VARCHAR(50) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    rollback_from UUID REFERENCES deployment_history(deployment_id),
    metadata JSONB DEFAULT '{}',
    
    INDEX idx_deployment_history_robot_id (robot_id),
    INDEX idx_deployment_history_status (status),
    INDEX idx_deployment_history_started_at (started_at DESC)
);

-- Metrics table for monitoring
CREATE TABLE IF NOT EXISTS metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(255) NOT NULL,
    metric_value NUMERIC,
    tags JSONB DEFAULT '{}',
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_metrics_name_timestamp (metric_name, timestamp DESC),
    INDEX idx_metrics_timestamp (timestamp DESC)
);

-- Create update trigger for robot_states
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_robot_states_updated_at BEFORE UPDATE
    ON robot_states FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_circuit_breakers_updated_at BEFORE UPDATE
    ON circuit_breakers FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Create function to get robot state at specific time
CREATE OR REPLACE FUNCTION get_robot_state_at_time(
    p_robot_id UUID,
    p_timestamp TIMESTAMP WITH TIME ZONE
)
RETURNS TABLE (
    robot_id UUID,
    state robot_state_enum,
    event_data JSONB
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.aggregate_id as robot_id,
        CASE 
            WHEN e.event_type IN ('robot_discovered') THEN 'discovered'::robot_state_enum
            WHEN e.event_type IN ('robot_provisioned') THEN 'provisioning'::robot_state_enum
            WHEN e.event_type IN ('robot_activated') THEN 'active'::robot_state_enum
            WHEN e.event_type IN ('robot_failed') THEN 'failed'::robot_state_enum
            WHEN e.event_type IN ('robot_maintenance_start') THEN 'maintenance'::robot_state_enum
            ELSE 'offline'::robot_state_enum
        END as state,
        e.event_data
    FROM events e
    WHERE e.aggregate_id = p_robot_id
      AND e.created_at <= p_timestamp
    ORDER BY e.created_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Add comments for documentation
COMMENT ON TABLE events IS 'Event store for event sourcing - append only';
COMMENT ON TABLE robot_states IS 'Current robot state - read model (CQRS)';
COMMENT ON TABLE discovery_sessions IS 'Track discovery session performance';
COMMENT ON TABLE circuit_breakers IS 'Circuit breaker state for each robot';
COMMENT ON TABLE deployment_history IS 'Deployment history and status';
COMMENT ON TABLE metrics IS 'Performance and monitoring metrics';