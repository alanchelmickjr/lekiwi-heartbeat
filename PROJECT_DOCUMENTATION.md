# LeKiwi Heartbeat Project Documentation

## Project Overview
LeKiwi Heartbeat is a Vercel-style deployment system for robot fleets, providing automated deployment, monitoring, and management of robotic systems with Git-based continuous deployment.

## File Structure and Documentation

### Root Level Files

#### `install.sh`
**Purpose**: Main installation script for setting up the deployment system
**Entry**: Shell script execution
**Exit**: System configured with deployment server running
**Dependencies**: Python 3, Git, SSH

#### `start-deployment-system.sh`
**Purpose**: Starts the entire deployment system including server and discovery
**Entry**: Shell script execution
**Exit**: Deployment server running on port 8000
**Dependencies**: Python environment, deployment-server components

#### `requirements.txt`
**Purpose**: Python package dependencies for the entire system
**Key packages**: FastAPI, Paramiko, asyncio, uvicorn

### Deployment Server (`deployment-server/`)

#### `server.py`
**Purpose**: Main FastAPI server providing REST API for robot fleet management
**Entry Points**:
- `/` - Web dashboard
- `/api/discover` - Trigger parallel staged discovery
- `/api/fleet` - Get fleet configuration
- `/api/robot/{ip}/stages` - Get staged discovery status
- `/api/robot/{ip}/teleoperation-status` - Check teleop status (HOST vs OPERATION)
- `/api/deploy` - Create new deployment
- `/api/execute` - Execute commands on robots
**Exit**: JSON responses, WebSocket updates
**Key Features**: 
- Parallel staged discovery integration
- Deployment management
- Robot status tracking
- SSH command execution

#### `server_discovery.py` (NEW)
**Purpose**: Implements parallel staged discovery with 6 stages
**Entry**: `ParallelDiscovery.discover_network()` 
**Stages**:
1. AWAKE - Network/ping check
2. TYPE - Detect robot type (Lekiwi/XLE/blank Pi)
3. SOFTWARE - Check installed components
4. VIDEO - Camera/stream status
5. TELEOP_HOST - Service ready status
6. TELEOP_OPERATION - Actually being controlled
**Exit**: Structured discovery results with stage status
**Key Features**:
- True parallel execution with ThreadPoolExecutor
- Blank Pi detection and filtering
- Independent stage progression per robot
- <5 second discovery for 10+ robots

#### `smart_discover.py`
**Purpose**: Legacy smart robot discovery using SSH and network scanning
**Entry**: Command line execution or import
**Exit**: Discovery results in JSON and text formats
**Features**: SSH banner detection, credential validation, Raspberry Pi identification

#### `detect_robot_type.py`
**Purpose**: Determine if robot is LeKiwi or XLERobot type
**Entry**: `detect_robot_type(ip)` function
**Exit**: Robot type string ('lekiwi', 'xlerobot', 'unknown')
**Detection**: Checks for XLE-specific libraries and hardware

#### `comparison_engine.py`
**Purpose**: Compare robot deployments and create baselines
**Entry**: Various comparison functions
**Exit**: Comparison results with differences
**Features**: File checksums, baseline creation, compliance checking

#### `robot_versioning.py`
**Purpose**: Version management and delta deployments
**Entry**: Snapshot creation, version deployment
**Exit**: Version artifacts and deployment results
**Features**: Delta sync, rollback support

#### `add_discovered_robots.py`
**Purpose**: Convert discovery results to fleet configuration
**Entry**: Reads discovery text files
**Exit**: JSON fleet configuration file

### Static Web Interface (`deployment-server/static/`)

#### `index.html`
**Purpose**: Main web dashboard for robot fleet management
**Entry**: Browser request to server root
**Features**:
- Real-time robot status display
- Staged discovery visualization
- Camera preview with fullscreen
- SSH terminal integration
- Teleop HOST vs OPERATION status
**Key Updates**:
- Shows all 6 discovery stages per robot
- Distinguishes between "ready" and "operated" status
- Filters blank Pis from display
- No fake data or padding

