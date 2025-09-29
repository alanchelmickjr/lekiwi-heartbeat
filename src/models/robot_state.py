"""State machine implementation for robot lifecycle."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional, List, Any, Callable
from uuid import UUID

from ..events.base import Event, EventType
from ..events.robot_events import (
    RobotDiscoveredEvent,
    RobotProvisionedEvent,
    RobotActivatedEvent,
    RobotFailedEvent,
    RobotHeartbeatEvent
)


class RobotState(Enum):
    """Robot lifecycle states."""
    DISCOVERED = "discovered"
    PROVISIONING = "provisioning"
    READY = "ready"
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"
    FAILED = "failed"


class RobotType(Enum):
    """Robot types."""
    LEKIWI = "lekiwi"
    XLEROBOT = "xlerobot"
    UNKNOWN = "unknown"


class StateTransition:
    """Represents a valid state transition."""
    
    def __init__(self, from_state: RobotState, to_state: RobotState, 
                 event_type: EventType, condition: Optional[Callable] = None):
        self.from_state = from_state
        self.to_state = to_state
        self.event_type = event_type
        self.condition = condition
    
    def can_transition(self, event: Event, robot: 'Robot') -> bool:
        """Check if transition is valid for given event and robot."""
        if event.event_type != self.event_type:
            return False
        if self.condition and not self.condition(event, robot):
            return False
        return True


@dataclass
class Robot:
    """Robot aggregate with state machine."""
    
    robot_id: UUID
    ip_address: str
    hostname: Optional[str] = None
    robot_type: RobotType = RobotType.UNKNOWN
    state: RobotState = RobotState.DISCOVERED
    
    # Details
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    deployment_version: Optional[str] = None
    
    # State tracking
    last_heartbeat: Optional[datetime] = None
    last_state_change: datetime = field(default_factory=datetime.utcnow)
    failure_count: int = 0
    consecutive_failures: int = 0
    
    # Configuration
    config: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    provisioned_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Events
    uncommitted_events: List[Event] = field(default_factory=list)
    version: int = 0
    
    def __post_init__(self):
        """Initialize state transitions."""
        self._init_transitions()
    
    def _init_transitions(self):
        """Initialize valid state transitions."""
        self.transitions = [
            # From DISCOVERED
            StateTransition(
                RobotState.DISCOVERED, 
                RobotState.PROVISIONING,
                EventType.ROBOT_PROVISIONED
            ),
            StateTransition(
                RobotState.DISCOVERED,
                RobotState.FAILED,
                EventType.ROBOT_FAILED
            ),
            
            # From PROVISIONING
            StateTransition(
                RobotState.PROVISIONING,
                RobotState.READY,
                EventType.ROBOT_PROVISIONED,
                condition=lambda e, r: hasattr(e, 'deployment_version') and e.deployment_version
            ),
            StateTransition(
                RobotState.PROVISIONING,
                RobotState.FAILED,
                EventType.ROBOT_FAILED
            ),
            
            # From READY
            StateTransition(
                RobotState.READY,
                RobotState.ACTIVE,
                EventType.ROBOT_ACTIVATED
            ),
            StateTransition(
                RobotState.READY,
                RobotState.MAINTENANCE,
                EventType.ROBOT_MAINTENANCE_START
            ),
            StateTransition(
                RobotState.READY,
                RobotState.FAILED,
                EventType.ROBOT_FAILED
            ),
            
            # From ACTIVE
            StateTransition(
                RobotState.ACTIVE,
                RobotState.READY,
                EventType.ROBOT_DEACTIVATED
            ),
            StateTransition(
                RobotState.ACTIVE,
                RobotState.MAINTENANCE,
                EventType.ROBOT_MAINTENANCE_START
            ),
            StateTransition(
                RobotState.ACTIVE,
                RobotState.OFFLINE,
                EventType.ROBOT_FAILED,
                condition=lambda e, r: r.consecutive_failures < 3
            ),
            StateTransition(
                RobotState.ACTIVE,
                RobotState.FAILED,
                EventType.ROBOT_FAILED,
                condition=lambda e, r: r.consecutive_failures >= 3
            ),
            
            # From MAINTENANCE
            StateTransition(
                RobotState.MAINTENANCE,
                RobotState.READY,
                EventType.ROBOT_MAINTENANCE_END
            ),
            StateTransition(
                RobotState.MAINTENANCE,
                RobotState.FAILED,
                EventType.ROBOT_FAILED
            ),
            
            # From OFFLINE
            StateTransition(
                RobotState.OFFLINE,
                RobotState.READY,
                EventType.ROBOT_RECOVERED
            ),
            StateTransition(
                RobotState.OFFLINE,
                RobotState.FAILED,
                EventType.ROBOT_FAILED,
                condition=lambda e, r: r.consecutive_failures >= 5
            ),
            
            # From FAILED (recovery)
            StateTransition(
                RobotState.FAILED,
                RobotState.PROVISIONING,
                EventType.ROBOT_RECOVERED
            ),
        ]
    
    def apply_event(self, event: Event) -> bool:
        """Apply an event to change robot state."""
        # Find valid transition
        for transition in self.transitions:
            if (transition.from_state == self.state and 
                transition.can_transition(event, self)):
                
                # Apply state change
                self.state = transition.to_state
                self.last_state_change = event.created_at
                self.updated_at = datetime.utcnow()
                
                # Apply event-specific changes
                self._apply_event_changes(event)
                
                # Track uncommitted event
                self.uncommitted_events.append(event)
                self.version += 1
                
                return True
        
        # No valid transition found
        return False
    
    def _apply_event_changes(self, event: Event):
        """Apply event-specific changes to robot."""
        if isinstance(event, RobotDiscoveredEvent):
            self.hostname = event.hostname or self.hostname
            self.model = event.model or self.model
            if event.robot_type != "unknown":
                self.robot_type = RobotType(event.robot_type)
        
        elif isinstance(event, RobotProvisionedEvent):
            self.firmware_version = event.firmware_version or self.firmware_version
            self.deployment_version = event.deployment_version or self.deployment_version
            self.config.update(event.config)
            self.capabilities.update(event.capabilities)
            self.provisioned_at = event.created_at
        
        elif isinstance(event, RobotActivatedEvent):
            self.activated_at = event.created_at
            self.consecutive_failures = 0
        
        elif isinstance(event, RobotFailedEvent):
            self.failure_count += 1
            self.consecutive_failures += 1
            self.metadata['last_error'] = event.error_message
            self.metadata['last_error_code'] = event.error_code
        
        elif isinstance(event, RobotHeartbeatEvent):
            self.last_heartbeat = event.created_at
            self.consecutive_failures = 0  # Reset on successful heartbeat
            
            # Store metrics in metadata
            self.metadata['metrics'] = {
                'cpu_usage': event.cpu_usage,
                'memory_usage': event.memory_usage,
                'disk_usage': event.disk_usage,
                'temperature': event.temperature,
                'uptime_seconds': event.uptime_seconds
            }
    
    def can_transition_to(self, target_state: RobotState) -> bool:
        """Check if robot can transition to target state."""
        for transition in self.transitions:
            if (transition.from_state == self.state and 
                transition.to_state == target_state):
                return True
        return False
    
    def get_allowed_transitions(self) -> List[RobotState]:
        """Get list of states robot can transition to."""
        allowed = []
        for transition in self.transitions:
            if transition.from_state == self.state:
                if transition.to_state not in allowed:
                    allowed.append(transition.to_state)
        return allowed
    
    def is_healthy(self) -> bool:
        """Check if robot is in a healthy state."""
        if self.state in [RobotState.FAILED, RobotState.OFFLINE]:
            return False
        
        # Check heartbeat freshness
        if self.last_heartbeat:
            heartbeat_age = datetime.utcnow() - self.last_heartbeat
            if heartbeat_age > timedelta(minutes=5):
                return False
        
        # Check failure threshold
        if self.consecutive_failures >= 3:
            return False
        
        return True
    
    def needs_provisioning(self) -> bool:
        """Check if robot needs provisioning."""
        return (self.state == RobotState.DISCOVERED or 
                (self.state == RobotState.FAILED and not self.deployment_version))
    
    def is_deployable(self) -> bool:
        """Check if robot can receive deployments."""
        return self.state in [RobotState.READY, RobotState.ACTIVE]
    
    def mark_events_committed(self):
        """Clear uncommitted events after persistence."""
        self.uncommitted_events.clear()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert robot to dictionary."""
        return {
            'robot_id': str(self.robot_id),
            'ip_address': self.ip_address,
            'hostname': self.hostname,
            'robot_type': self.robot_type.value,
            'state': self.state.value,
            'model': self.model,
            'firmware_version': self.firmware_version,
            'deployment_version': self.deployment_version,
            'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            'last_state_change': self.last_state_change.isoformat(),
            'failure_count': self.failure_count,
            'consecutive_failures': self.consecutive_failures,
            'config': self.config,
            'capabilities': self.capabilities,
            'metadata': self.metadata,
            'discovered_at': self.discovered_at.isoformat(),
            'provisioned_at': self.provisioned_at.isoformat() if self.provisioned_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'updated_at': self.updated_at.isoformat(),
            'version': self.version,
            'is_healthy': self.is_healthy(),
            'needs_provisioning': self.needs_provisioning(),
            'is_deployable': self.is_deployable()
        }
    
    @classmethod
    def from_events(cls, events: List[Event]) -> 'Robot':
        """Rebuild robot state from events."""
        if not events:
            raise ValueError("Cannot create robot without events")
        
        # First event should be RobotDiscoveredEvent
        first_event = events[0]
        if not isinstance(first_event, RobotDiscoveredEvent):
            raise ValueError("First event must be RobotDiscoveredEvent")
        
        # Create robot from first event
        robot = cls(
            robot_id=first_event.aggregate_id,
            ip_address=first_event.ip_address,
            hostname=first_event.hostname,
            robot_type=RobotType(first_event.robot_type) if first_event.robot_type != "unknown" else RobotType.UNKNOWN,
            state=RobotState.DISCOVERED,
            model=first_event.model,
            discovered_at=first_event.created_at
        )
        
        # Apply remaining events
        for event in events[1:]:
            robot.apply_event(event)
        
        # Clear uncommitted events since we're loading from history
        robot.mark_events_committed()
        
        return robot


