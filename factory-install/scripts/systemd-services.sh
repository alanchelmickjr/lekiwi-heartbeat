#!/bin/bash
# SystemD Service Definitions Generator for Lekiwi/XLE Robots
# Creates all necessary service files with proper dependencies and resource limits

set -e

SERVICES_DIR="/etc/systemd/system"
AGENT_BIN="/usr/local/bin/lekiwi-agent"
STATE_DIR="/var/lib/lekiwi-agent"
CONFIG_DIR="/etc/lekiwi"

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# Main monitoring agent service
create_agent_service() {
    log_info "Creating lekiwi-agent.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-agent.service <<'EOF'
[Unit]
Description=Lekiwi Robot Monitoring Agent
Documentation=https://docs.lekiwi.io/agent
After=network-online.target time-sync.target
Wants=network-online.target time-sync.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
ExecStartPre=/usr/local/bin/lekiwi-agent-check.sh
ExecStart=/usr/local/bin/lekiwi-agent \
    --robot-id ${ROBOT_ID} \
    --server ${CONTROL_SERVER} \
    --port 8080 \
    --mtls ${ENABLE_MTLS} \
    --cert-path ${CONFIG_DIR}/certs
ExecReload=/bin/kill -HUP $MAINPID
Restart=always
RestartSec=10
TimeoutStopSec=10

# User and permissions
User=lekiwi-agent
Group=lekiwi-agent
UMask=0077

# Resource limits
MemoryMax=50M
MemorySwapMax=0
CPUQuota=10%
TasksMax=20
IOWeight=10

# Security hardening
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
LockPersonality=yes
NoNewPrivileges=yes
PrivateDevices=yes
DevicePolicy=closed
DeviceAllow=/dev/i2c-1 rw
DeviceAllow=/dev/gpiomem rw
ReadWritePaths=/var/lib/lekiwi-agent
ReadOnlyPaths=/etc/lekiwi
RuntimeDirectory=lekiwi-agent
RuntimeDirectoryMode=0700
StateDirectory=lekiwi-agent
StateDirectoryMode=0700
LogsDirectory=lekiwi-agent
LogsDirectoryMode=0700

# Environment
EnvironmentFile=-/etc/lekiwi/agent.env
Environment="RUST_LOG=info"
Environment="ROBOT_ID=%i"

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lekiwi-agent

[Install]
WantedBy=multi-user.target
Alias=robot-agent.service
EOF
}

# Hardware detection service (runs once at boot)
create_hardware_detection_service() {
    log_info "Creating lekiwi-hardware-detect.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-hardware-detect.service <<'EOF'
[Unit]
Description=Lekiwi Robot Hardware Detection
Documentation=https://docs.lekiwi.io/hardware
Before=lekiwi-agent.service
After=sysinit.target
ConditionPathExists=!/etc/lekiwi/hardware.conf
DefaultDependencies=no

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/detect-hardware.sh
StandardOutput=journal
StandardError=journal
TimeoutSec=30

# Run as root for hardware access
User=root
Group=root

# Security (limited since we need hardware access)
PrivateTmp=yes
ProtectHome=yes
NoNewPrivileges=yes
ReadWritePaths=/etc/lekiwi

[Install]
WantedBy=sysinit.target
EOF
}

# Agent health monitor (watchdog)
create_watchdog_service() {
    log_info "Creating lekiwi-watchdog.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-watchdog.service <<'EOF'
[Unit]
Description=Lekiwi Agent Health Monitor
After=lekiwi-agent.service
Requires=lekiwi-agent.service
PartOf=lekiwi-agent.service

[Service]
Type=simple
ExecStart=/usr/local/bin/lekiwi-watchdog.sh
Restart=always
RestartSec=30

# Minimal resources
MemoryMax=10M
CPUQuota=5%

# User
User=lekiwi-agent
Group=lekiwi-agent

# Security
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
ReadOnlyPaths=/var/lib/lekiwi-agent

[Install]
WantedBy=lekiwi-agent.service
EOF
}

