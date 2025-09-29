#!/usr/bin/env python3
"""
Ring Buffer Implementation
Lock-free ring buffer for high-performance telemetry data collection.
"""

import struct
import threading
import time
from typing import Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np
from multiprocessing import shared_memory
import logging

logger = logging.getLogger(__name__)


@dataclass
class BufferItem:
    """Single item in the ring buffer."""
    timestamp: float
    item_type: int
    data_size: int
    data: bytes


class RingBuffer:
    """
    Lock-free ring buffer for telemetry data.
    Uses atomic operations for thread-safe access without locks.
    """
    
    # Item header format: timestamp(8) + type(2) + size(2) = 12 bytes
    HEADER_SIZE = 12
    MAX_ITEM_SIZE = 1024  # Maximum size for a single item
    
    def __init__(self, capacity: int = 65536):
        """
        Initialize ring buffer.
        
        Args:
            capacity: Buffer capacity in bytes
        """
        self.capacity = capacity
        
        # Allocate buffer
        self.buffer = bytearray(capacity)
        
        # Atomic pointers (using numpy for atomic operations)
        self.write_pos = np.array([0], dtype=np.uint32)
        self.read_pos = np.array([0], dtype=np.uint32)
        self.size = np.array([0], dtype=np.uint32)
        
        # Statistics
        self.stats = {
            'items_written': 0,
            'items_read': 0,
            'bytes_written': 0,
            'bytes_read': 0,
            'overflows': 0,
            'underflows': 0
        }
    
    def write(self, item_type: int, data: bytes) -> bool:
        """
        Write item to buffer (lock-free).
        
        Args:
            item_type: Type identifier for the item
            data: Item data
            
        Returns:
            True if written successfully
        """
        timestamp = time.time()
        data_size = len(data)
        
        # Check size
        total_size = self.HEADER_SIZE + data_size
        if total_size > self.MAX_ITEM_SIZE:
            logger.warning(f"Item too large: {total_size} > {self.MAX_ITEM_SIZE}")
            return False
        
        # Check available space
        current_size = self.size[0]
        if current_size + total_size > self.capacity:
            self.stats['overflows'] += 1
            return False
        
        # Get write position
        write_pos = self.write_pos[0]
        
        # Write header
        header = struct.pack('!dHH', timestamp, item_type, data_size)
        
        # Calculate positions
        header_end = write_pos + self.HEADER_SIZE
        data_end = header_end + data_size
        
        # Handle wrap-around
        if data_end <= self.capacity:
            # No wrap-around
            self.buffer[write_pos:header_end] = header
            self.buffer[header_end:data_end] = data
            new_write_pos = data_end % self.capacity
        else:
            # Wrap-around needed
            if header_end <= self.capacity:
                # Header fits, data wraps
                self.buffer[write_pos:header_end] = header
                
                first_chunk_size = self.capacity - header_end
                self.buffer[header_end:self.capacity] = data[:first_chunk_size]
                self.buffer[0:data_size - first_chunk_size] = data[first_chunk_size:]
                
                new_write_pos = data_size - first_chunk_size
            else:
                # Header wraps
                first_chunk_size = self.capacity - write_pos
                self.buffer[write_pos:self.capacity] = header[:first_chunk_size]
                self.buffer[0:self.HEADER_SIZE - first_chunk_size] = header[first_chunk_size:]
                
                # Data follows wrapped header
                data_start = self.HEADER_SIZE - first_chunk_size
                self.buffer[data_start:data_start + data_size] = data
                
                new_write_pos = data_start + data_size
        
        # Update pointers atomically
        self.write_pos[0] = new_write_pos
        self.size[0] = current_size + total_size
        
        # Update stats
        self.stats['items_written'] += 1
        self.stats['bytes_written'] += total_size
        
        return True
    
    def read(self) -> Optional[BufferItem]:
        """
        Read item from buffer (lock-free).
        
        Returns:
            BufferItem or None if buffer is empty
        """
        # Check if data available
        current_size = self.size[0]
        if current_size < self.HEADER_SIZE:
            self.stats['underflows'] += 1
            return None
        
        # Get read position
        read_pos = self.read_pos[0]
        
        # Read header
        header_end = read_pos + self.HEADER_SIZE
        
        if header_end <= self.capacity:
            # No wrap-around
            header = bytes(self.buffer[read_pos:header_end])
        else:
            # Header wraps
            first_chunk_size = self.capacity - read_pos
            header = bytes(self.buffer[read_pos:self.capacity])
            header += bytes(self.buffer[0:self.HEADER_SIZE - first_chunk_size])
        
        # Parse header
        timestamp, item_type, data_size = struct.unpack('!dHH', header)
        
        # Check if full item is available
        total_size = self.HEADER_SIZE + data_size
        if current_size < total_size:
            self.stats['underflows'] += 1
            return None
        
        # Read data
        data_start = header_end % self.capacity
        data_end = (data_start + data_size) % self.capacity
        
        if data_start < data_end:
            # No wrap-around
            data = bytes(self.buffer[data_start:data_end])
        else:
            # Data wraps
            data = bytes(self.buffer[data_start:self.capacity])
            data += bytes(self.buffer[0:data_end])
        
        # Update pointers atomically
        self.read_pos[0] = (read_pos + total_size) % self.capacity
        self.size[0] = current_size - total_size
        
        # Update stats
        self.stats['items_read'] += 1
        self.stats['bytes_read'] += total_size
        
        return BufferItem(timestamp, item_type, data_size, data)
    
    def peek(self) -> Optional[BufferItem]:
        """
        Peek at next item without removing it.
        
        Returns:
            BufferItem or None if buffer is empty
        """
        # Check if data available
        current_size = self.size[0]
        if current_size < self.HEADER_SIZE:
            return None
        
        # Get read position
        read_pos = self.read_pos[0]
        
        # Read header
        header_end = read_pos + self.HEADER_SIZE
        
        if header_end <= self.capacity:
            header = bytes(self.buffer[read_pos:header_end])
        else:
            first_chunk_size = self.capacity - read_pos
            header = bytes(self.buffer[read_pos:self.capacity])
            header += bytes(self.buffer[0:self.HEADER_SIZE - first_chunk_size])
        
        # Parse header
        timestamp, item_type, data_size = struct.unpack('!dHH', header)
        
        # Check if full item is available
        if current_size < self.HEADER_SIZE + data_size:
            return None
        
        # Read data
        data_start = header_end % self.capacity
        data_end = (data_start + data_size) % self.capacity
        
        if data_start < data_end:
            data = bytes(self.buffer[data_start:data_end])
        else:
            data = bytes(self.buffer[data_start:self.capacity])
            data += bytes(self.buffer[0:data_end])
        
        return BufferItem(timestamp, item_type, data_size, data)
    
    def clear(self):
        """Clear the buffer."""
        self.write_pos[0] = 0
        self.read_pos[0] = 0
        self.size[0] = 0
    
    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return self.size[0] == 0
    
    def is_full(self) -> bool:
        """Check if buffer is full."""
        return self.size[0] >= self.capacity - self.MAX_ITEM_SIZE
    
    def get_size(self) -> int:
        """Get current buffer size in bytes."""
        return int(self.size[0])
    
    def get_item_count(self) -> int:
        """Get approximate item count."""
        avg_item_size = 50  # Estimated average
        return self.get_size() // avg_item_size
    
    def get_stats(self) -> dict:
        """Get buffer statistics."""
        return {
            **self.stats,
            'capacity': self.capacity,
            'used_bytes': self.get_size(),
            'used_percent': (self.get_size() / self.capacity) * 100,
            'write_pos': int(self.write_pos[0]),
            'read_pos': int(self.read_pos[0])
        }