#### `comparison.html`
**Purpose**: Robot deployment comparison interface
**Entry**: Navigation from main dashboard
**Exit**: Visual diff display
**Features**: Side-by-side deployment comparison

#### `xterm-ssh.html`
**Purpose**: Web-based SSH terminal using xterm.js
**Entry**: iframe from main dashboard
**Exit**: Interactive SSH session
**Features**: Full terminal emulation in browser

### Deployment Master (`deployment-master/`)

#### `lekiwi-master-deploy.py`
**Purpose**: Master deployment script for robot configuration
**Entry**: Command line with robot IP
**Actions**:
- `check` - Check robot status
- `full` - Complete deployment
- `teleop-only` - Configure teleop
- `install-conda` - Install Miniconda
- `setup-env` - Setup Python environment
**Exit**: Deployment status and logs

#### `lekiwi-robot-deploy.sh`
**Purpose**: Shell wrapper for deployment operations
**Entry**: Shell script execution
**Exit**: Deployment completion status

### Deployment Agent (`deployment-agent/`)

#### `agent.py`
**Purpose**: Agent running on robots for autonomous updates
**Entry**: Systemd service or direct execution
**Features**: 
- Polls server for updates
- Self-updates from Git
- Reports status back to server

### Deployment CLI (`deployment-cli/`)

#### `lekiwi-deploy`
**Purpose**: Command-line deployment tool
**Entry**: CLI command
**Exit**: Deployment status

#### `lekiwi-complete`
**Purpose**: Bash completion for CLI
**Entry**: Source in bashrc
**Exit**: Tab completion support

### SSH Proxy (`deployment-ssh/`)

#### `ssh-proxy-server.py`
**Purpose**: WebSocket to SSH proxy for browser terminals
**Entry**: WebSocket connection
**Exit**: SSH session proxied to browser

### Reverse Tunnel (`deployment-tunnel/`)

#### `reverse-tunnel-system.py`
**Purpose**: Establish reverse SSH tunnels for NAT traversal
**Entry**: Service startup
**Exit**: Persistent tunnel connections

### Teleoperation Monitoring (`teleoperation/`)

#### `monitor.py`
**Purpose**: Monitor teleoperation status and performance
**Entry**: Direct execution or import
**Features**: Multiple detection methods, performance metrics

#### Detectors (`teleoperation/detectors/`)
- `input_detector.py` - Detect user input
- `network_detector.py` - Network status monitoring
- `webrtc_detector.py` - WebRTC connection detection
- `zmq_detector.py` - ZMQ stream detection

### Factory Install (`factory-install/`)

#### `agent/` (Rust)
**Purpose**: High-performance factory installation agent
**Entry**: Rust binary execution
**Exit**: Installation completion

#### `boot-server/pxe-config.sh`
**Purpose**: PXE boot configuration for network installs
**Entry**: Script execution
**Exit**: PXE server configured

#### `cloud-init/user-data.yaml`
**Purpose**: Cloud-init configuration for automated setup
**Entry**: Cloud-init processing
**Exit**: System configured per specification

### Source Modules (`src/`)

#### `state_manager.py`
**Purpose**: Centralized state management
**Entry**: Import and instantiation
**Exit**: State queries and updates

#### `discovery_service.py`
**Purpose**: Discovery service abstraction
**Entry**: Service methods
**Exit**: Discovery results

#### `cache_manager.py`
**Purpose**: Caching layer for performance
**Entry**: Cache operations
**Exit**: Cached or fresh data

#### `integration.py`
**Purpose**: System integration utilities
**Entry**: Integration functions
**Exit**: Integrated operations

### Architecture Documentation (`architecture/`)

