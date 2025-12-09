# pylint: disable=line-too-long
# pylint: disable=too-few-public-methods
"""
Abstract interfaces for the PLC Simulator.
Defines contracts for simulator operations, config loading, and config saving.
"""

from abc import ABC, abstractmethod


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
