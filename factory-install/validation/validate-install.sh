#!/bin/bash
# Validation and Testing Procedures for Lekiwi/XLE Robot Factory Install
# Comprehensive test suite to validate installation and functionality

set -e

# Configuration
TEST_RESULTS_DIR="/var/log/lekiwi-tests"
TEST_REPORT="${TEST_RESULTS_DIR}/validation-report-$(date +%Y%m%d-%H%M%S).txt"
CONTROL_SERVER="https://control.lekiwi.io:8443"
AGENT_PORT="8080"
MAX_MEMORY_MB="50"
MIN_DISK_GB="4"
REQUIRED_SERVICES=("lekiwi-agent" "ssh" "systemd-networkd")

# Test counters
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0
TESTS_SKIPPED=0

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Initialize
mkdir -p ${TEST_RESULTS_DIR}
exec > >(tee -a ${TEST_REPORT})
exec 2>&1

# Test framework functions
test_start() {
    local test_name="$1"
    echo ""
    echo -e "${CYAN}[TEST]${NC} ${test_name}"
    echo "======================================"
    TESTS_TOTAL=$((TESTS_TOTAL + 1))
}

test_pass() {
    local message="${1:-Test passed}"
    echo -e "${GREEN}[PASS]${NC} ${message}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
}

test_fail() {
    local message="${1:-Test failed}"
    echo -e "${RED}[FAIL]${NC} ${message}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

test_skip() {
    local message="${1:-Test skipped}"
    echo -e "${YELLOW}[SKIP]${NC} ${message}"
    TESTS_SKIPPED=$((TESTS_SKIPPED + 1))
}

test_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

# Pre-installation validation
validate_prerequisites() {
    test_start "Prerequisites Validation"
    
    # Check if running on Raspberry Pi
    if [ -f /proc/device-tree/model ]; then
        local model=$(tr -d '\0' < /proc/device-tree/model)
        if [[ "$model" == *"Raspberry Pi"* ]]; then
            test_pass "Running on Raspberry Pi: ${model}"
        else
            test_fail "Not running on Raspberry Pi: ${model}"
        fi
    else
        test_fail "Cannot detect Raspberry Pi model"
    fi
    
    # Check kernel version
    local kernel=$(uname -r)
    test_info "Kernel version: ${kernel}"
    if [[ "$kernel" == *"rpi"* ]] || [[ "$kernel" == *"raspi"* ]]; then
        test_pass "Raspberry Pi kernel detected"
    else
        test_fail "Non-Raspberry Pi kernel: ${kernel}"
    fi
    
    # Check architecture
    local arch=$(uname -m)
    if [[ "$arch" == "aarch64" ]] || [[ "$arch" == "armv7l" ]]; then
        test_pass "ARM architecture: ${arch}"
    else
        test_fail "Unsupported architecture: ${arch}"
    fi
}

# System resources validation
validate_system_resources() {
    test_start "System Resources Validation"
    
    # Check memory
    local total_mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    local total_mem_mb=$((total_mem_kb / 1024))
    test_info "Total memory: ${total_mem_mb}MB"
    
    if [ ${total_mem_mb} -ge 512 ]; then
        test_pass "Sufficient memory available"
    else
        test_fail "Insufficient memory: ${total_mem_mb}MB (minimum 512MB)"
    fi
    
    # Check disk space
    local disk_free_gb=$(df / | tail -1 | awk '{print int($4/1024/1024)}')
    test_info "Free disk space: ${disk_free_gb}GB"
    
    if [ ${disk_free_gb} -ge ${MIN_DISK_GB} ]; then
        test_pass "Sufficient disk space available"
    else
        test_fail "Insufficient disk space: ${disk_free_gb}GB (minimum ${MIN_DISK_GB}GB)"
    fi
    
    # Check CPU cores
    local cpu_cores=$(nproc)
    test_info "CPU cores: ${cpu_cores}"
    
    if [ ${cpu_cores} -ge 2 ]; then
        test_pass "Sufficient CPU cores"
    else
        test_warn "Low CPU core count: ${cpu_cores}"
    fi
}

# Hardware detection validation
validate_hardware_detection() {
    test_start "Hardware Detection Validation"
    
    # Check if hardware detection was run
    if [ -f /etc/lekiwi/hardware.conf ]; then
        test_pass "Hardware configuration file exists"
        source /etc/lekiwi/hardware.conf
        
        # Validate robot type detection
        case "${ROBOT_TYPE}" in
            lekiwi)
                test_pass "Robot type: Lekiwi"
                # Check for I2C servo controller
                if [[ "${I2C_DEVICES}" == *"PCA9685"* ]]; then
                    test_pass "PCA9685 servo controller detected"
                else
                    test_fail "PCA9685 servo controller not found"
                fi
                ;;
            xle)
                test_pass "Robot type: XLE"
                # Check for RealSense or arm controllers
                if [[ "${USB_DEVICES}" == *"RealSense"* ]] || [[ "${USB_DEVICES}" == *"Dynamixel"* ]]; then
                    test_pass "XLE hardware detected"
                else
                    test_fail "XLE hardware not found"
                fi
                ;;
            unknown)
                test_fail "Robot type unknown"
                ;;
            *)
                test_fail "Invalid robot type: ${ROBOT_TYPE}"
                ;;
        esac
        
        # Validate Raspberry Pi version
        if [ -n "${RASPBERRY_PI_VERSION}" ]; then
            test_pass "Raspberry Pi version: ${RASPBERRY_PI_VERSION}"
        else
            test_fail "Raspberry Pi version not detected"
        fi
    else
        test_fail "Hardware detection not completed"
    fi
}