class RobotStateMachine:
    """Manages state transitions for robots."""
    
    def __init__(self):
        self.robots: Dict[UUID, Robot] = {}
    
    def add_robot(self, robot: Robot):
        """Add a robot to the state machine."""
        self.robots[robot.robot_id] = robot
    
    def get_robot(self, robot_id: UUID) -> Optional[Robot]:
        """Get a robot by ID."""
        return self.robots.get(robot_id)
    
    def process_event(self, event: Event) -> bool:
        """Process an event for a robot."""
        robot = self.get_robot(event.aggregate_id)
        
        if not robot:
            # Create new robot if it's a discovery event
            if isinstance(event, RobotDiscoveredEvent):
                robot = Robot(
                    robot_id=event.aggregate_id,
                    ip_address=event.ip_address,
                    hostname=event.hostname,
                    robot_type=RobotType(event.robot_type) if event.robot_type != "unknown" else RobotType.UNKNOWN,
                    model=event.model,
                    discovered_at=event.created_at
                )
                self.add_robot(robot)
                return True
            return False
        
        return robot.apply_event(event)
    
    def get_robots_by_state(self, state: RobotState) -> List[Robot]:
        """Get all robots in a specific state."""
        return [r for r in self.robots.values() if r.state == state]
    
    def get_healthy_robots(self) -> List[Robot]:
        """Get all healthy robots."""
        return [r for r in self.robots.values() if r.is_healthy()]
    
    def get_deployable_robots(self) -> List[Robot]:
        """Get robots that can receive deployments."""
        return [r for r in self.robots.values() if r.is_deployable()]