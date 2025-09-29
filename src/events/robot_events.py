"""Robot-specific event definitions."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from .base import Event, EventType


@dataclass
class RobotDiscoveredEvent(Event):
    """Event when a new robot is discovered."""
    
    ip_address: str = ""
    hostname: Optional[str] = None
    robot_type: str = "unknown"
    model: Optional[str] = None
    ssh_banner: Optional[str] = None
    discovery_method: str = "websocket"
    response_time_ms: Optional[int] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.ROBOT_DISCOVERED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "ip_address": self.ip_address,
            "hostname": self.hostname,
            "robot_type": self.robot_type,
            "model": self.model,
            "ssh_banner": self.ssh_banner,
            "discovery_method": self.discovery_method,
            "response_time_ms": self.response_time_ms
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RobotDiscoveredEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            ip_address=data["ip_address"],
            hostname=data.get("hostname"),
            robot_type=data.get("robot_type", "unknown"),
            model=data.get("model"),
            ssh_banner=data.get("ssh_banner"),
            discovery_method=data.get("discovery_method", "websocket"),
            response_time_ms=data.get("response_time_ms")
        )


@dataclass
class RobotProvisionedEvent(Event):
    """Event when a robot is provisioned."""
    
    firmware_version: Optional[str] = None
    deployment_version: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.ROBOT_PROVISIONED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "firmware_version": self.firmware_version,
            "deployment_version": self.deployment_version,
            "config": self.config,
            "capabilities": self.capabilities
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RobotProvisionedEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            firmware_version=data.get("firmware_version"),
            deployment_version=data.get("deployment_version"),
            config=data.get("config", {}),
            capabilities=data.get("capabilities", {})
        )


@dataclass
class RobotActivatedEvent(Event):
    """Event when a robot is activated."""
    
    activation_reason: Optional[str] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.ROBOT_ACTIVATED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "activation_reason": self.activation_reason
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RobotActivatedEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            activation_reason=data.get("activation_reason")
        )


@dataclass
class RobotFailedEvent(Event):
    """Event when a robot fails."""
    
    error_message: str = ""
    error_code: Optional[str] = None
    failure_type: str = "unknown"  # connection, deployment, hardware, software
    retry_count: int = 0
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.ROBOT_FAILED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "error_message": self.error_message,
            "error_code": self.error_code,
            "failure_type": self.failure_type,
            "retry_count": self.retry_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RobotFailedEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            error_message=data.get("error_message", ""),
            error_code=data.get("error_code"),
            failure_type=data.get("failure_type", "unknown"),
            retry_count=data.get("retry_count", 0)
        )


@dataclass
class RobotHeartbeatEvent(Event):
    """Event for robot heartbeat."""
    
    cpu_usage: Optional[float] = None
    memory_usage: Optional[float] = None
    disk_usage: Optional[float] = None
    temperature: Optional[float] = None
    uptime_seconds: Optional[int] = None
    active_processes: Optional[int] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.ROBOT_HEARTBEAT
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "cpu_usage": self.cpu_usage,
            "memory_usage": self.memory_usage,
            "disk_usage": self.disk_usage,
            "temperature": self.temperature,
            "uptime_seconds": self.uptime_seconds,
            "active_processes": self.active_processes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RobotHeartbeatEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            cpu_usage=data.get("cpu_usage"),
            memory_usage=data.get("memory_usage"),
            disk_usage=data.get("disk_usage"),
            temperature=data.get("temperature"),
            uptime_seconds=data.get("uptime_seconds"),
            active_processes=data.get("active_processes")
        )


@dataclass 
class DeploymentStartedEvent(Event):
    """Event when deployment starts on a robot."""
    
    deployment_id: UUID = field(default_factory=UUID)
    version: str = ""
    deployment_type: str = "full"  # full, delta, rollback
    source: Optional[str] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.DEPLOYMENT_STARTED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "deployment_id": str(self.deployment_id),
            "version": self.version,
            "deployment_type": self.deployment_type,
            "source": self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeploymentStartedEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            deployment_id=UUID(data["deployment_id"]),
            version=data.get("version", ""),
            deployment_type=data.get("deployment_type", "full"),
            source=data.get("source")
        )


@dataclass
class DeploymentCompletedEvent(Event):
    """Event when deployment completes successfully."""
    
    deployment_id: UUID = field(default_factory=UUID)
    version: str = ""
    duration_seconds: Optional[int] = None
    files_changed: Optional[int] = None
    
    def __post_init__(self):
        super().__post_init__()
        self.event_type = EventType.DEPLOYMENT_COMPLETED
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type.value,
            "aggregate_id": str(self.aggregate_id),
            "aggregate_type": self.aggregate_type,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "metadata": self.metadata,
            "deployment_id": str(self.deployment_id),
            "version": self.version,
            "duration_seconds": self.duration_seconds,
            "files_changed": self.files_changed
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeploymentCompletedEvent':
        return cls(
            event_id=UUID(data["event_id"]),
            aggregate_id=UUID(data["aggregate_id"]),
            aggregate_type=data.get("aggregate_type", "robot"),
            created_at=datetime.fromisoformat(data["created_at"]),
            created_by=data.get("created_by"),
            metadata=data.get("metadata", {}),
            deployment_id=UUID(data["deployment_id"]),
            version=data.get("version", ""),
            duration_seconds=data.get("duration_seconds"),
            files_changed=data.get("files_changed")
        )


# Event factory to create events from type
EVENT_CLASSES = {
    EventType.ROBOT_DISCOVERED: RobotDiscoveredEvent,
    EventType.ROBOT_PROVISIONED: RobotProvisionedEvent,
    EventType.ROBOT_ACTIVATED: RobotActivatedEvent,
    EventType.ROBOT_FAILED: RobotFailedEvent,
    EventType.ROBOT_HEARTBEAT: RobotHeartbeatEvent,
    EventType.DEPLOYMENT_STARTED: DeploymentStartedEvent,
    EventType.DEPLOYMENT_COMPLETED: DeploymentCompletedEvent,
}


def create_event(event_type: EventType, **kwargs) -> Event:
    """Factory function to create events."""
    event_class = EVENT_CLASSES.get(event_type)
    if not event_class:
        raise ValueError(f"No event class for type: {event_type}")
    return event_class(**kwargs)