# Network connectivity tests
validate_network() {
    test_start "Network Connectivity Validation"
    
    # Check network interfaces
    local interfaces=$(ip -o link show | awk -F': ' '{print $2}' | grep -v lo)
    test_info "Network interfaces: ${interfaces}"
    
    # Check for active network connection
    if ip route | grep -q default; then
        test_pass "Default route configured"
        
        # Test DNS resolution
        if nslookup google.com &>/dev/null; then
            test_pass "DNS resolution working"
        else
            test_fail "DNS resolution failed"
        fi
        
        # Test internet connectivity
        if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
            test_pass "Internet connectivity confirmed"
        else
            test_fail "No internet connectivity"
        fi
        
        # Test control server connectivity
        if curl -sf --max-time 5 ${CONTROL_SERVER}/health &>/dev/null; then
            test_pass "Control server reachable"
        else
            test_warn "Control server not reachable"
        fi
    else
        test_fail "No default route configured"
    fi
    
    # Check mDNS/Avahi
    if systemctl is-active --quiet avahi-daemon; then
        test_pass "Avahi daemon running"
        
        # Check hostname resolution
        local hostname=$(hostname -f)
        if avahi-resolve -n ${hostname}.local &>/dev/null; then
            test_pass "mDNS hostname resolution working"
        else
            test_warn "mDNS hostname resolution failed"
        fi
    else
        test_warn "Avahi daemon not running"
    fi
}

