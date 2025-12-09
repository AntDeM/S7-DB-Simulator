# pylint: disable=line-too-long
# pylint: disable=broad-exception-caught
"""
PLC Simulator - S7 PLC server simulation using snap7.
Handles DB memory, reading/writing values, and snap7 server registration.
"""

import ctypes
import logging
from tkinter import messagebox

import yaml
from snap7.server import Server
from snap7.type import SrvArea

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
        self.server = Server(False)
        self.server.stop()  # Ensure server is stopped before configuration
        self._db_definitions = self.load_config(config_path)
        self._db_data = {}
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
        try:
            self.server.start(tcp_port=102)  # Standard S7 communication port
            logger.info("PLC Server started successfully")
        except Exception as e:
            logger.error("Failed to start server: %s", e)
            messagebox.showerror("Server Error", f"Failed to start PLC server: {e}")
            raise

    def _register_dbs(self):
        """
        Registers all DBs with the snap7 server.
        """
        for db_number, data in self.db_data.items():
            try:
                # Convert the data buffer to bytes before registering
                buffer = (ctypes.c_uint8 * len(data)).from_buffer(data)
                self.server.register_area(SrvArea.DB, db_number, buffer)
                logger.info("Registered DB %d with size %d bytes", db_number, len(data))
            except Exception as e:
                logger.error("Failed to register DB %d: %s", db_number, e)
                raise

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
        return self.db_data[db_number]

    def read_value(self, db_number, offset, type_, bit=None):
        """
        Reads a value from the specified DB, offset, and type. Handles BOOL bit if provided.
        """
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
        try:
            self.server.stop()
        except Exception as e:
            logger.error("Error stopping server: %s", e)
