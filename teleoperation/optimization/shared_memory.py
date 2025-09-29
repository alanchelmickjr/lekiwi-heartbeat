#!/usr/bin/env python3
"""
Shared Memory Manager
Provides zero-copy inter-process communication for teleoperation data.
"""

import os
import mmap
import struct
import json
import logging
import threading
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import multiprocessing as mp
from multiprocessing import shared_memory

logger = logging.getLogger(__name__)


@dataclass
class SharedMemorySegment:
    """Represents a shared memory segment."""
    name: str
    size: int
    shm: Optional[shared_memory.SharedMemory] = None
    lock: Optional[threading.Lock] = None
    
    def cleanup(self):
        """Clean up shared memory."""
        if self.shm:
            try:
                self.shm.close()
            except:
                pass


class SharedMemoryManager:
    """
    Manages shared memory segments for zero-copy teleoperation data sharing.
    Uses memory-mapped files for persistence and crash recovery.
    """
    
    # Memory layout constants
    HEADER_SIZE = 64  # Bytes for metadata
    STATE_SIZE = 4096  # Bytes for teleoperation state
    METRICS_SIZE = 8192  # Bytes for metrics data
    BUFFER_SIZE = 65536  # Bytes for ring buffer
    
    # Magic number for validation
    MAGIC = 0x54454C45  # "TELE" in hex
    
    def __init__(self, namespace: str = "teleoperation"):
        self.namespace = namespace
        self.segments: Dict[str, SharedMemorySegment] = {}
        self._locks: Dict[str, threading.Lock] = {}
        
        # Memory layout
        self.layout = {
            'header': (0, self.HEADER_SIZE),
            'state': (self.HEADER_SIZE, self.STATE_SIZE),
            'metrics': (self.HEADER_SIZE + self.STATE_SIZE, self.METRICS_SIZE),
            'buffer': (self.HEADER_SIZE + self.STATE_SIZE + self.METRICS_SIZE, self.BUFFER_SIZE)
        }
        
        self.total_size = sum(size for _, size in self.layout.values())
        
        # Main shared memory segment
        self.main_segment: Optional[shared_memory.SharedMemory] = None
        
        # Process synchronization
        self.process_lock = mp.Lock()
        
    def initialize(self, create: bool = True):
        """Initialize shared memory segments."""
        try:
            segment_name = f"{self.namespace}_main"
            
            if create:
                # Try to clean up existing segment
                try:
                    existing = shared_memory.SharedMemory(name=segment_name)
                    existing.close()
                    existing.unlink()
                except:
                    pass
                
                # Create new segment
                self.main_segment = shared_memory.SharedMemory(
                    create=True,
                    size=self.total_size,
                    name=segment_name
                )
                
                # Initialize header
                self._write_header()
                
                logger.info(f"Created shared memory segment: {segment_name} ({self.total_size} bytes)")
                
            else:
                # Attach to existing segment
                self.main_segment = shared_memory.SharedMemory(
                    name=segment_name
                )
                
                # Validate header
                if not self._validate_header():
                    raise ValueError("Invalid shared memory segment")
                
                logger.info(f"Attached to shared memory segment: {segment_name}")
                
        except Exception as e:
            logger.error(f"Failed to initialize shared memory: {e}")
            raise
    
    def cleanup(self):
        """Clean up shared memory segments."""
        try:
            if self.main_segment:
                self.main_segment.close()
                
                # Only unlink if we created it
                try:
                    self.main_segment.unlink()
                except:
                    pass
                    
        except Exception as e:
            logger.error(f"Error cleaning up shared memory: {e}")
    
    def _write_header(self):
        """Write header to shared memory."""
        if not self.main_segment:
            return
            
        header_data = struct.pack(
            '!IIQQ',  # Network byte order
            self.MAGIC,  # Magic number
            1,  # Version
            int(datetime.now().timestamp()),  # Creation time
            os.getpid()  # Creator PID
        )
        
        self.main_segment.buf[:len(header_data)] = header_data
    
    def _validate_header(self) -> bool:
        """Validate shared memory header."""
        if not self.main_segment:
            return False
            
        try:
            header_data = bytes(self.main_segment.buf[:16])
            magic, version, timestamp, pid = struct.unpack('!IIQQ', header_data)
            
            return magic == self.MAGIC
            
        except:
            return False
    
    def write_state(self, state: Dict[str, Any]):
        """Write teleoperation state to shared memory."""
        with self.process_lock:
            try:
                # Serialize state
                state_json = json.dumps(state)
                state_bytes = state_json.encode('utf-8')
                
                # Check size
                if len(state_bytes) > self.STATE_SIZE:
                    logger.warning(f"State too large: {len(state_bytes)} > {self.STATE_SIZE}")
                    return False
                
                # Get state region
                start, size = self.layout['state']
                
                # Write size header
                size_bytes = struct.pack('!I', len(state_bytes))
                self.main_segment.buf[start:start+4] = size_bytes
                
                # Write state data
                self.main_segment.buf[start+4:start+4+len(state_bytes)] = state_bytes
                
                # Write timestamp
                timestamp_bytes = struct.pack('!Q', int(datetime.now().timestamp() * 1000))
                self.main_segment.buf[start+size-8:start+size] = timestamp_bytes
                
                return True
                
            except Exception as e:
                logger.error(f"Error writing state: {e}")
                return False
    
    def read_state(self) -> Optional[Dict[str, Any]]:
        """Read teleoperation state from shared memory."""
        with self.process_lock:
            try:
                # Get state region
                start, size = self.layout['state']
                
                # Read size header
                size_bytes = bytes(self.main_segment.buf[start:start+4])
                data_size = struct.unpack('!I', size_bytes)[0]
                
                if data_size == 0 or data_size > self.STATE_SIZE:
                    return None
                
                # Read state data
                state_bytes = bytes(self.main_segment.buf[start+4:start+4+data_size])
                state_json = state_bytes.decode('utf-8')
                
                # Parse state
                state = json.loads(state_json)
                
                # Read timestamp
                timestamp_bytes = bytes(self.main_segment.buf[start+size-8:start+size])
                timestamp_ms = struct.unpack('!Q', timestamp_bytes)[0]
                state['_timestamp_ms'] = timestamp_ms
                
                return state
                
            except Exception as e:
                logger.debug(f"Error reading state: {e}")
                return None
    
    def write_metrics(self, metrics: Dict[str, float]):
        """Write metrics to shared memory."""
        with self.process_lock:
            try:
                # Get metrics region
                start, size = self.layout['metrics']
                
                # Pack metrics (up to 256 metrics)
                packed_data = bytearray()
                
                # Write count
                packed_data.extend(struct.pack('!H', len(metrics)))
                
                # Write each metric
                for name, value in list(metrics.items())[:256]:
                    # Truncate name to 32 bytes
                    name_bytes = name.encode('utf-8')[:32]
                    name_bytes = name_bytes.ljust(32, b'\x00')
                    
                    packed_data.extend(name_bytes)
                    packed_data.extend(struct.pack('!d', value))
                
                # Check size
                if len(packed_data) > size:
                    logger.warning(f"Metrics too large: {len(packed_data)} > {size}")
                    return False
                
                # Write to shared memory
                self.main_segment.buf[start:start+len(packed_data)] = packed_data
                
                return True
                
            except Exception as e:
                logger.error(f"Error writing metrics: {e}")
                return False
    
    def read_metrics(self) -> Dict[str, float]:
        """Read metrics from shared memory."""
        with self.process_lock:
            try:
                # Get metrics region
                start, size = self.layout['metrics']
                
                # Read count
                count_bytes = bytes(self.main_segment.buf[start:start+2])
                count = struct.unpack('!H', count_bytes)[0]
                
                if count == 0 or count > 256:
                    return {}
                
                metrics = {}
                offset = start + 2
                
                # Read each metric
                for _ in range(count):
                    # Read name
                    name_bytes = bytes(self.main_segment.buf[offset:offset+32])
                    name = name_bytes.rstrip(b'\x00').decode('utf-8')
                    offset += 32
                    
                    # Read value
                    value_bytes = bytes(self.main_segment.buf[offset:offset+8])
                    value = struct.unpack('!d', value_bytes)[0]
                    offset += 8
                    
                    metrics[name] = value
                
                return metrics
                
            except Exception as e:
                logger.debug(f"Error reading metrics: {e}")
                return {}
    
    def get_ring_buffer(self) -> Tuple[int, int]:
        """Get ring buffer location in shared memory."""
        start, size = self.layout['buffer']
        return start, size
    
    def write_buffer_data(self, offset: int, data: bytes) -> bool:
        """Write data to ring buffer region."""
        with self.process_lock:
            try:
                buffer_start, buffer_size = self.layout['buffer']
                
                # Check bounds
                if offset + len(data) > buffer_size:
                    return False
                
                # Write data
                actual_offset = buffer_start + offset
                self.main_segment.buf[actual_offset:actual_offset+len(data)] = data
                
                return True
                
            except Exception as e:
                logger.error(f"Error writing buffer data: {e}")
                return False
    
    def read_buffer_data(self, offset: int, length: int) -> Optional[bytes]:
        """Read data from ring buffer region."""
        with self.process_lock:
            try:
                buffer_start, buffer_size = self.layout['buffer']
                
                # Check bounds
                if offset + length > buffer_size:
                    return None
                
                # Read data
                actual_offset = buffer_start + offset
                data = bytes(self.main_segment.buf[actual_offset:actual_offset+length])
                
                return data
                
            except Exception as e:
                logger.error(f"Error reading buffer data: {e}")
                return None
    
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get memory usage statistics."""
        stats = {
            'total_size': self.total_size,
            'segment_name': f"{self.namespace}_main" if self.main_segment else None,
            'layout': self.layout,
            'is_attached': self.main_segment is not None
        }
        
        if self.main_segment:
            # Check state usage
            state = self.read_state()
            if state:
                stats['state_size'] = len(json.dumps(state))
            
            # Check metrics count
            metrics = self.read_metrics()
            stats['metrics_count'] = len(metrics)
        
        return stats


class SharedMemoryPool:
    """
    Pool of shared memory segments for parallel processing.
    """
    
    def __init__(self, pool_size: int = 4, segment_size: int = 65536):
        self.pool_size = pool_size
        self.segment_size = segment_size
        self.segments: List[shared_memory.SharedMemory] = []
        self.available: mp.Queue = mp.Queue()
        
    def initialize(self):
        """Initialize memory pool."""
        for i in range(self.pool_size):
            try:
                segment = shared_memory.SharedMemory(
                    create=True,
                    size=self.segment_size,
                    name=f"teleoperation_pool_{i}"
                )
                self.segments.append(segment)
                self.available.put(i)
                
            except Exception as e:
                logger.error(f"Failed to create pool segment {i}: {e}")
    
    def acquire(self, timeout: float = 1.0) -> Optional[Tuple[int, shared_memory.SharedMemory]]:
        """Acquire a segment from the pool."""
        try:
            idx = self.available.get(timeout=timeout)
            return idx, self.segments[idx]
        except:
            return None
    
    def release(self, idx: int):
        """Release a segment back to the pool."""
        self.available.put(idx)
    
    def cleanup(self):
        """Clean up all segments."""
        for segment in self.segments:
            try:
                segment.close()
                segment.unlink()
            except:
                pass