# Telemetry collector timer (periodic tasks)
create_telemetry_timer() {
    log_info "Creating lekiwi-telemetry.timer..."
    
    # Timer unit
    cat > ${SERVICES_DIR}/lekiwi-telemetry.timer <<'EOF'
[Unit]
Description=Lekiwi Telemetry Collection Timer
Documentation=https://docs.lekiwi.io/telemetry
Requires=lekiwi-agent.service

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min
AccuracySec=1min
Persistent=true

[Install]
WantedBy=timers.target
EOF

    # Service unit
    cat > ${SERVICES_DIR}/lekiwi-telemetry.service <<'EOF'
[Unit]
Description=Lekiwi Telemetry Collection
After=lekiwi-agent.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/collect-telemetry.sh
User=lekiwi-agent
Group=lekiwi-agent

# Resource limits
MemoryMax=20M
CPUQuota=10%
TimeoutSec=30

# Security
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
ReadWritePaths=/var/lib/lekiwi-agent/telemetry
EOF
}

# Update checker service
create_update_service() {
    log_info "Creating lekiwi-update.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-update.service <<'EOF'
[Unit]
Description=Lekiwi Agent Auto-Update Service
Documentation=https://docs.lekiwi.io/updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/lekiwi-update.sh
User=root
Group=root
StandardOutput=journal
StandardError=journal

# Security (needs root for updates)
PrivateTmp=yes
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

[Install]
WantedBy=multi-user.target
EOF

    # Update timer
    cat > ${SERVICES_DIR}/lekiwi-update.timer <<'EOF'
[Unit]
Description=Lekiwi Agent Auto-Update Timer
Requires=network-online.target

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
EOF
}

# Emergency recovery service
create_recovery_service() {
    log_info "Creating lekiwi-recovery.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-recovery.service <<'EOF'
[Unit]
Description=Lekiwi Emergency Recovery Service
Documentation=https://docs.lekiwi.io/recovery
DefaultDependencies=no
Conflicts=shutdown.target
Before=shutdown.target
OnFailure=lekiwi-factory-reset.service

[Service]
Type=simple
ExecStart=/usr/local/bin/lekiwi-recovery.sh
ExecStop=/usr/local/bin/lekiwi-recovery-stop.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

# Run as root for system recovery
User=root
Group=root

# Minimal dependencies for recovery mode
TimeoutSec=300

[Install]
WantedBy=rescue.target
EOF
}

# Factory reset service
create_factory_reset_service() {
    log_info "Creating lekiwi-factory-reset.service..."
    
    cat > ${SERVICES_DIR}/lekiwi-factory-reset.service <<'EOF'
[Unit]
Description=Lekiwi Factory Reset Service
Documentation=https://docs.lekiwi.io/factory-reset
DefaultDependencies=no
ConditionPathExists=/tmp/factory-reset-trigger

[Service]
Type=oneshot
ExecStart=/usr/local/bin/factory-reset.sh
StandardOutput=journal
StandardError=journal
TimeoutSec=600

# Must run as root
User=root
Group=root

# No security restrictions for factory reset
RemainAfterExit=yes
EOF
}