# Agent installation validation
validate_agent() {
    test_start "Monitoring Agent Validation"
    
    # Check if agent binary exists
    if [ -f /usr/local/bin/lekiwi-agent ]; then
        test_pass "Agent binary installed"
        
        # Check agent version
        if /usr/local/bin/lekiwi-agent --version &>/dev/null; then
            local version=$(/usr/local/bin/lekiwi-agent --version 2>&1 | head -1)
            test_pass "Agent version: ${version}"
        else
            test_fail "Cannot determine agent version"
        fi
    else
        test_fail "Agent binary not found"
    fi
    
    # Check agent service
    if systemctl list-unit-files | grep -q lekiwi-agent.service; then
        test_pass "Agent service installed"
        
        # Check if service is enabled
        if systemctl is-enabled --quiet lekiwi-agent.service; then
            test_pass "Agent service enabled"
        else
            test_fail "Agent service not enabled"
        fi
        
        # Check if service is running
        if systemctl is-active --quiet lekiwi-agent.service; then
            test_pass "Agent service running"
        else
            test_fail "Agent service not running"
            # Show recent logs
            journalctl -u lekiwi-agent.service --no-pager -n 10
        fi
    else
        test_fail "Agent service not installed"
    fi
    
    # Check agent API
    if curl -sf http://localhost:${AGENT_PORT}/health &>/dev/null; then
        test_pass "Agent API responding"
        
        # Check agent status endpoint
        local status=$(curl -sf http://localhost:${AGENT_PORT}/status)
        if [ -n "${status}" ]; then
            test_pass "Agent status endpoint working"
            test_info "Agent status: $(echo ${status} | jq -c '.system_info.robot_type' 2>/dev/null || echo 'parse error')"
        else
            test_fail "Agent status endpoint not responding"
        fi
    else
        test_fail "Agent API not responding"
    fi
    
    # Check memory usage
    if pidof lekiwi-agent &>/dev/null; then
        local agent_pid=$(pidof lekiwi-agent)
        local mem_usage=$(ps -o rss= -p ${agent_pid} | awk '{print int($1/1024)}')
        test_info "Agent memory usage: ${mem_usage}MB"
        
        if [ ${mem_usage} -le ${MAX_MEMORY_MB} ]; then
            test_pass "Agent memory usage within limits"
        else
            test_fail "Agent memory usage exceeds limit: ${mem_usage}MB > ${MAX_MEMORY_MB}MB"
        fi
    fi
}

# Security validation
validate_security() {
    test_start "Security Configuration Validation"
    
    # Check SSH configuration
    if [ -f /etc/ssh/sshd_config ]; then
        if grep -q "^PasswordAuthentication no" /etc/ssh/sshd_config; then
            test_pass "SSH password authentication disabled"
        else
            test_warn "SSH password authentication enabled"
        fi
        
        if grep -q "^PermitRootLogin no" /etc/ssh/sshd_config; then
            test_pass "SSH root login disabled"
        else
            test_warn "SSH root login enabled"
        fi
    else
        test_fail "SSH configuration not found"
    fi
    
    # Check firewall
    if command -v ufw &>/dev/null; then
        if ufw status | grep -q "Status: active"; then
            test_pass "Firewall enabled"
        else
            test_warn "Firewall not enabled"
        fi
    else
        test_info "UFW not installed"
    fi
    
    # Check certificate configuration
    if [ -f /etc/lekiwi/certs/client-cert.pem ]; then
        test_pass "Client certificate installed"
        
        # Verify certificate
        if openssl x509 -in /etc/lekiwi/certs/client-cert.pem -noout -checkend 86400; then
            test_pass "Client certificate valid"
        else
            test_fail "Client certificate expired or expiring soon"
        fi
    else
        test_warn "Client certificate not installed"
    fi
    
    # Check file permissions
    if [ -d /etc/lekiwi/keys ]; then
        local key_perms=$(stat -c %a /etc/lekiwi/keys)
        if [ "${key_perms}" = "700" ]; then
            test_pass "Key directory permissions correct"
        else
            test_fail "Key directory permissions incorrect: ${key_perms}"
        fi
    fi
}

# Performance tests
validate_performance() {
    test_start "Performance Validation"
    
    # Test boot time
    local boot_time=$(systemd-analyze | grep "Startup finished" | grep -oE '[0-9]+\.[0-9]+s' | tail -1)
    test_info "Boot time: ${boot_time}"
    
    # Test CPU performance
    test_info "Running CPU benchmark..."
    local cpu_start=$(date +%s%N)
    for i in {1..10000}; do
        echo $((i * i)) > /dev/null
    done
    local cpu_end=$(date +%s%N)
    local cpu_time=$(( (cpu_end - cpu_start) / 1000000 ))
    test_info "CPU benchmark time: ${cpu_time}ms"
    
    if [ ${cpu_time} -lt 1000 ]; then
        test_pass "CPU performance acceptable"
    else
        test_warn "CPU performance may be slow"
    fi
    
    # Test I/O performance
    test_info "Running I/O benchmark..."
    dd if=/dev/zero of=/tmp/testfile bs=1M count=100 &>/dev/null
    sync
    local io_start=$(date +%s%N)
    dd if=/tmp/testfile of=/dev/null bs=1M &>/dev/null
    local io_end=$(date +%s%N)
    local io_time=$(( (io_end - io_start) / 1000000 ))
    rm -f /tmp/testfile
    test_info "I/O read time: ${io_time}ms for 100MB"
    
    if [ ${io_time} -lt 5000 ]; then
        test_pass "I/O performance acceptable"
    else
        test_warn "I/O performance may be slow"
    fi
}

# Service validation
validate_services() {
    test_start "System Services Validation"
    
    for service in "${REQUIRED_SERVICES[@]}"; do
        if systemctl list-unit-files | grep -q "${service}"; then
            if systemctl is-active --quiet ${service}; then
                test_pass "Service ${service} is running"
            else
                test_fail "Service ${service} is not running"
            fi
        else
            test_fail "Service ${service} not found"
        fi
    done
    
    # Check for failed services
    local failed_services=$(systemctl --failed --no-legend | wc -l)
    if [ ${failed_services} -eq 0 ]; then
        test_pass "No failed services"
    else
        test_fail "${failed_services} failed services detected"
        systemctl --failed --no-legend
    fi
}

# Hardware-specific tests
validate_robot_hardware() {
    test_start "Robot Hardware Validation"
    
    [ -f /etc/lekiwi/hardware.conf ] && source /etc/lekiwi/hardware.conf
    
    case "${ROBOT_TYPE}" in
        lekiwi)
            # Lekiwi-specific tests
            test_info "Running Lekiwi hardware tests..."
            
            # Test I2C communication
            if i2cdetect -y 1 &>/dev/null; then
                test_pass "I2C bus accessible"
                
                # Check servo controller
                if i2cget -y 1 0x40 0x00 &>/dev/null; then
                    test_pass "Servo controller responding"
                else
                    test_fail "Servo controller not responding"
                fi
            else
                test_fail "I2C bus not accessible"
            fi
            
            # Test GPIO
            if [ -w /sys/class/gpio/export ]; then
                test_pass "GPIO accessible"
            else
                test_fail "GPIO not accessible"
            fi
            ;;
            
        xle)
            # XLE-specific tests
            test_info "Running XLE hardware tests..."
            
            # Test RealSense camera
            if lsusb | grep -q "Intel.*RealSense"; then
                test_pass "RealSense camera detected"
                
                # Check video devices
                if ls /dev/video* &>/dev/null; then
                    test_pass "Video devices present"
                else
                    test_fail "No video devices found"
                fi
            else
                test_warn "RealSense camera not detected"
            fi
            
            # Test arm controllers
            if lsusb | grep -qE "(Dynamixel|STM32|FTDI)"; then
                test_pass "Arm controllers detected"
            else
                test_fail "Arm controllers not detected"
            fi
            ;;
            
        *)
            test_skip "Unknown robot type, skipping hardware tests"
            ;;
    esac
}

