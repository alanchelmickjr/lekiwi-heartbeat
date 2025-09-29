#!/bin/bash
#
# Universal Rollback Script
# Provides rollback capability for any phase of migration
#

set -euo pipefail

# Configuration
LOG_DIR="/var/log/migration"
LOG_FILE="${LOG_DIR}/rollback.log"
CONFIG_FILE="/app/config/migration_config.yaml"
SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-""}
MIGRATION_EMAIL=${MIGRATION_EMAIL:-""}

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Create log directory
mkdir -p "$LOG_DIR"

# Function to log messages
log_message() {
    local level=$1
    shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*" | tee -a "$LOG_FILE"
}

# Function to send alert
send_alert() {
    local phase=$1
    local reason=$2
    local severity=${3:-"warning"}
    
    # Slack notification
    if [ -n "$SLACK_WEBHOOK_URL" ]; then
        local color="warning"
        local emoji="⚠️"
        
        if [ "$severity" == "critical" ]; then
            color="danger"
            emoji="🚨"
        fi
        
        curl -X POST "$SLACK_WEBHOOK_URL" \
            -H 'Content-Type: application/json' \
            -d "{
                \"text\": \"$emoji Migration Rollback Initiated\",
                \"attachments\": [{
                    \"color\": \"$color\",
                    \"fields\": [
                        {\"title\": \"Phase\", \"value\": \"$phase\", \"short\": true},
                        {\"title\": \"Reason\", \"value\": \"$reason\", \"short\": false},
                        {\"title\": \"Severity\", \"value\": \"$severity\", \"short\": true},
                        {\"title\": \"Executor\", \"value\": \"${USER:-system}\", \"short\": true},
                        {\"title\": \"Timestamp\", \"value\": \"$(date '+%Y-%m-%d %H:%M:%S')\", \"short\": false}
                    ]
                }]
            }" 2>/dev/null || log_message "WARN" "Failed to send Slack notification"
    fi
    
    # Email notification
    if [ -n "$MIGRATION_EMAIL" ]; then
        echo -e "Subject: [MIGRATION] Rollback Initiated - $phase\n\nPhase: $phase\nReason: $reason\nSeverity: $severity\nTime: $(date)" | \
            sendmail "$MIGRATION_EMAIL" 2>/dev/null || log_message "WARN" "Failed to send email"
    fi
}

# Function to update traffic split
update_traffic_split() {
    local percentage=$1
    log_message "INFO" "Updating traffic split to $percentage%"
    
    if [ -x "./update_traffic_split.sh" ]; then
        ./update_traffic_split.sh "$percentage" "rollback" || {
            log_message "ERROR" "Failed to update traffic split"
            return 1
        }
    else
        log_message "ERROR" "Traffic split script not found"
        return 1
    fi
}

# Function to stop new services
stop_new_services() {
    log_message "INFO" "Stopping new services..."
    
    # Stop Docker services
    if command -v docker-compose &> /dev/null; then
        docker-compose -f /app/migration/docker-compose.new.yml stop || {
            log_message "WARN" "Failed to stop some Docker services"
        }
    fi
    
    # Stop systemd services if they exist
    for service in discovery-service state-manager websocket-monitor teleoperation-service; do
        if systemctl is-active --quiet "lekiwi-$service"; then
            systemctl stop "lekiwi-$service" || {
                log_message "WARN" "Failed to stop $service"
            }
        fi
    done
}

# Function to restart legacy services
restart_legacy_services() {
    log_message "INFO" "Restarting legacy services..."
    
    # Restart legacy Docker services
    if [ -f "/app/docker-compose.legacy.yml" ]; then
        docker-compose -f /app/docker-compose.legacy.yml up -d || {
            log_message "ERROR" "Failed to restart legacy Docker services"
            return 1
        }
    fi
    
    # Restart legacy systemd service
    if systemctl is-enabled --quiet lekiwi-legacy; then
        systemctl restart lekiwi-legacy || {
            log_message "ERROR" "Failed to restart legacy service"
            return 1
        }
    fi
    
    # Wait for legacy to be healthy
    local max_retries=30
    local retry=0
    
    while [ $retry -lt $max_retries ]; do
        if curl -s -f "http://localhost:8000/health" > /dev/null 2>&1; then
            log_message "INFO" "Legacy system is healthy"
            return 0
        fi
        
        sleep 2
        retry=$((retry + 1))
    done
    
    log_message "ERROR" "Legacy system failed to become healthy"
    return 1
}

# Function to restore database backup
restore_database_backup() {
    local backup_file=$1
    
    log_message "INFO" "Restoring database from $backup_file"
    
    if [ ! -f "$backup_file" ]; then
        log_message "ERROR" "Backup file not found: $backup_file"
        return 1
    fi
    
    # Stop services that use the database
    stop_new_services
    
    # Restore PostgreSQL
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS lekiwi_heartbeat_rollback;"
    sudo -u postgres psql -c "ALTER DATABASE lekiwi_heartbeat RENAME TO lekiwi_heartbeat_rollback;"
    sudo -u postgres psql -c "CREATE DATABASE lekiwi_heartbeat;"
    sudo -u postgres psql lekiwi_heartbeat < "$backup_file" || {
        log_message "ERROR" "Database restore failed"
        # Try to restore the original
        sudo -u postgres psql -c "DROP DATABASE IF EXISTS lekiwi_heartbeat;"
        sudo -u postgres psql -c "ALTER DATABASE lekiwi_heartbeat_rollback RENAME TO lekiwi_heartbeat;"
        return 1
    }
    
    log_message "INFO" "Database restored successfully"
}

# Function to clear Redis cache
clear_redis_cache() {
    log_message "INFO" "Clearing Redis cache..."
    
    redis-cli FLUSHDB || {
        log_message "WARN" "Failed to clear Redis cache"
    }
}

# Function to update feature flags
update_feature_flags() {
    local enable_new_features=$1
    
    log_message "INFO" "Updating feature flags (new_features=$enable_new_features)"
    
    python3 - <<EOF
import yaml
import sys

try:
    with open('$CONFIG_FILE', 'r') as f:
        config = yaml.safe_load(f)
    
    flags = config.get('rollout', {}).get('feature_flags', {})
    for flag in flags:
        config['rollout']['feature_flags'][flag] = $enable_new_features
    
    with open('$CONFIG_FILE', 'w') as f:
        yaml.dump(config, f)
    
    print("Feature flags updated successfully")
except Exception as e:
    print(f"Failed to update feature flags: {e}", file=sys.stderr)
    sys.exit(1)
EOF
}

# Function to verify rollback
verify_rollback() {
    local target_phase=$1
    
    log_message "INFO" "Verifying rollback to $target_phase..."
    
    local checks_passed=0
    local total_checks=0
    
    # Check legacy system health
    total_checks=$((total_checks + 1))
    if curl -s -f "http://localhost:8000/health" > /dev/null 2>&1; then
        log_message "INFO" "✓ Legacy system is healthy"
        checks_passed=$((checks_passed + 1))
    else
        log_message "ERROR" "✗ Legacy system is not healthy"
    fi
    
    # Check traffic routing
    total_checks=$((total_checks + 1))
    local current_split=$(grep -oP 'new_backend.*weight=\K\d+' /etc/nginx/conf.d/upstream.conf 2>/dev/null || echo "0")
    local expected_split=0
    
    case $target_phase in
        "canary_10") expected_split=0 ;;
        "rollout_25") expected_split=10 ;;
        "rollout_50") expected_split=25 ;;
        "full_100") expected_split=50 ;;
        "emergency") expected_split=0 ;;
    esac
    
    if [ "$current_split" -eq "$expected_split" ]; then
        log_message "INFO" "✓ Traffic split is correct ($current_split%)"
        checks_passed=$((checks_passed + 1))
    else
        log_message "ERROR" "✗ Traffic split mismatch (current=$current_split%, expected=$expected_split%)"
    fi
    
    # Check feature flags
    total_checks=$((total_checks + 1))
    local flags_status=$(python3 -c "
import yaml
with open('$CONFIG_FILE') as f:
    config = yaml.safe_load(f)
flags = config.get('rollout', {}).get('feature_flags', {})
print('disabled' if all(not v for v in flags.values()) else 'enabled')
" 2>/dev/null || echo "unknown")
    
    if [ "$target_phase" == "emergency" ] && [ "$flags_status" == "disabled" ]; then
        log_message "INFO" "✓ Feature flags are disabled"
        checks_passed=$((checks_passed + 1))
    elif [ "$target_phase" != "emergency" ]; then
        log_message "INFO" "✓ Feature flags in appropriate state"
        checks_passed=$((checks_passed + 1))
    else
        log_message "WARN" "⚠ Feature flags state: $flags_status"
    fi
    
    # Summary
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Rollback Verification Results${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo "Checks passed: $checks_passed/$total_checks"
    
    if [ "$checks_passed" -eq "$total_checks" ]; then
        echo -e "${GREEN}✓ Rollback completed successfully${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠ Rollback completed with warnings${NC}"
        return 1
    fi
}

# Function to perform phase-specific rollback
rollback_phase() {
    local phase=$1
    local reason=$2
    
    case $phase in
        "canary_10")
            log_message "INFO" "Rolling back from 10% canary"
            update_traffic_split 0
            update_feature_flags false
            ;;
            
        "rollout_25")
            log_message "INFO" "Rolling back from 25% rollout"
            update_traffic_split 10
            ;;
            
        "rollout_50")
            log_message "INFO" "Rolling back from 50% rollout"
            update_traffic_split 25
            ;;
            
        "full_100")
            log_message "INFO" "Rolling back from 100% migration"
            update_traffic_split 50
            ;;
            
        "emergency")
            log_message "CRITICAL" "EMERGENCY ROLLBACK - Full revert to legacy"
            update_traffic_split 0
            update_feature_flags false
            stop_new_services
            restart_legacy_services
            clear_redis_cache
            ;;
            
        "data_corruption")
            log_message "CRITICAL" "Rolling back due to data corruption"
            
            # Find latest backup
            LATEST_BACKUP=$(ls -t /backups/postgres_*.sql 2>/dev/null | head -1)
            
            if [ -n "$LATEST_BACKUP" ]; then
                restore_database_backup "$LATEST_BACKUP"
            else
                log_message "ERROR" "No database backup found!"
                return 1
            fi
            
            update_traffic_split 0
            update_feature_flags false
            restart_legacy_services
            ;;
            
        *)
            log_message "ERROR" "Unknown rollback phase: $phase"
            echo "Valid phases: canary_10, rollout_25, rollout_50, full_100, emergency, data_corruption"
            return 1
            ;;
    esac
}

