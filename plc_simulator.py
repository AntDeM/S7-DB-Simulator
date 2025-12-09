"""
PLC DB Simulator - Main entry point.
Starts the PLC simulator GUI application.
"""

import logging
import tkinter as tk

import yaml

from _version import __version__
from src.interfaces import IConfigLoader, IConfigSaver
from src.gui import PLCGui

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


def start_simulator_with_gui():
    """
    Starts the PLC simulator GUI. If a config file is provided, it is ignored (GUI starts empty).
    """
    root = tk.Tk()
    root.title(f"PLC DB Simulator v{__version__}")

    # Start with no simulator loaded
    PLCGui(root, None, ConcreteConfigLoader(), ConcreteConfigSaver())
    root.mainloop()


if __name__ == "__main__":
    start_simulator_with_gui()
