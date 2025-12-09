# pylint: disable=line-too-long
# pylint: disable=too-few-public-methods
"""
PLC Type Handlers for packing/unpacking S7 data types.
Provides handlers for BOOL, BYTE, WORD, INT, DWORD, DINT, REAL, STRING, WSTRING, DT, DTL.
"""

import struct
import datetime
from abc import ABC, abstractmethod
from typing import Any

from snap7.type import WordLen


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
        microsecond = ms * 1000  # pylint: disable=unused-variable
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
        max_len, actual_len = struct.unpack('>HH', data[:4])  # pylint: disable=unused-variable
        return data[4:4+actual_len*2].decode('utf-16be')
    def word_length(self):
        # Each char is 2 bytes, but S7 treats as bytes for area access
        return WordLen.Byte


# Registry of singleton handlers for non-parameterized types
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
    # STRING and WSTRING are dynamic, handled in get_type_handler
}


def get_type_handler(type_: str) -> PlcTypeHandler:
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


def pack_value(value, type_: str) -> bytes:
    """
    Packs a Python value into bytes according to the PLC type string.
    """
    return get_type_handler(type_).pack(value)


def unpack_value(data, type_: str):
    """
    Unpacks bytes into a Python value according to the PLC type string.
    """
    return get_type_handler(type_).unpack(data)


def get_word_length(type_: str) -> int:
    """
    Returns the snap7 WordLen constant for the given PLC type string.
    """
    return get_type_handler(type_).word_length()