class SharedRingBuffer:
    """
    Ring buffer backed by shared memory for IPC.
    """
    
    def __init__(self, name: str, capacity: int = 65536, create: bool = True):
        """
        Initialize shared ring buffer.
        
        Args:
            name: Shared memory name
            capacity: Buffer capacity
            create: Create new buffer or attach to existing
        """
        self.name = name
        self.capacity = capacity
        
        # Metadata size: write_pos(4) + read_pos(4) + size(4) = 12 bytes
        self.metadata_size = 12
        self.total_size = self.metadata_size + capacity
        
        # Initialize shared memory
        if create:
            # Clean up existing
            try:
                existing = shared_memory.SharedMemory(name=name)
                existing.close()
                existing.unlink()
            except:
                pass
            
            # Create new
            self.shm = shared_memory.SharedMemory(
                create=True,
                size=self.total_size,
                name=name
            )
            
            # Initialize metadata
            self.shm.buf[0:4] = struct.pack('!I', 0)  # write_pos
            self.shm.buf[4:8] = struct.pack('!I', 0)  # read_pos
            self.shm.buf[8:12] = struct.pack('!I', 0)  # size
            
        else:
            # Attach to existing
            self.shm = shared_memory.SharedMemory(name=name)
        
        # Statistics
        self.stats = {
            'items_written': 0,
            'items_read': 0,
            'bytes_written': 0,
            'bytes_read': 0
        }
    
    def write(self, item_type: int, data: bytes) -> bool:
        """Write item to shared buffer."""
        timestamp = time.time()
        data_size = len(data)
        
        # Create item
        header = struct.pack('!dHH', timestamp, item_type, data_size)
        total_size = len(header) + data_size
        
        # Read metadata
        write_pos = struct.unpack('!I', bytes(self.shm.buf[0:4]))[0]
        read_pos = struct.unpack('!I', bytes(self.shm.buf[4:8]))[0]
        size = struct.unpack('!I', bytes(self.shm.buf[8:12]))[0]
        
        # Check space
        if size + total_size > self.capacity:
            return False
        
        # Calculate buffer position
        buffer_start = self.metadata_size + write_pos
        
        # Write header and data
        item_data = header + data
        
        # Handle wrap-around
        if write_pos + total_size <= self.capacity:
            # No wrap
            self.shm.buf[buffer_start:buffer_start + total_size] = item_data
            new_write_pos = write_pos + total_size
        else:
            # Wrap
            first_chunk = self.capacity - write_pos
            self.shm.buf[buffer_start:self.metadata_size + self.capacity] = item_data[:first_chunk]
            self.shm.buf[self.metadata_size:self.metadata_size + total_size - first_chunk] = item_data[first_chunk:]
            new_write_pos = total_size - first_chunk
        
        # Update metadata
        self.shm.buf[0:4] = struct.pack('!I', new_write_pos % self.capacity)
        self.shm.buf[8:12] = struct.pack('!I', size + total_size)
        
        # Update stats
        self.stats['items_written'] += 1
        self.stats['bytes_written'] += total_size
        
        return True
    
    def read(self) -> Optional[Tuple[float, int, bytes]]:
        """Read item from shared buffer."""
        # Read metadata
        write_pos = struct.unpack('!I', bytes(self.shm.buf[0:4]))[0]
        read_pos = struct.unpack('!I', bytes(self.shm.buf[4:8]))[0]
        size = struct.unpack('!I', bytes(self.shm.buf[8:12]))[0]
        
        # Check if data available
        if size < 12:  # Header size
            return None
        
        # Read header
        buffer_start = self.metadata_size + read_pos
        
        if read_pos + 12 <= self.capacity:
            header = bytes(self.shm.buf[buffer_start:buffer_start + 12])
        else:
            # Header wraps
            first_chunk = self.capacity - read_pos
            header = bytes(self.shm.buf[buffer_start:self.metadata_size + self.capacity])
            header += bytes(self.shm.buf[self.metadata_size:self.metadata_size + 12 - first_chunk])
        
        # Parse header
        timestamp, item_type, data_size = struct.unpack('!dHH', header)
        
        total_size = 12 + data_size
        if size < total_size:
            return None
        
        # Read data
        data_start = (read_pos + 12) % self.capacity
        
        if data_start + data_size <= self.capacity:
            data = bytes(self.shm.buf[self.metadata_size + data_start:self.metadata_size + data_start + data_size])
        else:
            # Data wraps
            first_chunk = self.capacity - data_start
            data = bytes(self.shm.buf[self.metadata_size + data_start:self.metadata_size + self.capacity])
            data += bytes(self.shm.buf[self.metadata_size:self.metadata_size + data_size - first_chunk])
        
        # Update metadata
        new_read_pos = (read_pos + total_size) % self.capacity
        self.shm.buf[4:8] = struct.pack('!I', new_read_pos)
        self.shm.buf[8:12] = struct.pack('!I', size - total_size)
        
        # Update stats
        self.stats['items_read'] += 1
        self.stats['bytes_read'] += total_size
        
        return timestamp, item_type, data
    
    def cleanup(self):
        """Clean up shared memory."""
        if self.shm:
            self.shm.close()
            try:
                self.shm.unlink()
            except:
                pass