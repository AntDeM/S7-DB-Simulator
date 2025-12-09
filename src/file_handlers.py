# pylint: disable=line-too-long
# pylint: disable=too-few-public-methods
"""
File handlers for loading and saving DB configurations.
Supports YAML and CSV file formats.
"""

import csv
from abc import ABC, abstractmethod

import yaml


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


def get_file_handler(file_path: str) -> DbFileHandler:
    """
    Returns the appropriate file handler based on file extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        DbFileHandler instance for the file type
        
    Raises:
        ValueError: If file type is not supported
    """
    if file_path.endswith('.yaml') or file_path.endswith('.yml'):
        return YamlFileHandler()
    if file_path.endswith('.csv'):
        return CsvFileHandler()
    raise ValueError(f"Unsupported file type: {file_path}")
