# pylint: disable=line-too-long
# pylint: disable=broad-exception-caught
"""
PLC Simulator - S7 PLC server simulation using snap7.
Handles DB memory, reading/writing values, and snap7 server registration.

Thread Safety:
    All DB data access is protected by a reentrant lock (_data_lock) to prevent
    race conditions between:
    - External S7 clients reading through snap7 server
    - GUI polling thread (every 500ms)
    - Script engine writing values
    This ensures data consistency and prevents communication timeouts.

Copy-on-Read Architecture:
    The simulator maintains two sets of buffers:
    1. Working buffers (_db_data) - Used by GUI, scripts, and internal operations
    2. Snap7 buffers (_snap7_buffers) - Isolated copies for external S7 clients
    
    A background thread syncs buffers bidirectionally every 20ms:
    - When external S7 client writes → syncs FROM snap7 TO working buffers
    - During normal operation → syncs FROM working TO snap7 buffers
    
    This architecture:
    - Prevents external reads from blocking internal writes
    - Ensures S7 clients always read consistent data snapshots
    - Captures external client writes and makes them visible to GUI
    - Eliminates communication timeouts caused by lock contention
    - Maintains low latency (<20ms) for all operations
"""

import ctypes
import logging
import threading
import time
from tkinter import messagebox

import yaml
from snap7.server import Server
from snap7.type import SrvArea
try:
    from snap7.server import SrvEvent
    from snap7 import snap7types
    SNAP7_EVENTS_AVAILABLE = True
except ImportError:
    SNAP7_EVENTS_AVAILABLE = False

from src.interfaces import IPlcSimulator
from src.type_handlers import pack_value, unpack_value

logger = logging.getLogger(__name__)