# Rollback readiness check
validate_rollback_capability() {
    test_start "Rollback Capability Validation"
    
    # Check for backup partition
    if lsblk | grep -q "backup"; then
        test_pass "Backup partition exists"
    else
        test_warn "No backup partition found"
    fi
    
    # Check for recovery scripts
    if [ -f /usr/local/bin/factory-reset.sh ]; then
        test_pass "Factory reset script available"
    else
        test_warn "Factory reset script not found"
    fi
    
    # Check for backup configurations
    if [ -d /etc/lekiwi/backup ]; then
        test_pass "Backup directory exists"
        local backup_count=$(ls /etc/lekiwi/backup | wc -l)
        test_info "Backup files: ${backup_count}"
    else
        test_warn "No backup directory"
    fi
}

# Integration tests
run_integration_tests() {
    test_start "Integration Tests"
    
    # Test end-to-end heartbeat
    test_info "Testing heartbeat communication..."
    
    # Trigger manual heartbeat
    if curl -X POST http://localhost:${AGENT_PORT}/heartbeat &>/dev/null; then
        test_pass "Manual heartbeat triggered"
    else
        test_fail "Failed to trigger heartbeat"
    fi
    
    # Test hardware detection integration
    if [ -f /usr/local/bin/detect-hardware.sh ]; then
        test_info "Re-running hardware detection..."
        if /usr/local/bin/detect-hardware.sh &>/dev/null; then
            test_pass "Hardware detection successful"
        else
            test_fail "Hardware detection failed"
        fi
    fi
    
    # Test certificate renewal
    if [ -f /usr/local/bin/rotate-robot-cert.sh ]; then
        test_info "Testing certificate rotation..."
        if /usr/local/bin/rotate-robot-cert.sh &>/dev/null; then
            test_pass "Certificate rotation test passed"
        else
            test_warn "Certificate rotation test failed"
        fi
    fi
}

# Generate test report
generate_report() {
    echo ""
    echo "======================================"
    echo "VALIDATION REPORT SUMMARY"
    echo "======================================"
    echo "Date: $(date)"
    echo "Hostname: $(hostname)"
    echo "Robot Type: ${ROBOT_TYPE:-unknown}"
    echo "======================================"
    echo -e "${GREEN}Passed:${NC} ${TESTS_PASSED}"
    echo -e "${RED}Failed:${NC} ${TESTS_FAILED}"
    echo -e "${YELLOW}Skipped:${NC} ${TESTS_SKIPPED}"
    echo "Total: ${TESTS_TOTAL}"
    echo "======================================"
    
    local success_rate=0
    if [ ${TESTS_TOTAL} -gt 0 ]; then
        success_rate=$(( TESTS_PASSED * 100 / TESTS_TOTAL ))
    fi
    
    echo "Success Rate: ${success_rate}%"
    
    if [ ${TESTS_FAILED} -eq 0 ]; then
        echo -e "${GREEN}VALIDATION SUCCESSFUL${NC}"
        return 0
    elif [ ${success_rate} -ge 80 ]; then
        echo -e "${YELLOW}VALIDATION PASSED WITH WARNINGS${NC}"
        return 0
    else
        echo -e "${RED}VALIDATION FAILED${NC}"
        return 1
    fi
}

# Main test execution
main() {
    echo "======================================"
    echo "Lekiwi/XLE Robot Installation Validation"
    echo "======================================"
    echo "Starting validation tests..."
    echo ""
    
    # Run all validation tests
    validate_prerequisites
    validate_system_resources
    validate_hardware_detection
    validate_network
    validate_agent
    validate_security
    validate_performance
    validate_services
    validate_robot_hardware
    validate_rollback_capability
    run_integration_tests
    
    # Generate and display report
    generate_report
    
    # Save report
    echo ""
    echo "Full report saved to: ${TEST_REPORT}"
    
    # Exit with appropriate code
    exit $?
}

# Run main function
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
    main "$@"
fi