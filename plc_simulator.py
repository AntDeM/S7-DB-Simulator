# pylint: disable=line-too-long
# pylint: disable=too-few-public-methods
# pylint: disable=broad-exception-caught
# pylint: disable=raise-missing-from

import struct
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import ctypes
import os
import csv
import re
import traceback
from abc import ABC, abstractmethod
from typing import Any
import datetime
import yaml
from snap7.server import Server
from snap7.type import SrvArea, WordLen
from _version import __version__

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 500

# --- TYPE HANDLER OCP ---
class PlcTypeHandler(ABC):
    """Abstract base class for PLC type handlers. Defines the interface for packing, unpacking, and word length."""
    @abstractmethod
    def pack(self, value) -> bytes:
        """Pack a Python value into bytes for this PLC type."""
    @abstractmethod
    def unpack(self, data) -> Any:
        """Unpack bytes into a Python value for this PLC type."""
    @abstractmethod
    def word_length(self) -> int:
        """Return the snap7 WordLen constant for this PLC type."""

class BoolHandler(PlcTypeHandler):
    """Handler for BOOL PLC type."""
    def pack(self, value):
        """Pack a boolean value into a single byte."""
        return bytes([1 if value else 0])
    def unpack(self, data):
        """Unpack a single byte into a boolean value."""
        return bool(data[0])
    def word_length(self):
        """Return the WordLen for BOOL type."""
        return WordLen.Bit

class ByteHandler(PlcTypeHandler):
    """Handler for BYTE PLC type."""
    def pack(self, value):
        """Pack an integer value into a single byte."""
        return bytes([int(value) & 0xFF])
    def unpack(self, data):
        """Unpack a single byte into an integer value."""
        return data[0]
    def word_length(self):
        """Return the WordLen for BYTE type."""
        return WordLen.Byte

class WordHandler(PlcTypeHandler):
    """Handler for WORD PLC type."""
    def pack(self, value):
        """Pack an integer value into two bytes (WORD)."""
        return struct.pack('>H', int(value))
    def unpack(self, data):
        """Unpack two bytes into an integer value (WORD)."""
        return struct.unpack('>H', data[:2])[0]
    def word_length(self):
        """Return the WordLen for WORD type."""
        return WordLen.Word

class IntHandler(PlcTypeHandler):
    """Handler for INT PLC type."""
    def pack(self, value):
        """Pack an integer value into two bytes (INT)."""
        return struct.pack('>h', int(value))
    def unpack(self, data):
        """Unpack two bytes into an integer value (INT)."""
        return struct.unpack('>h', data[:2])[0]
    def word_length(self):
        """Return the WordLen for INT type."""
        return WordLen.Word

class DWordHandler(PlcTypeHandler):
    """Handler for DWORD PLC type."""
    def pack(self, value):
        """Pack an integer value into four bytes (DWORD)."""
        return struct.pack('>I', int(value))
    def unpack(self, data):
        """Unpack four bytes into an integer value (DWORD)."""
        return struct.unpack('>I', data[:4])[0]
    def word_length(self):
        """Return the WordLen for DWORD type."""
        return WordLen.DWord

class DIntHandler(PlcTypeHandler):
    """Handler for DINT PLC type."""
    def pack(self, value):
        """Pack an integer value into four bytes (DINT)."""
        return struct.pack('>i', int(value))
    def unpack(self, data):
        """Unpack four bytes into an integer value (DINT)."""
        return struct.unpack('>i', data[:4])[0]
    def word_length(self):
        """Return the WordLen for DINT type."""
        return WordLen.DWord

class RealHandler(PlcTypeHandler):
    """Handler for REAL PLC type."""
    def pack(self, value):
        """Pack a float value into four bytes (REAL)."""
        return struct.pack('>f', float(value))
    def unpack(self, data):
        """Unpack four bytes into a float value (REAL)."""
        if len(data) < 4:
            raise ValueError(f"Not enough bytes to read REAL value. Expected 4 bytes, got {len(data)}")
        try:
            return round(struct.unpack('>f', data[:4])[0], 2)
        except struct.error as e:
            raise ValueError(f"Failed to unpack REAL value: {e}")
    def word_length(self):
        """Return the WordLen for REAL type."""
        return WordLen.DWord