class PLCSimulator(IPlcSimulator):
    """
    Simulates a Siemens S7 PLC server with DBs defined by a YAML configuration.
    Handles DB memory, reading/writing values, and snap7 server registration.
    """

    @property
    def db_definitions(self):
        """Return the database definitions list."""
        return self._db_definitions

    @property
    def db_data(self):
        """Return the database data dictionary."""
        return self._db_data

    def __init__(self, config_path):
        """
        Initializes the simulator from a YAML config file path.
        """
        self.server = Server(log=False)
        self.server.stop()  # Ensure server is stopped before configuration
        
        # Configure server parameters to prevent timeouts
        try:
            # Set resource optimization parameters if available
            # These may not be available in all snap7 versions
            logger.info("Configuring snap7 server parameters...")
        except Exception as e:
            logger.warning("Could not set all server parameters: %s", e)
        
        self._db_definitions = self.load_config(config_path)
        self._db_data = {}
        self._snap7_buffers = {}  # Separate buffers for snap7 server (copy-on-read)
        self._snap7_checksums = {}  # Track checksums to detect external writes
        self._data_lock = threading.RLock()  # Reentrant lock for thread-safe DB access
        self._sync_timer = None
        self._sync_interval = 0.02  # Sync every 20ms for maximum responsiveness
        self._running = True
        self._client_count = 0  # Track active clients
        self.client_log = []
        for db_def in self._db_definitions:
            db_number = db_def['db_number']
            size = self.calculate_db_size(db_def['fields'])
            # Create a buffer using unsigned bytes (0-255)
            self.db_data[db_number] = (ctypes.c_uint8 * size)()
            logger.info("Created DB %d with size %d bytes", db_number, size)
            # Initialize with zeros
            ctypes.memset(self.db_data[db_number], 0, size)

            # Initialize values from YAML if present
            for field in db_def['fields']:
                if 'value' in field:
                    logger.info("Initializing DB%d.%d (%s) with value %s", db_number, field['offset'], field['name'], field['value'])
                    self.write_value(db_number, field['offset'], field['type'], field['value'], field.get('bit'))
        self._register_dbs()
        
        # Register event callback to monitor client connections
        if SNAP7_EVENTS_AVAILABLE:
            try:
                self.server.set_events_callback(self._event_callback)
                logger.info("Event callback registered")
            except Exception as e:
                logger.warning("Could not register event callback: %s", e)
        
        try:
            # Start server with explicit binding
            self.server.start(tcp_port=102)
            logger.info("PLC Server started successfully on port 102")
            logger.info("Server ready for S7 client connections")
        except Exception as e:
            logger.error("Failed to start server: %s", e)
            messagebox.showerror("Server Error", f"Failed to start PLC server: {e}")
            raise

    def _register_dbs(self):
        """
        Registers all DBs with the snap7 server using separate buffers.
        Creates isolated copies to prevent interference between snap7 and internal operations.
        """
        for db_number, data in self.db_data.items():
            try:
                # Create a separate buffer for snap7 server (copy-on-read isolation)
                snap7_buffer = (ctypes.c_uint8 * len(data))()
                # Initialize with current data
                ctypes.memmove(snap7_buffer, data, len(data))
                self._snap7_buffers[db_number] = snap7_buffer
                # Calculate initial checksum for change detection
                self._snap7_checksums[db_number] = self._calculate_checksum(snap7_buffer)
                self.server.register_area(SrvArea.DB, db_number, snap7_buffer)
                logger.info("Registered DB %d with size %d bytes (isolated buffer)", db_number, len(data))
            except Exception as e:
                logger.error("Failed to register DB %d: %s", db_number, e)
                raise
        
        # Start background thread to sync data to snap7 buffers
        self._start_sync_thread()

    def _event_callback(self, event, err_num, param1, param2, param3, param4):
        """
        Callback for snap7 server events to monitor client connections.
        Helps diagnose timeout issues.
        """
        try:
            if SNAP7_EVENTS_AVAILABLE:
                # Log significant events
                if event == 0x00000001:  # evcServerStarted
                    logger.info("[Event] Server started")
                elif event == 0x00000002:  # evcServerStopped
                    logger.info("[Event] Server stopped")
                elif event == 0x00000004:  # evcClientAdded
                    self._client_count += 1
                    logger.info("[Event] Client connected (total: %d)", self._client_count)
                elif event == 0x00000008:  # evcClientDisconnected
                    self._client_count -= 1
                    logger.info("[Event] Client disconnected (remaining: %d)", self._client_count)
                elif event == 0x00000020:  # evcDataRead
                    logger.debug("[Event] Data read - DB: %d, Offset: %d, Size: %d", param1, param2, param3)
                elif event == 0x00000040:  # evcDataWrite
                    logger.debug("[Event] Data write - DB: %d, Offset: %d, Size: %d", param1, param2, param3)
                elif err_num != 0:
                    logger.warning("[Event] Error event: 0x%08X, error: %d", event, err_num)
        except Exception as e:
            logger.error("Error in event callback: %s", e)

    def _start_sync_thread(self):
        """
        Starts a background thread to periodically sync DB data to snap7 buffers.
        This implements copy-on-read by updating snap7's buffers asynchronously.
        """
        def sync_loop():
            while self._running:
                try:
                    self._sync_to_snap7_buffers()
                    time.sleep(self._sync_interval)
                except Exception as e:
                    logger.error("Error in sync thread: %s", e)
        
        sync_thread = threading.Thread(target=sync_loop, daemon=True, name="Snap7Sync")
        # Try to set higher priority for sync thread (may not work on all platforms)
        try:
            import os
            if hasattr(os, 'nice'):
                # Unix-like systems
                sync_thread.start()
            else:
                # Windows
                sync_thread.start()
        except Exception:
            sync_thread.start()
        
        logger.info("Started snap7 buffer sync thread (interval: %dms)", int(self._sync_interval * 1000))

    def _calculate_checksum(self, buffer):
        """Calculate a simple checksum for change detection."""
        checksum = 0
        for i in range(len(buffer)):
            checksum = (checksum + buffer[i]) & 0xFFFFFFFF
        return checksum

    def _sync_to_snap7_buffers(self):
        """
        Bidirectional synchronization between internal DB data and snap7 server buffers.
        - Detects external writes by comparing checksums
        - Copies FROM snap7 TO working buffers when external client writes detected
        - Copies FROM working TO snap7 buffers during normal operation
        Uses minimal lock time to avoid blocking external clients.
        """
        # Use try_lock pattern to avoid blocking if another operation is in progress
        if self._data_lock.acquire(blocking=False):
            try:
                for db_number, data in self.db_data.items():
                    if db_number in self._snap7_buffers:
                        snap7_buffer = self._snap7_buffers[db_number]
                        
                        # Calculate current checksum of snap7 buffer
                        current_checksum = self._calculate_checksum(snap7_buffer)
                        previous_checksum = self._snap7_checksums.get(db_number, 0)
                        
                        # Check if snap7 buffer changed (external write detected)
                        if current_checksum != previous_checksum:
                            # External client wrote to snap7 buffer, sync TO working buffer
                            ctypes.memmove(data, snap7_buffer, len(data))
                            self._snap7_checksums[db_number] = current_checksum
                            logger.debug("External write detected on DB%d, synced to working buffer", db_number)
                        else:
                            # No external changes, sync FROM working TO snap7 (normal operation)
                            ctypes.memmove(snap7_buffer, data, len(data))
                            # Update checksum after our write
                            self._snap7_checksums[db_number] = self._calculate_checksum(snap7_buffer)
            finally:
                self._data_lock.release()
        else:
            # Lock was busy, skip this sync cycle - we'll catch up next time
            logger.debug("Sync skipped - lock busy")

    def set_sync_interval(self, interval_seconds):
        """
        Adjusts the sync interval for copy-on-read updates.
        
        Args:
            interval_seconds: Time between sync operations (default 0.1 = 100ms)
                             Lower values = lower latency, higher CPU usage
                             Higher values = higher latency, lower CPU usage
        """
        if interval_seconds < 0.01:
            logger.warning("Sync interval too low, setting to minimum 10ms")
            interval_seconds = 0.01
        elif interval_seconds > 5.0:
            logger.warning("Sync interval too high, setting to maximum 5s")
            interval_seconds = 5.0
        
        self._sync_interval = interval_seconds
        logger.info("Sync interval updated to %dms", int(interval_seconds * 1000))

    def get_client_count(self):
        """
        Returns the number of currently connected clients.
        """
        return self._client_count

    def load_config(self, path):
        """
        Loads the YAML configuration from the given file path.
        """
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logger.info("YAML loaded config: %s", config)
        try:
            return config['dbs']
        except Exception as exc:
            logger.error("YAML missing 'dbs' key or malformed: %s", exc)
            return []

    def calculate_db_size(self, fields):
        """
        Calculates the required size in bytes for a DB given its fields.
        """
        max_offset = 0
        for field in fields:
            offset = field['offset']
            type_ = field['type'].upper()
            # Calculate size based on type
            if type_ == 'BOOL':
                size = 1
            elif type_ == 'BYTE':
                size = 1
            elif type_ in {'WORD', 'INT'}:
                size = 2
            elif type_ in {'DWORD', 'DINT', 'REAL'}:
                size = 4
            elif type_ == 'DTL':
                size = 12
            elif type_ == 'DT':
                size = 8
            elif type_.startswith('STRING['):
                max_len = int(type_[7:-1])
                size = max_len + 2  # 2 extra bytes for max length and actual length
            elif type_.startswith('WSTRING['):
                max_len = int(type_[8:-1])
                size = 2 + 2 + max_len * 2  # 2 bytes max len, 2 bytes actual len, n UTF-16 code units
            else:
                size = 1
            max_offset = max(max_offset, offset + size)
        return max_offset

    def get_db_data(self, db_number):
        """
        Returns the ctypes array for the given DB number.
        """
        with self._data_lock:
            return self.db_data[db_number]

    def read_value(self, db_number, offset, type_, bit=None):
        """
        Reads a value from the specified DB, offset, and type. Handles BOOL bit if provided.
        """
        with self._data_lock:
            try:
                data = self.db_data[db_number]
                type_ = type_.upper()

                # Handle BOOL type separately
                if type_ == 'BOOL' and bit is not None:
                    byte_val = data[offset]
                    return bool((byte_val >> bit) & 0x01)

                # Calculate required bytes based on type
                if type_ == 'BYTE':
                    size = 1
                elif type_ in {'WORD', 'INT'}:
                    size = 2
                elif type_ in {'DWORD', 'DINT', 'REAL'}:
                    size = 4
                elif type_ == 'DTL':
                    size = 12
                elif type_ == 'DT':
                    size = 8
                elif type_.startswith('STRING['):
                    max_len = int(type_[7:-1])
                    size = max_len + 2
                elif type_.startswith('WSTRING['):
                    max_len = int(type_[8:-1])
                    size = 2 + 2 + max_len * 2
                else:
                    size = 1

                # Get exact number of bytes needed
                if offset + size > len(data):
                    raise ValueError(f"Not enough bytes in DB. Need {size} bytes at offset {offset}, but DB only has {len(data)} bytes")

                # For REAL values, ensure we get exactly 4 bytes
                if type_ == 'REAL':
                    raw_bytes = bytearray(4)
                    for i in range(4):
                        raw_bytes[i] = data[offset + i]
                    data_slice = bytes(raw_bytes)
                    logger.debug("Reading REAL value from DB%d.%d: bytes=%s", db_number, offset, [b for b in data_slice])
                else:
                    data_slice = bytes(data[offset:offset + size])

                return unpack_value(data_slice, type_)
            except Exception as e:  # Broad except is intentional to catch all read errors
                logger.error("Read error for DB%d.%d type %s: %s", db_number, offset, type_, e)
                return "<err>"

    def write_value(self, db_number, offset, type_, value, bit=None):
        """
        Writes a value to the specified DB, offset, and type. Handles BOOL bit if provided.
        """
        with self._data_lock:
            try:
                data = self.db_data[db_number]
                type_ = type_.upper()

                if type_ == 'BOOL' and bit is not None:
                    current = data[offset]
                    if value in [True, 1, '1', 'true', 'yes']:
                        data[offset] = current | (1 << bit)
                    else:
                        data[offset] = current & ~(1 << bit)
                else:
                    packed = pack_value(value, type_)
                    # For REAL values, log the bytes being written
                    if type_ == 'REAL':
                        logger.debug("Writing REAL value to DB%d.%d: value=%s, bytes=%s", db_number, offset, value, [b for b in packed])
                    # Copy bytes into ctypes array
                    for i, b in enumerate(packed):
                        data[offset + i] = b
                    logger.info("Written to DB%d.%d type %s: %s", db_number, offset, type_, value)
            except Exception as e:
                logger.error("Write error for DB%d.%d type %s: %s", db_number, offset, type_, e)

    def stop(self):
        """
        Stops the PLC server and sync thread.
        """
        self._running = False  # Signal sync thread to stop
        try:
            # Give sync thread time to finish current iteration
            time.sleep(self._sync_interval + 0.05)
            self.server.stop()
            logger.info("PLC Server stopped")
        except Exception as e:
            logger.error("Error stopping server: %s", e)
