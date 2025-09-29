"""Base event classes for event sourcing."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Type, List
from uuid import UUID, uuid4
import json


class EventType(Enum):
    """Event types for robot state management."""
    # Robot lifecycle events
    ROBOT_DISCOVERED = "robot_discovered"
    ROBOT_PROVISIONED = "robot_provisioned"
    ROBOT_ACTIVATED = "robot_activated"
    ROBOT_DEACTIVATED = "robot_deactivated"
    ROBOT_FAILED = "robot_failed"
    ROBOT_RECOVERED = "robot_recovered"
    ROBOT_MAINTENANCE_START = "robot_maintenance_start"
    ROBOT_MAINTENANCE_END = "robot_maintenance_end"
    ROBOT_HEARTBEAT = "robot_heartbeat"
    ROBOT_CONFIG_CHANGED = "robot_config_changed"
    
    # Deployment events  
    DEPLOYMENT_STARTED = "deployment_started"
    DEPLOYMENT_COMPLETED = "deployment_completed"
    DEPLOYMENT_FAILED = "deployment_failed"


@dataclass
class Event(ABC):
    """Base event class for all domain events."""
    
    event_id: UUID = field(default_factory=uuid4)
    event_type: EventType = field(init=False)
    aggregate_id: UUID = field(default_factory=uuid4)  # Robot ID
    aggregate_type: str = "robot"
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Set event type after initialization."""
        if not hasattr(self, 'event_type'):
            # Derive event type from class name
            class_name = self.__class__.__name__
            # Convert CamelCase to snake_case
            import re
            snake_case = re.sub('([A-Z]+)', r'_\1', class_name).lower().strip('_')
            try:
                self.event_type = EventType[snake_case.upper()]
            except KeyError:
                raise ValueError(f"No EventType defined for {class_name}")
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for storage."""
        pass
    
    @classmethod
    @abstractmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Event':
        """Create event from dictionary."""
        pass
    
    def to_json(self) -> str:
        """Convert event to JSON string."""
        data = self.to_dict()
        # Convert datetime objects to ISO format
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = value.isoformat()
            elif isinstance(value, UUID):
                data[key] = str(value)
            elif isinstance(value, Enum):
                data[key] = value.value
        return json.dumps(data)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Event':
        """Create event from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)


class EventHandler(ABC):
    """Base class for event handlers."""
    
    @abstractmethod
    def handle(self, event: Event) -> None:
        """Handle an event."""
        pass
    
    @abstractmethod
    def can_handle(self, event: Event) -> bool:
        """Check if this handler can handle the event."""
        pass


class EventBus:
    """Simple event bus for publishing and handling events."""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._all_handlers: List[EventHandler] = []
    
    def register_handler(self, event_type: EventType, handler: EventHandler) -> None:
        """Register an event handler for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def register_global_handler(self, handler: EventHandler) -> None:
        """Register a handler for all events."""
        self._all_handlers.append(handler)
    
    async def publish(self, event: Event) -> None:
        """Publish an event to all registered handlers."""
        # Handle specific event type handlers
        if event.event_type in self._handlers:
            for handler in self._handlers[event.event_type]:
                if handler.can_handle(event):
                    await handler.handle(event)
        
        # Handle global handlers
        for handler in self._all_handlers:
            if handler.can_handle(event):
                await handler.handle(event)


class EventStore:
    """Interface for event storage."""
    
    @abstractmethod
    async def append(self, event: Event) -> None:
        """Append an event to the store."""
        pass
    
    @abstractmethod
    async def get_events(self, aggregate_id: UUID, 
                        from_version: Optional[int] = None) -> List[Event]:
        """Get events for an aggregate."""
        pass
    
    @abstractmethod
    async def get_all_events(self, event_type: Optional[EventType] = None,
                            from_timestamp: Optional[datetime] = None) -> List[Event]:
        """Get all events, optionally filtered."""
        pass