class StringHandler(PlcTypeHandler):
    """Handler for STRING[n] PLC type."""
    def __init__(self, max_len):
        """Initialize a STRING handler with a maximum length."""
        self.max_len = max_len
    def pack(self, value):
        """Pack a string value into bytes with S7 string header."""
        s = str(value)[:self.max_len].encode('ascii')
        return bytes([self.max_len, len(s)]) + s
    def unpack(self, data):
        """Unpack bytes into a string value, using S7 string header."""
        actual_len = data[1]
        return data[2:2+actual_len].decode('ascii')
    def word_length(self):
        """Return the WordLen for STRING type."""
        return WordLen.Byte

class DTHandler(PlcTypeHandler):
    """Handler for S7 DATE_AND_TIME (DT) type (8 bytes, BCD)."""
    def pack(self, value):
        if isinstance(value, str):
            # Accept 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS'
            try:
                value = datetime.datetime.strptime(value.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
            except Exception as e:
                raise ValueError(f"Invalid DT string: {value}") from e
        if not isinstance(value, datetime.datetime):
            raise ValueError("DT value must be datetime or string")
        # S7 DT is BCD encoded
        def to_bcd(val):
            return ((val // 10) << 4) | (val % 10)
        year = to_bcd(value.year % 100)
        month = to_bcd(value.month)
        day = to_bcd(value.day)
        hour = to_bcd(value.hour)
        minute = to_bcd(value.minute)
        second = to_bcd(value.second)
        ms = value.microsecond // 1000
        ms_high = to_bcd(ms // 10)  # 1/10s (high nibble)
        ms_low = to_bcd(ms % 10)    # 1/100s (low nibble)
        ms_byte = (ms_high << 4) | ms_low
        # Day of week: 1=Sunday, 7=Saturday
        dow = value.isoweekday() % 7 + 1
        dow_byte = to_bcd(dow) << 4
        return bytes([year, month, day, hour, minute, second, ms_byte, dow_byte])
    def unpack(self, data):
        def from_bcd(b):
            return ((b >> 4) * 10) + (b & 0x0F)
        year = from_bcd(data[0])
        month = from_bcd(data[1])
        day = from_bcd(data[2])
        hour = from_bcd(data[3])
        minute = from_bcd(data[4])
        second = from_bcd(data[5])
        ms = from_bcd(data[6] >> 4) * 10 + from_bcd(data[6] & 0x0F)
        microsecond = ms * 1000 # pylint: disable=unused-variable
        # Day of week is high nibble of data[7]
        # dow = from_bcd(data[7] >> 4)
        # Compose datetime (assume 2000+year for 2-digit year)
        year_full = 2000 + year if year < 90 else 1900 + year
        return f"{year_full:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{second:02d}"
    def word_length(self):
        return WordLen.DWord

class DTLHandler(PlcTypeHandler):
    """Handler for S7 DATE_AND_TIME_LONG (DTL) type (12 bytes, unsigned, S7 order)."""
    def pack(self, value):
        # Accept 'YYYY-MM-DD HH:MM:SS.ffffff W' (W=weekday, optional)
        if isinstance(value, str):
            parts = value.strip().split()
            if len(parts) == 3:
                dt_str, time_str, weekday = parts
            elif len(parts) == 2:
                dt_str, time_str = parts
                weekday = None
            else:
                raise ValueError(f"Invalid DTL string: {value}")
            if '.' in time_str:
                time_main, micro = time_str.split('.')
                micro = micro.ljust(6, '0')  # pad to microseconds
            else:
                time_main = time_str
                micro = '0'
            dt = datetime.datetime.strptime(f"{dt_str} {time_main}", "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(microsecond=int(micro))
            value = (dt, int(weekday) if weekday else dt.isoweekday() % 7 + 1)
        if isinstance(value, tuple):
            dt, weekday = value
        else:
            dt = value
            weekday = dt.isoweekday() % 7 + 1
        # S7 DTL: year(2), month(1), day(1), weekday(1), hour(1), min(1), sec(1), nanos(4)
        b = bytearray(12)
        b[0:2] = struct.pack('>H', dt.year)
        b[2] = dt.month
        b[3] = dt.day
        b[4] = weekday
        b[5] = dt.hour
        b[6] = dt.minute
        b[7] = dt.second
        nanos = dt.microsecond * 1000
        b[8:12] = struct.pack('>I', nanos)
        return bytes(b)
    def unpack(self, data):
        year = struct.unpack('>H', data[0:2])[0]
        month = data[2]
        day = data[3]
        weekday = data[4]
        hour = data[5]
        minute = data[6]
        second = data[7]
        nanos = struct.unpack('>I', data[8:12])[0]
        microsecond = nanos // 1000
        dt = datetime.datetime(year, month, day, hour, minute, second, microsecond)
        return f"{dt.strftime('%Y-%m-%d %H:%M:%S')}.{dt.microsecond:06d} {weekday}"
    def word_length(self):
        return WordLen.DWord

class WStringHandler(PlcTypeHandler):
    """Handler for WSTRING[n] PLC type (UTF-16BE, 2-byte max len, 2-byte actual len, n UTF-16BE code units, big-endian headers)."""
    def __init__(self, max_len):
        self.max_len = max_len
    def pack(self, value):
        s = str(value)[:self.max_len]
        encoded = s.encode('utf-16be')
        actual_len = len(encoded) // 2
        # S7 WSTRING: 2 bytes max len, 2 bytes actual len, then UTF-16BE chars, headers are big-endian
        return struct.pack('>HH', self.max_len, actual_len) + encoded
    def unpack(self, data):
        max_len, actual_len = struct.unpack('>HH', data[:4]) # pylint: disable=unused-variable
        return data[4:4+actual_len*2].decode('utf-16be')
    def word_length(self):
        # Each char is 2 bytes, but S7 treats as bytes for area access
        return WordLen.Byte

PLC_TYPE_HANDLERS = {
    'BOOL': BoolHandler(),
    'BYTE': ByteHandler(),
    'WORD': WordHandler(),
    'INT': IntHandler(),
    'DWORD': DWordHandler(),
    'DINT': DIntHandler(),
    'REAL': RealHandler(),
    'DT': DTHandler(),
    'DTL': DTLHandler(),
    # WSTRING is dynamic, handled in get_type_handler
}

def get_type_handler(type_):
    """
    Returns the appropriate PlcTypeHandler instance for the given PLC type string.
    Handles dynamic types such as STRING[n] and WSTRING[n] by instantiating a handler with the correct length.
    """
    type_upper = type_.upper()
    if type_upper.startswith('STRING['):
        max_len = int(type_upper[7:-1])
        return StringHandler(max_len)
    if type_upper.startswith('WSTRING['):
        max_len = int(type_upper[8:-1])
        return WStringHandler(max_len)
    if type_upper == 'DT':
        return PLC_TYPE_HANDLERS['DT']
    if type_upper == 'DTL':
        return PLC_TYPE_HANDLERS['DTL']
    return PLC_TYPE_HANDLERS[type_upper]

# --- FILE HANDLER OCP ---
class DbFileHandler(ABC):
    """Abstract base class for file handlers (YAML, CSV, etc)."""
    @abstractmethod
    def load(self, path):
        """Load and parse a file at the given path."""
    @abstractmethod
    def save(self, path, data):
        """Save data to a file at the given path."""

class YamlFileHandler(DbFileHandler):
    """Handler for YAML file format."""
    def load(self, path):
        """Load and parse a YAML file."""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    def save(self, path, data):
        """Save data to a YAML file."""
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f)

class CsvFileHandler(DbFileHandler):
    """Handler for CSV file format."""
    def load(self, path):
        """Load and parse a CSV file. (Not implemented)"""
        # Not implemented (optional)
        raise NotImplementedError("CSV loading not implemented.")
    def save(self, path, data):
        """Save data to a CSV file."""
        with open(path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["db_number", "name", "type", "offset", "bit", "value"])
            for db_def in data:
                db_number = db_def['db_number']
                for field in db_def['fields']:
                    name = field['name']
                    type_ = field['type']
                    offset = field['offset']
                    bit = field.get('bit', '')
                    val = field.get('value', '')
                    writer.writerow([db_number, name, type_, offset, bit, val])

def get_file_handler(file_path):
    if file_path.endswith('.yaml') or file_path.endswith('.yml'):
        return YamlFileHandler()
    if file_path.endswith('.csv'):
        return CsvFileHandler()
    raise ValueError(f"Unsupported file type: {file_path}")

def pack_value(value, type_):
    """
    Packs a Python value into bytes according to the PLC type string.
    """
    return get_type_handler(type_).pack(value)

def unpack_value(data, type_):
    """
    Unpacks bytes into a Python value according to the PLC type string.
    """
    return get_type_handler(type_).unpack(data)

def get_word_length(type_):
    """
    Returns the snap7 WordLen constant for the given PLC type string.
    """
    return get_type_handler(type_).word_length()

def sanity_check_config(config): #pylint: disable=too-many-statements
    """
    Checks the structure and content of the loaded YAML config for validity.
    Ensures required keys, supported types, and value compatibility.
    Raises ValueError if any check fails.
    """
    supported_types = {'BOOL', 'BYTE', 'WORD', 'INT', 'DWORD', 'DINT', 'REAL', 'DT', 'DTL'}
    string_type_re = re.compile(r'^STRING\[(\d+)\]$', re.IGNORECASE)
    wstring_type_re = re.compile(r'^WSTRING\[(\d+)\]$', re.IGNORECASE)

    def check_type_validity(type_):
        type_upper = type_.upper()
        if type_upper in supported_types:
            return True
        if string_type_re.match(type_upper) or wstring_type_re.match(type_upper):
            return True
        raise ValueError(f"Unsupported type {type_}")

    def check_offset_validity(offset, field_name, db_number):
        if not isinstance(offset, int) or offset < 0:
            raise ValueError(f"Invalid offset for field {field_name} in DB {db_number}")

    def check_value_compatibility(type_, value, field_name, db_number): #pylint: disable=too-many-statements, too-many-branches
        type_upper = type_.upper()
        try:
            if type_upper == 'BOOL':
                if not isinstance(value, (bool, int, str)):
                    raise ValueError()
                if isinstance(value, str) and value.lower() not in ('true', 'false', '1', '0', 'yes', 'no'):
                    raise ValueError()
            elif type_upper in {'BYTE', 'WORD', 'INT', 'DWORD', 'DINT'}:
                int(value)
            elif type_upper == 'REAL':
                float(value)
            elif type_upper == 'DT':
                if isinstance(value, str):
                    try:
                        datetime.datetime.strptime(value.replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        raise ValueError(f"Invalid DT string: {value}")
                elif not isinstance(value, datetime.datetime):
                    raise ValueError("DT value must be string or datetime")
            elif type_upper == 'DTL':
                if isinstance(value, str):
                    parts = value.strip().split()
                    if len(parts) not in (2, 3):
                        raise ValueError(f"Invalid DTL string: {value}")
                    dt_str, time_str = parts[0], parts[1]
                    if '.' in time_str:
                        time_main, micro = time_str.split('.')
                        micro = micro.ljust(6, '0')
                    else:
                        time_main = time_str
                        micro = '0'
                    try:
                        datetime.datetime.strptime(f"{dt_str} {time_main}", "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        raise ValueError(f"Invalid DTL string: {value}")
                elif not (isinstance(value, tuple) and isinstance(value[0], datetime.datetime)):
                    raise ValueError("DTL value must be string or (datetime, weekday) tuple")
            else:
                m = string_type_re.match(type_upper)
                if m:
                    max_len = int(m.group(1))
                    if not isinstance(value, str):
                        raise ValueError()
                    if len(value) > max_len:
                        raise ValueError(f"Value for field {field_name} in DB {db_number} exceeds STRING[{max_len}] length.")
                m2 = wstring_type_re.match(type_upper)
                if m2:
                    max_len = int(m2.group(1))
                    if not isinstance(value, str):
                        raise ValueError()
                    if len(value) > max_len:
                        raise ValueError(f"Value for field {field_name} in DB {db_number} exceeds WSTRING[{max_len}] length.")
        except Exception as exc:
            raise ValueError(f"Value {value} for field {field_name} in DB {db_number} is not compatible with type {type_upper}") from exc

    if not isinstance(config, dict):
        raise ValueError("YAML root must be a dictionary.")
    if 'dbs' not in config or not isinstance(config['dbs'], list):
        raise ValueError("YAML must contain a top-level 'dbs' list.")
    db_numbers = set()
    for db in config['dbs']:
        if 'db_number' not in db or 'fields' not in db:
            raise ValueError("Each DB must have 'db_number' and 'fields'.")
        if db['db_number'] in db_numbers:
            raise ValueError(f"Duplicate db_number: {db['db_number']}")
        db_numbers.add(db['db_number'])
        field_names = set()
        for field in db['fields']:
            if 'name' not in field or 'type' not in field or 'offset' not in field:
                raise ValueError(f"Each field must have 'name', 'type', and 'offset'. Problem in DB {db['db_number']}.")
            if field['name'] in field_names:
                raise ValueError(f"Duplicate field name {field['name']} in DB {db['db_number']}")
            field_names.add(field['name'])
            check_type_validity(field['type'])
            check_offset_validity(field['offset'], field['name'], db['db_number'])
            if 'value' in field:
                check_value_compatibility(field['type'], field['value'], field['name'], db['db_number'])
    return True

class IPlcSimulator(ABC):
    """Interface for PLC simulator operations."""
    @property
    @abstractmethod
    def db_data(self) -> dict:
        """Return the database data dictionary."""

    @property
    @abstractmethod
    def db_definitions(self) -> list:
        """Return the database definitions list."""

    @abstractmethod
    def read_value(self, db_number, offset, type_, bit=None):
        """Read a value from the specified DB, offset, and type."""

    @abstractmethod
    def write_value(self, db_number, offset, type_, value, bit=None):
        """Write a value to the specified DB, offset, and type."""

    @abstractmethod
    def stop(self):
        """Stop the PLC simulator/server."""

class IConfigLoader(ABC):
    """Interface for configuration file loaders."""
    @abstractmethod
    def load(self, path):
        """Load configuration from a file at the given path."""

class IConfigSaver(ABC):
    """Interface for configuration file savers."""
    @abstractmethod
    def save(self, path, data):
        """Save configuration data to a file at the given path."""

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

class PLCGui:
    """
    Tkinter GUI for viewing and editing PLC DBs. Supports loading, saving, and exporting DBs.
    """
    def __init__(self, root, simulator: IPlcSimulator | None, config_loader: IConfigLoader, config_saver: IConfigSaver):
        """
        Initializes the GUI. If a simulator is provided, loads its DBs.
        """
        self.root = root
        self.simulator = simulator
        self.config_loader = config_loader
        self.config_saver = config_saver
        self.db_data = simulator.db_data if simulator else {}
        self.db_definitions = simulator.db_definitions if simulator else []
        self.tables = {}
        self.current_yaml_path = None
        self.last_yaml_mtime = None
        self.file_check_interval_ms = 2000
        self.update_gui_id = None  # Track polling state
        self.build_toolbar()
        self.build_ui()
        if self.simulator:
            self.update_gui()
        self.check_file_modification()

    def build_toolbar(self):
        """
        Builds the toolbar with file operation buttons.
        """
        toolbar = ttk.Frame(self.root)
        toolbar.pack(fill='x')
        load_btn = ttk.Button(toolbar, text="Load DB", command=self.on_load_yaml)
        load_btn.pack(side='left', padx=2, pady=2)
        reload_btn = ttk.Button(toolbar, text="Reload DB", command=self.on_reload_yaml)
        reload_btn.pack(side='left', padx=2, pady=2)
        save_btn = ttk.Button(toolbar, text="Save", command=self.on_save_yaml)
        save_btn.pack(side='left', padx=2, pady=2)
        saveas_btn = ttk.Button(toolbar, text="Save As", command=self.on_saveas_yaml)
        saveas_btn.pack(side='left', padx=2, pady=2)
        export_csv_btn = ttk.Button(toolbar, text="Export CSV", command=self.on_export_csv)
        export_csv_btn.pack(side='left', padx=2, pady=2)

    def build_ui(self):
        """
        Builds the main notebook/tables for each DB. Clears previous tables if any.
        """
        try:
            # Remove previous widgets if any
            for widget in self.root.pack_slaves():
                if isinstance(widget, ttk.Notebook):
                    widget.destroy()

            self.tables.clear() # Clear stale table references

            if not self.db_definitions:
                return
            notebook = ttk.Notebook(self.root)
            notebook.pack(fill='both', expand=True)
            for db_def in self.db_definitions:
                db_number = db_def['db_number']
                if 'name' in db_def and db_def['name']:
                    tab_label = f"{db_def['name']} (DB{db_number})"
                else:
                    tab_label = f"DB{db_number}"
                frame = ttk.Frame(notebook)
                notebook.add(frame, text=tab_label)
                paned = ttk.PanedWindow(frame, orient='vertical')
                paned.pack(fill='both', expand=True)
                table_frame = ttk.Frame(paned)
                tree = ttk.Treeview(table_frame, columns=("Name", "Type", "Offset", "Bit", "Value"), show='headings')
                vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
                hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
                tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
                tree.grid(row=0, column=0, sticky='nsew')
                vsb.grid(row=0, column=1, sticky='ns')
                hsb.grid(row=1, column=0, sticky='ew')
                table_frame.grid_columnconfigure(0, weight=1)
                table_frame.grid_rowconfigure(0, weight=1)
                tree.heading("Name", text="Name")
                tree.heading("Type", text="Type")
                tree.heading("Offset", text="Offset")
                tree.heading("Bit", text="Bit")
                tree.heading("Value", text="Value")
                tree.column("Name", width=150)
                tree.column("Type", width=100)
                tree.column("Offset", width=70)
                tree.column("Bit", width=50)
                tree.column("Value", width=100)
                log_frame = ttk.Frame(paned)
                log_box = tk.Text(log_frame, height=5, state='disabled', bg='black', fg='white')
                log_box.pack(fill='both', expand=True)
                paned.add(table_frame, weight=3)
                paned.add(log_frame, weight=1)
                self.tables[db_number] = (tree, log_box)
                for field in db_def['fields']:
                    name = field['name']
                    type_ = field['type']
                    offset = field['offset']
                    bit = field.get('bit', '')
                    val = self.read_value(db_number, offset, type_, bit)
                    tree.insert('', 'end', iid=name, values=(name, type_, offset, bit, val))

                # Simplified binding, only passing the db_number
                tree.bind('<Double-1>', lambda e, db=db_number: self.on_edit(e, db))
                tree.bind('<Button-3>', lambda e, db=db_number: self.on_right_click(e, db))
        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("UI Error", f"Failed to build tables: {e}")

    def on_load_yaml(self):
        """
        Loads a YAML file, checks its validity, and updates the simulator and GUI.
        """
        file_path = filedialog.askopenfilename(
            title="Select YAML file",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if not file_path:
            return
        try:
            # Stop polling while loading new file
            if self.update_gui_id is not None:
                self.root.after_cancel(self.update_gui_id)
                self.update_gui_id = None
        except Exception:
            pass  # No poll scheduled yet or already canceled

        try:
            handler = get_file_handler(file_path)
            config = handler.load(file_path)
            sanity_check_config(config)
            simulator = PLCSimulator(file_path)
            self.simulator = simulator
            self.db_data = simulator.db_data
            self.db_definitions = simulator.db_definitions
            self.current_yaml_path = file_path
            self.last_yaml_mtime = os.path.getmtime(file_path)
            logger.info("Loaded db_definitions: %s", self.db_definitions)
            self.build_ui()
            self.update_gui()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load YAML: {e}")

    def on_reload_yaml(self):
        """
        Reloads the current YAML file, checks its validity, and updates the simulator and GUI.
        """
        if not self.current_yaml_path:
            messagebox.showwarning("Warning", "No YAML file loaded.")
            return
        try:
            # Stop polling while reloading
            if self.update_gui_id is not None:
                self.root.after_cancel(self.update_gui_id)
                self.update_gui_id = None
        except Exception:
            pass  # No poll scheduled yet or already canceled

        if self.simulator:
            try:
                self.simulator.stop()
            except Exception as e:
                logger.error("Error stopping previous simulator: %s", e)

        try:
            handler = get_file_handler(self.current_yaml_path)
            config = handler.load(self.current_yaml_path)
            sanity_check_config(config)
            simulator = PLCSimulator(self.current_yaml_path)
            self.simulator = simulator
            self.db_data = simulator.db_data
            self.db_definitions = simulator.db_definitions
            logger.info("Loaded db_definitions: %s", self.db_definitions)
            self.build_ui()
            self.last_yaml_mtime = os.path.getmtime(self.current_yaml_path)
            self.update_gui()  # Restart the GUI polling
            messagebox.showinfo("Success", "YAML file reloaded successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to reload YAML: {e}")

    def on_save_yaml(self):
        """
        Saves the current DBs to the loaded YAML file.
        """
        if not self.current_yaml_path:
            self.on_saveas_yaml()
            return
        try:
            self._export_to_file(self.current_yaml_path)
            self.last_yaml_mtime = os.path.getmtime(self.current_yaml_path)
            messagebox.showinfo("Saved", f"Saved to {os.path.basename(self.current_yaml_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save YAML: {e}")

    def on_saveas_yaml(self):
        """
        Prompts for a file path and saves the current DBs to YAML.
        """
        file_path = filedialog.asksaveasfilename(
            title="Save YAML as...",
            defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")]
        )
        if not file_path:
            return
        try:
            self._export_to_file(file_path)
            self.current_yaml_path = file_path
            self.last_yaml_mtime = os.path.getmtime(file_path)
            messagebox.showinfo("Saved", f"Saved to {os.path.basename(file_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save YAML: {e}")

    def _export_to_file(self, file_path):
        """
        Writes the current DBs to the specified file using the appropriate handler.
        """
        export = []
        for db_def in self.db_definitions:
            db_number = db_def['db_number']
            new_fields = []
            for field in db_def['fields']:
                name = field['name']
                type_ = field['type']
                offset = field['offset']
                bit = field.get('bit', None)
                val = self.read_value(db_number, offset, type_, bit)
                field_copy = {'name': name, 'type': type_, 'offset': offset, 'value': val}
                if bit is not None:
                    field_copy['bit'] = bit
                new_fields.append(field_copy)
            export.append({'db_number': db_number, 'fields': new_fields})
        handler = get_file_handler(file_path)
        if isinstance(handler, CsvFileHandler):
            handler.save(file_path, export)
        else:
            handler.save(file_path, {'dbs': export})

    def on_export_csv(self):
        """
        Prompts for a file path and exports the current DBs to CSV.
        """
        if not self.db_definitions:
            messagebox.showinfo("Info", "No data to export.")
            return
        file_path = filedialog.asksaveasfilename(
            title="Export CSV as...",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not file_path:
            return
        try:
            self._export_to_file(file_path)
            messagebox.showinfo("Exported", f"Exported to {os.path.basename(file_path)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export CSV: {e}")

    def check_file_modification(self):
        """
        Periodically checks if the loaded YAML file was modified externally and notifies the user.
        """
        if self.current_yaml_path and os.path.exists(self.current_yaml_path):
            mtime = os.path.getmtime(self.current_yaml_path)
            if self.last_yaml_mtime and mtime != self.last_yaml_mtime:
                self.last_yaml_mtime = mtime
                messagebox.showwarning(
                    "File Modified",
                    f"The YAML file '{os.path.basename(self.current_yaml_path)}' was modified outside the application. Click Reload to update."
                )
        self.root.after(self.file_check_interval_ms, self.check_file_modification)

    def append_log(self, log_box, message):
        """
        Appends a message to the log box for a DB tab.
        """
        log_box.config(state='normal')
        log_box.insert('end', message + '\n')
        log_box.see('end')
        log_box.config(state='disabled')

    def on_edit(self, event, db_number):
        """
        Handles double-click editing of a value cell in the table.
        """
        tree, log_box = self.tables[db_number]

        # Find the corresponding db_def from the master list to get the correct fields
        try:
            db_def = next(d for d in self.db_definitions if d['db_number'] == db_number)
            fields = db_def['fields']
        except StopIteration:
            self.append_log(log_box, f"Error: Could not find definition for DB {db_number}")
            return

        item = tree.identify_row(event.y)
        column = tree.identify_column(event.x)
        if column != '#5':
            return
        x, y, width, height = tree.bbox(item, column)
        old_value = tree.set(item, column)
        entry = tk.Entry(tree)
        entry.insert(0, old_value)
        entry.place(x=x, y=y, width=width, height=height)
        def on_enter(event):
            new_value = entry.get()
            # Look up the field in the freshly retrieved fields list
            field = next(f for f in fields if f['name'] == item)

            # Special handling for boolean values
            if field['type'].upper() == 'BOOL':
                # Convert input to proper boolean
                new_value_bool = new_value.lower() in ('true', '1', 'yes')
                self.write_value(db_number, field['offset'], field['type'], new_value_bool, field.get('bit'))
                tree.set(item, column, str(new_value_bool))
                self.append_log(log_box, f'Edited {item}: {old_value} → {new_value_bool}')
            else:
                self.write_value(db_number, field['offset'], field['type'], new_value, field.get('bit'))
                tree.set(item, column, new_value)
                self.append_log(log_box, f'Edited {item}: {old_value} → {new_value}')
            entry.destroy()
        entry.bind('<Return>', on_enter)
        entry.focus_set()

    def on_right_click(self, event, db_number):
        """
        Handles right-click context menu for toggling boolean values.
        """
        tree, log_box = self.tables[db_number]
        item = tree.identify_row(event.y)
        if not item:
            return

        # Select the row that was right-clicked
        tree.selection_set(item)

        # Find the corresponding db_def and field
        try:
            db_def = next(d for d in self.db_definitions if d['db_number'] == db_number)
            field = next(f for f in db_def['fields'] if f['name'] == item)
        except StopIteration:
            return

        # Only show context menu for BOOL type
        if field['type'].upper() != 'BOOL':
            return

        # Create context menu
        context_menu = tk.Menu(tree, tearoff=0)
        context_menu.add_command(
            label="Toggle Value",
            command=lambda: self.toggle_bool_value(db_number, item, field, tree, log_box)
        )
        context_menu.tk_popup(event.x_root, event.y_root)

    def toggle_bool_value(self, db_number, item, field, tree, log_box):
        """
        Toggles a boolean value in the DB and updates the GUI.
        """
        current_val = tree.set(item, 'Value')
        current_bool = current_val.lower() in ('true', '1', 'yes')
        new_bool = not current_bool

        self.write_value(db_number, field['offset'], field['type'], new_bool, field.get('bit'))
        tree.set(item, 'Value', str(new_bool))
        self.append_log(log_box, f'Toggled {item}: {current_bool} → {new_bool}')

    def read_value(self, db_number, offset, type_, bit=None):
        """
        Reads a value from the simulator for display in the GUI.
        """
        if self.simulator is None:
            return "<no simulator>"
        return self.simulator.read_value(db_number, offset, type_, bit)

    def write_value(self, db_number, offset, type_, value, bit=None):
        """
        Writes a value to the simulator from the GUI.
        """
        if self.simulator is None:
            return
        self.simulator.write_value(db_number, offset, type_, value, bit)

    def update_gui(self):
        """
        Periodically updates the GUI with the latest values from the simulator.
        """
        # Cancel any previous polling before starting a new one
        if hasattr(self, 'update_gui_id') and self.update_gui_id is not None:
            try:
                self.root.after_cancel(self.update_gui_id)
            except Exception:
                pass
            self.update_gui_id = None
        if not self.simulator:
            return
        try:
            for db_def in self.db_definitions:
                db_number = db_def['db_number']
                if db_number not in self.tables:
                    continue
                tree, log_box = self.tables[db_number]
                for field in db_def['fields']:
                    name = field['name']
                    type_ = field['type']
                    offset = field['offset']
                    bit = field.get('bit', None)
                    new_val = self.read_value(db_number, offset, type_, bit)
                    # Special handling for boolean values
                    if type_.upper() == 'BOOL':
                        new_val_bool = bool(new_val)
                        current_val = tree.set(name, 'Value')
                        current_val_bool = current_val.lower() in ('true', '1', 'yes')
                        if new_val_bool != current_val_bool:
                            tree.set(name, 'Value', str(new_val_bool))
                            self.append_log(log_box, f'Value Updated from client: {name} = {new_val_bool}')
                    else:
                        if str(new_val) != str(tree.set(name, 'Value')):
                            tree.set(name, 'Value', new_val)
                            self.append_log(log_box, f'Value Updated from client: {name} = {new_val}')
            # Schedule next poll
            self.update_gui_id = self.root.after(POLL_INTERVAL_MS, self.update_gui)
        except Exception as e:
            traceback.print_exc()
            self.update_gui_id = None
            messagebox.showerror("Polling Error", f"An error occurred during polling: {e}")

def start_simulator_with_gui():
    """
    Starts the PLC simulator GUI. If a config file is provided, it is ignored (GUI starts empty).
    """
    root = tk.Tk()
    root.title(f"PLC DB Simulator v{__version__}")

    class ConcreteConfigLoader(IConfigLoader):
        """Concrete implementation of IConfigLoader for loading YAML configuration files."""
        def load(self, path):
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)

    class ConcreteConfigSaver(IConfigSaver):
        """Concrete implementation of IConfigSaver for saving YAML configuration files."""
        def save(self, path, data):
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f)

    # Start with no simulator loaded
    PLCGui(root, None, ConcreteConfigLoader(), ConcreteConfigSaver())
    root.mainloop()

if __name__ == "__main__":
    start_simulator_with_gui()