#### `lekiwi-heartbeat-architecture.md`
**Purpose**: System architecture documentation
**Content**: Design decisions, component interactions

### Migration (`migration/`)

#### `migration-plan.md`
**Purpose**: Migration strategy from legacy system
**Content**: Phased migration approach

#### Scripts (`migration/scripts/`)
- `sync_legacy_to_new.py` - Sync data between systems
- `universal_rollback.sh` - Emergency rollback
- `update_traffic_split.sh` - Gradual traffic migration

### Refactoring Documentation (`refactoring/`)

#### `00_executive_summary.md`
**Purpose**: Overview of refactoring strategy
**Content**: Goals, approach, timeline

#### `01_modular_refactoring_strategy.md`
**Purpose**: Modularization approach
**Content**: Component separation strategy

#### `02_implementation_phases.md`
**Purpose**: Implementation roadmap
**Content**: Phased implementation plan

#### `03_testing_validation_strategy.md`
**Purpose**: Testing strategy
**Content**: Test coverage, validation approach

## System Flow

### Discovery Flow
1. User triggers discovery via web UI
2. `server.py` calls `server_discovery.py` 
3. Parallel staged discovery runs through 6 stages
4. Blank Pis are filtered out
5. Results returned with stage status per robot
6. UI updates with real-time stage visualization

### Deployment Flow
1. User initiates deployment via UI or API
2. Server builds deployment package from Git
3. Robots poll for updates via agent
4. Deployment applied with auto-rollback on failure
5. Status reported back to server

### Teleoperation Status Flow
1. Stage 5 (TELEOP_HOST) checks if service is ready
2. Stage 6 (TELEOP_OPERATION) checks if actually being controlled
3. UI shows different badges for HOST vs OPERATION status
4. Real-time updates via WebSocket

## Key Improvements Implemented

1. **Parallel Staged Discovery**: True parallel execution with 6 distinct stages
2. **Blank Pi Detection**: Validates real robots vs blank Raspberry Pis
3. **HOST vs OPERATION Status**: Distinguishes between ready and actively controlled
4. **Performance**: <5 second discovery for 10+ robots
5. **Real-time UI**: Stage-by-stage status updates without full refresh
6. **No Fake Data**: All status information is real, no padding or fake delays

## API Response Formats

### Discovery Response
```json
{
  "status": "success",
  "fleet": {
    "robots": [
      {
        "ip": "192.168.88.21",
        "hostname": "lekiwi_21",
        "type": "lekiwi",
        "stages": {
          "awake": {"status": "success", "message": "SSH port open"},
          "type": {"status": "success", "message": "Detected as lekiwi"},
          "software": {"status": "success", "message": "All components installed"},
          "video": {"status": "success", "message": "2 camera(s) detected"},
          "teleop_host": {"status": "success", "message": "Teleop service ready"},
          "teleop_operation": {"status": "idle", "message": "Not operated"}
        }
      }
    ],
    "total": 5,
    "stages_enabled": true
  },
  "summary": {
    "total_scanned": 254,
    "valid_robots": 5,
    "blank_pis": 2
  }
}
```

## Configuration Files

### `config/system_config.yaml`
System-wide configuration parameters

### `deployment-server/comparison_config.json`
Configuration for deployment comparison engine

### `.gitignore`
Git ignore patterns for the project

### `.roomodes`
Custom IDE modes configuration

## Entry Points Summary

**Main Entry**: `start-deployment-system.sh`
**Web Interface**: `http://localhost:8000`
**API Base**: `http://localhost:8000/api`
**Discovery**: `/api/discover` (POST)
**Fleet Status**: `/api/fleet` (GET)
**Robot Stages**: `/api/robot/{ip}/stages` (GET)

## Exit Points Summary

**Deployments**: Git packages to robots
**Status**: JSON via REST API
**Real-time**: WebSocket updates
**Logs**: Console and file outputs
**Metrics**: Prometheus-compatible endpoints