# Create supporting scripts
create_support_scripts() {
    log_info "Creating support scripts..."
    
    # Agent check script
    cat > /usr/local/bin/lekiwi-agent-check.sh <<'EOF'
#!/bin/bash
# Pre-flight checks for agent startup

# Check network connectivity
if ! ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
    echo "Warning: No network connectivity detected"
fi

# Check state directory
if [ ! -d /var/lib/lekiwi-agent ]; then
    mkdir -p /var/lib/lekiwi-agent
    chown lekiwi-agent:lekiwi-agent /var/lib/lekiwi-agent
fi

# Check configuration
if [ ! -f /etc/lekiwi/agent.env ]; then
    echo "Creating default configuration..."
    mkdir -p /etc/lekiwi
    cat > /etc/lekiwi/agent.env <<CONFIG
CONTROL_SERVER=https://control.lekiwi.io:8443
ENABLE_MTLS=false
ROBOT_ID=$(cat /proc/sys/kernel/random/uuid)
CONFIG
fi

# Load robot type
if [ -f /etc/robot.conf ]; then
    source /etc/robot.conf
else
    echo "Warning: Robot configuration not found"
fi

exit 0
EOF
    chmod +x /usr/local/bin/lekiwi-agent-check.sh
    
    # Watchdog script
    cat > /usr/local/bin/lekiwi-watchdog.sh <<'EOF'
#!/bin/bash
# Monitor agent health and restart if needed

AGENT_URL="http://localhost:8080/health"
MAX_FAILURES=3
failures=0

while true; do
    if curl -sf ${AGENT_URL} >/dev/null 2>&1; then
        failures=0
        echo "Agent healthy"
    else
        ((failures++))
        echo "Agent check failed (${failures}/${MAX_FAILURES})"
        
        if [ ${failures} -ge ${MAX_FAILURES} ]; then
            echo "Restarting agent service..."
            systemctl restart lekiwi-agent.service
            failures=0
            sleep 30
        fi
    fi
    sleep 10
done
EOF
    chmod +x /usr/local/bin/lekiwi-watchdog.sh
    
    # Telemetry collection script
    cat > /usr/local/bin/collect-telemetry.sh <<'EOF'
#!/bin/bash
# Collect and store telemetry data

TELEMETRY_DIR="/var/lib/lekiwi-agent/telemetry"
mkdir -p ${TELEMETRY_DIR}

# Collect system metrics
cat > ${TELEMETRY_DIR}/metrics.json <<METRICS
{
    "timestamp": "$(date -Iseconds)",
    "load_average": $(cat /proc/loadavg | awk '{print "["$1","$2","$3"]"}'),
    "memory_free_kb": $(grep MemFree /proc/meminfo | awk '{print $2}'),
    "disk_usage_percent": $(df / | tail -1 | awk '{print $5}' | tr -d '%'),
    "process_count": $(ps aux | wc -l),
    "network_connections": $(ss -tan | grep ESTAB | wc -l)
}
METRICS

echo "Telemetry collected"
EOF
    chmod +x /usr/local/bin/collect-telemetry.sh
    
    # Update script
    cat > /usr/local/bin/lekiwi-update.sh <<'EOF'
#!/bin/bash
# Auto-update agent if new version available

CURRENT_VERSION=$(/usr/local/bin/lekiwi-agent --version 2>/dev/null | awk '{print $2}')
LATEST_VERSION=$(curl -sf https://releases.lekiwi.io/agent/latest/version.txt)

if [ -z "${LATEST_VERSION}" ]; then
    echo "Failed to check for updates"
    exit 1
fi

if [ "${CURRENT_VERSION}" != "${LATEST_VERSION}" ]; then
    echo "Updating agent from ${CURRENT_VERSION} to ${LATEST_VERSION}"
    
    # Download new version
    curl -sSL "https://releases.lekiwi.io/agent/v${LATEST_VERSION}/lekiwi-agent-arm64" \
        -o /tmp/lekiwi-agent-new
    
    if [ $? -eq 0 ]; then
        # Backup current version
        cp /usr/local/bin/lekiwi-agent /usr/local/bin/lekiwi-agent.bak
        
        # Install new version
        mv /tmp/lekiwi-agent-new /usr/local/bin/lekiwi-agent
        chmod +x /usr/local/bin/lekiwi-agent
        
        # Restart service
        systemctl restart lekiwi-agent.service
        echo "Update complete"
    else
        echo "Update failed"
        exit 1
    fi
else
    echo "Agent is up to date (${CURRENT_VERSION})"
fi
EOF
    chmod +x /usr/local/bin/lekiwi-update.sh
}

# Create user and group
create_user() {
    log_info "Creating lekiwi-agent user..."
    
    if ! id -u lekiwi-agent &>/dev/null; then
        useradd -r -s /bin/false -d /var/lib/lekiwi-agent -m lekiwi-agent
        usermod -a -G i2c,gpio,video lekiwi-agent
    fi
    
    # Create directories
    mkdir -p /var/lib/lekiwi-agent
    mkdir -p /etc/lekiwi/certs
    mkdir -p /var/log/lekiwi-agent
    
    # Set permissions
    chown -R lekiwi-agent:lekiwi-agent /var/lib/lekiwi-agent
    chown -R lekiwi-agent:lekiwi-agent /var/log/lekiwi-agent
    chmod 700 /var/lib/lekiwi-agent
    chmod 755 /etc/lekiwi
}

# Main installation
main() {
    log_info "Installing systemd services..."
    
    create_user
    create_agent_service
    create_hardware_detection_service
    create_watchdog_service
    create_telemetry_timer
    create_update_service
    create_recovery_service
    create_factory_reset_service
    create_support_scripts
    
    # Reload systemd
    systemctl daemon-reload
    
    # Enable essential services
    systemctl enable lekiwi-hardware-detect.service
    systemctl enable lekiwi-agent.service
    systemctl enable lekiwi-telemetry.timer
    systemctl enable lekiwi-update.timer
    
    log_info "Systemd services installed successfully!"
    log_info "Start with: systemctl start lekiwi-agent.service"
}

# Run if executed directly
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi