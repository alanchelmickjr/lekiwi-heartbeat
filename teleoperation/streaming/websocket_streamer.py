#!/usr/bin/env python3
"""
WebSocket Streamer
Provides real-time teleoperation status updates via WebSocket.
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Set, Any
from datetime import datetime
import aiohttp
from aiohttp import web
import weakref

logger = logging.getLogger(__name__)


class WebSocketStreamer:
    """
    Streams teleoperation status updates to connected clients via WebSocket.
    Uses event-based push notifications for minimal latency.
    """
    
    def __init__(self, host: str = '0.0.0.0', port: int = 8765):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
        # Connected WebSocket clients
        self._websockets: Set[weakref.ref] = set()
        
        # Current teleoperation state
        self.current_state = {
            'teleoperation_active': False,
            'operators': [],
            'connections': {},
            'metrics': {},
            'timestamp': None
        }
        
        # Event queue for broadcasting
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._broadcast_task: Optional[asyncio.Task] = None
        
        # Performance metrics
        self.stream_metrics = {
            'messages_sent': 0,
            'bytes_sent': 0,
            'connected_clients': 0,
            'broadcast_latency_ms': 0.0
        }
        
        # Setup routes
        self._setup_routes()
    
    def _setup_routes(self):
        """Setup WebSocket and HTTP routes."""
        self.app.router.add_get('/ws', self._websocket_handler)
        self.app.router.add_get('/status', self._status_handler)
        self.app.router.add_get('/metrics', self._metrics_handler)
        self.app.router.add_get('/health', self._health_handler)
        
        # Add CORS middleware
        @web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
            return response
        
        self.app.middlewares.append(cors_middleware)
    
    async def start(self):
        """Start WebSocket server."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        
        # Start broadcast task
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        
        logger.info(f"WebSocket streamer started on {self.host}:{self.port}")
    
    async def stop(self):
        """Stop WebSocket server."""
        # Stop broadcast task
        if self._broadcast_task:
            self._broadcast_task.cancel()
            await asyncio.gather(self._broadcast_task, return_exceptions=True)
        
        # Close all WebSocket connections
        for ws_ref in list(self._websockets):
            ws = ws_ref()
            if ws:
                await ws.close()
        
        # Stop server
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        
        logger.info("WebSocket streamer stopped")
    
    async def _websocket_handler(self, request):
        """Handle WebSocket connections."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        # Add to connected clients
        ws_ref = weakref.ref(ws)
        self._websockets.add(ws_ref)
        self.stream_metrics['connected_clients'] = len(self._websockets)
        
        logger.info(f"WebSocket client connected: {request.remote}")
        
        # Send initial state
        await self._send_to_websocket(ws, {
            'type': 'initial_state',
            'data': self.current_state,
            'timestamp': datetime.now().isoformat()
        })
        
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    # Handle client messages
                    try:
                        data = json.loads(msg.data)
                        await self._handle_client_message(ws, data)
                    except json.JSONDecodeError:
                        await ws.send_json({
                            'type': 'error',
                            'message': 'Invalid JSON'
                        })
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f'WebSocket error: {ws.exception()}')
                    
        except Exception as e:
            logger.error(f"WebSocket handler error: {e}")
        finally:
            # Remove from connected clients
            self._websockets.discard(ws_ref)
            self.stream_metrics['connected_clients'] = len(self._websockets)
            logger.info(f"WebSocket client disconnected: {request.remote}")
        
        return ws
    
    async def _handle_client_message(self, ws, data: Dict):
        """Handle messages from WebSocket clients."""
        msg_type = data.get('type')
        
        if msg_type == 'ping':
            # Respond to ping
            await ws.send_json({
                'type': 'pong',
                'timestamp': datetime.now().isoformat()
            })
        elif msg_type == 'subscribe':
            # Handle subscription requests
            topics = data.get('topics', [])
            await ws.send_json({
                'type': 'subscribed',
                'topics': topics,
                'timestamp': datetime.now().isoformat()
            })
        elif msg_type == 'get_state':
            # Send current state
            await ws.send_json({
                'type': 'state_update',
                'data': self.current_state,
                'timestamp': datetime.now().isoformat()
            })
    
    async def _send_to_websocket(self, ws, message: Dict) -> bool:
        """Send message to a specific WebSocket client."""
        try:
            if not ws.closed:
                msg_str = json.dumps(message)
                await ws.send_str(msg_str)
                
                # Update metrics
                self.stream_metrics['messages_sent'] += 1
                self.stream_metrics['bytes_sent'] += len(msg_str)
                
                return True
        except Exception as e:
            logger.debug(f"Error sending to WebSocket: {e}")
        
        return False
    
    async def _broadcast_loop(self):
        """Broadcast events to all connected clients."""
        while True:
            try:
                # Get event from queue
                event = await self.event_queue.get()
                
                if event is None:
                    break
                
                # Measure broadcast latency
                start_time = datetime.now()
                
                # Broadcast to all connected clients
                dead_refs = set()
                tasks = []
                
                for ws_ref in self._websockets:
                    ws = ws_ref()
                    if ws:
                        tasks.append(self._send_to_websocket(ws, event))
                    else:
                        dead_refs.add(ws_ref)
                
                # Remove dead references
                self._websockets -= dead_refs
                
                # Wait for all sends to complete
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Calculate latency
                latency_ms = (datetime.now() - start_time).total_seconds() * 1000
                self.stream_metrics['broadcast_latency_ms'] = (
                    self.stream_metrics['broadcast_latency_ms'] * 0.9 + latency_ms * 0.1
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in broadcast loop: {e}")
                await asyncio.sleep(0.1)
    
    async def broadcast_event(self, event_type: str, data: Any):
        """Broadcast an event to all connected clients."""
        event = {
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Non-blocking put
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest event if queue is full
            try:
                self.event_queue.get_nowait()
                self.event_queue.put_nowait(event)
            except:
                logger.warning("Event queue full, dropping event")
    
    async def update_teleoperation_state(self, state: Dict):
        """Update teleoperation state and broadcast changes."""
        # Detect changes
        changes = self._detect_state_changes(self.current_state, state)
        
        # Update current state
        self.current_state = state
        self.current_state['timestamp'] = datetime.now().isoformat()
        
        # Broadcast state update
        await self.broadcast_event('state_update', {
            'state': state,
            'changes': changes
        })
        
        # Broadcast specific change events
        for change in changes:
            await self.broadcast_event(f'{change["field"]}_changed', {
                'old_value': change['old_value'],
                'new_value': change['new_value']
            })
    
    def _detect_state_changes(self, old_state: Dict, new_state: Dict) -> List[Dict]:
        """Detect changes between states."""
        changes = []
        
        # Check teleoperation active status
        if old_state.get('teleoperation_active') != new_state.get('teleoperation_active'):
            changes.append({
                'field': 'teleoperation_active',
                'old_value': old_state.get('teleoperation_active'),
                'new_value': new_state.get('teleoperation_active')
            })
        
        # Check operators
        old_operators = set(old_state.get('operators', []))
        new_operators = set(new_state.get('operators', []))
        
        if old_operators != new_operators:
            changes.append({
                'field': 'operators',
                'old_value': list(old_operators),
                'new_value': list(new_operators),
                'added': list(new_operators - old_operators),
                'removed': list(old_operators - new_operators)
            })
        
        return changes
    
    async def _status_handler(self, request):
        """HTTP endpoint for current status."""
        return web.json_response({
            'status': 'running',
            'state': self.current_state,
            'connected_clients': len(self._websockets),
            'timestamp': datetime.now().isoformat()
        })
    
    async def _metrics_handler(self, request):
        """HTTP endpoint for streaming metrics."""
        return web.json_response({
            'stream_metrics': self.stream_metrics,
            'queue_size': self.event_queue.qsize(),
            'timestamp': datetime.now().isoformat()
        })
    
    async def _health_handler(self, request):
        """Health check endpoint."""
        return web.json_response({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat()
        })
    
    def get_metrics(self) -> Dict:
        """Get streaming metrics."""
        return {
            'connected_clients': len(self._websockets),
            'messages_sent': self.stream_metrics['messages_sent'],
            'bytes_sent': self.stream_metrics['bytes_sent'],
            'broadcast_latency_ms': self.stream_metrics['broadcast_latency_ms'],
            'queue_size': self.event_queue.qsize()
        }


class TeleopEventTypes:
    """Event types for teleoperation monitoring."""
    
    # Connection events
    CONNECTION_ESTABLISHED = 'connection_established'
    CONNECTION_LOST = 'connection_lost'
    CONNECTION_QUALITY_CHANGED = 'connection_quality_changed'
    
    # Operator events
    OPERATOR_CONNECTED = 'operator_connected'
    OPERATOR_DISCONNECTED = 'operator_disconnected'
    OPERATOR_TOOK_CONTROL = 'operator_took_control'
    OPERATOR_RELEASED_CONTROL = 'operator_released_control'
    
    # Teleoperation events
    TELEOPERATION_STARTED = 'teleoperation_started'
    TELEOPERATION_STOPPED = 'teleoperation_stopped'
    TELEOPERATION_PAUSED = 'teleoperation_paused'
    TELEOPERATION_RESUMED = 'teleoperation_resumed'
    
    # Performance events
    LATENCY_WARNING = 'latency_warning'
    BANDWIDTH_WARNING = 'bandwidth_warning'
    PACKET_LOSS_WARNING = 'packet_loss_warning'
    
    # System events
    EMERGENCY_STOP = 'emergency_stop'
    MODE_CHANGED = 'mode_changed'
    ERROR_OCCURRED = 'error_occurred'