# Main execution
main() {
    local PHASE=${1:-}
    local REASON=${2:-"Manual rollback"}
    local AUTO_CONFIRM=${3:-false}
    
    if [ -z "$PHASE" ]; then
        echo "Usage: $0 <phase> [reason] [auto-confirm]"
        echo ""
        echo "Phases:"
        echo "  canary_10       - Rollback from 10% canary deployment"
        echo "  rollout_25      - Rollback from 25% rollout"
        echo "  rollout_50      - Rollback from 50% rollout"
        echo "  full_100        - Rollback from 100% migration"
        echo "  emergency       - Emergency full rollback to legacy"
        echo "  data_corruption - Rollback with database restore"
        echo ""
        echo "Examples:"
        echo "  $0 canary_10 'High error rate detected'"
        echo "  $0 emergency 'Critical system failure' true"
        exit 1
    fi
    
    # Confirmation prompt (unless auto-confirm)
    if [ "$AUTO_CONFIRM" != "true" ]; then
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}⚠️  ROLLBACK CONFIRMATION REQUIRED${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo "Phase: $PHASE"
        echo "Reason: $REASON"
        echo ""
        echo -e "${RED}This action will revert the migration progress.${NC}"
        echo ""
        read -p "Are you sure you want to proceed? (yes/no): " confirmation
        
        if [ "$confirmation" != "yes" ]; then
            echo "Rollback cancelled."
            exit 0
        fi
    fi
    
    # Start rollback
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Starting Rollback Process${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    log_message "INFO" "=== ROLLBACK INITIATED ==="
    log_message "INFO" "Phase: $PHASE"
    log_message "INFO" "Reason: $REASON"
    log_message "INFO" "Executor: ${USER:-system}"
    
    # Send initial alert
    send_alert "$PHASE" "$REASON" "warning"
    
    # Perform rollback
    if rollback_phase "$PHASE" "$REASON"; then
        log_message "INFO" "Rollback phase completed"
    else
        log_message "ERROR" "Rollback phase failed"
        send_alert "$PHASE" "Rollback failed: $REASON" "critical"
        exit 1
    fi
    
    # Verify rollback
    if verify_rollback "$PHASE"; then
        log_message "INFO" "Rollback verification passed"
        
        # Update migration config
        python3 -c "
import yaml
with open('$CONFIG_FILE', 'r') as f:
    config = yaml.safe_load(f)
config['migration']['last_rollback'] = {
    'phase': '$PHASE',
    'reason': '$REASON',
    'timestamp': '$(date -Iseconds)',
    'executor': '${USER:-system}'
}
with open('$CONFIG_FILE', 'w') as f:
    yaml.dump(config, f)
" 2>/dev/null || log_message "WARN" "Failed to update config"
        
        # Final notification
        send_alert "$PHASE" "Rollback completed successfully: $REASON" "warning"
        
        echo ""
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}✓ Rollback Completed Successfully${NC}"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo "The system has been rolled back to the previous stable state."
        echo "Please review the logs at: $LOG_FILE"
        
    else
        log_message "ERROR" "Rollback verification failed"
        send_alert "$PHASE" "Rollback verification failed: $REASON" "critical"
        
        echo ""
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${RED}⚠️  Rollback Completed with Warnings${NC}"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo "Manual intervention may be required."
        echo "Check logs at: $LOG_FILE"
        
        exit 1
    fi
}

# Trap errors
trap 'log_message "ERROR" "Script failed at line $LINENO"' ERR

# Run main function
main "$@"