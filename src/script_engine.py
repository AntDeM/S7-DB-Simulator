# pylint: disable=line-too-long
# pylint: disable=broad-exception-caught
"""
Script Engine for PLC Simulator.
Parses and executes human-readable script files for automating DB variable operations.

Script Syntax:
    SET <db_number>.<variable_name> = <value>
    WAIT <milliseconds>
    WAIT_UNTIL <db_number>.<variable_name> <operator> <value> [TIMEOUT <ms>]
    LOOP <count>
        <commands>
    END_LOOP
    # Comment line

Operators for WAIT_UNTIL: ==, !=, >, <, >=, <=

Example:
    # Set motor to running
    SET 1.MotorStatus = true
    WAIT 1000
    WAIT_UNTIL 1.Temperature > 50 TIMEOUT 5000
    LOOP 3
        SET 1.Counter = 0
        WAIT 500
    END_LOOP
"""

import re
import time
import logging
import threading
from datetime import datetime
from enum import Enum
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


class CommandType(Enum):
    """Types of script commands."""
    SET = "SET"
    WAIT = "WAIT"
    WAIT_UNTIL = "WAIT_UNTIL"
    LOOP = "LOOP"
    END_LOOP = "END_LOOP"
    COMMENT = "COMMENT"
    EMPTY = "EMPTY"


@dataclass
class ScriptCommand:
    """Represents a parsed script command."""
    line_number: int
    command_type: CommandType
    raw_text: str
    db_number: int | None = None
    variable_name: str | None = None
    value: str | None = None
    operator: str | None = None
    wait_ms: int | None = None
    loop_count: int | None = None
    timeout_ms: int | None = None


class ScriptParseError(Exception):
    """Exception raised when script parsing fails."""
    def __init__(self, line_number: int, message: str):
        self.line_number = line_number
        self.message = message
        super().__init__(f"Line {line_number}: {message}")


class ScriptEngine:
    """
    Engine for parsing and executing PLC simulator scripts.
    Runs scripts in a background thread with start/stop control.
    """

    # Regex patterns for parsing commands
    SET_PATTERN = re.compile(r'^SET\s+(\d+)\.(\w+)\s*=\s*(.+)$', re.IGNORECASE)
    WAIT_PATTERN = re.compile(r'^WAIT\s+(\d+)$', re.IGNORECASE)
    WAIT_UNTIL_PATTERN = re.compile(
        r'^WAIT_UNTIL\s+(\d+)\.(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+?)(?:\s+TIMEOUT\s+(\d+))?$',
        re.IGNORECASE
    )
    LOOP_PATTERN = re.compile(r'^LOOP\s+(\d+)$', re.IGNORECASE)
    END_LOOP_PATTERN = re.compile(r'^END_LOOP$', re.IGNORECASE)

    def __init__(self, simulator, log_callback: Callable[[str], None] | None = None):
        """
        Initialize the script engine.

        Args:
            simulator: The PLC simulator instance for reading/writing values
            log_callback: Optional callback function for logging messages to UI
        """
        self.simulator = simulator
        self.log_callback = log_callback
        self.commands: list[ScriptCommand] = []
        self.running = False
        self.stop_requested = False
        self.thread: threading.Thread | None = None
        self.current_line = 0
        self.script_path: str | None = None

    def log(self, message: str):
        """Log a message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        log_message = f"[{timestamp}] {message}"
        logger.info(log_message)
        if self.log_callback:
            self.log_callback(log_message)

    def parse_script(self, script_path: str) -> list[ScriptCommand]:
        """
        Parse a script file into a list of commands.

        Args:
            script_path: Path to the script file

        Returns:
            List of parsed ScriptCommand objects

        Raises:
            ScriptParseError: If the script contains syntax errors
        """
        commands = []
        loop_stack = []  # Track nested loops

        with open(script_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for line_num, line in enumerate(lines, start=1):
            line = line.strip()

            # Empty line
            if not line:
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.EMPTY,
                    raw_text=line
                ))
                continue

            # Comment
            if line.startswith('#'):
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.COMMENT,
                    raw_text=line
                ))
                continue

            # SET command
            match = self.SET_PATTERN.match(line)
            if match:
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.SET,
                    raw_text=line,
                    db_number=int(match.group(1)),
                    variable_name=match.group(2),
                    value=match.group(3).strip()
                ))
                continue

            # WAIT command
            match = self.WAIT_PATTERN.match(line)
            if match:
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.WAIT,
                    raw_text=line,
                    wait_ms=int(match.group(1))
                ))
                continue

            # WAIT_UNTIL command
            match = self.WAIT_UNTIL_PATTERN.match(line)
            if match:
                timeout = int(match.group(5)) if match.group(5) else None
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.WAIT_UNTIL,
                    raw_text=line,
                    db_number=int(match.group(1)),
                    variable_name=match.group(2),
                    operator=match.group(3),
                    value=match.group(4).strip(),
                    timeout_ms=timeout
                ))
                continue

            # LOOP command
            match = self.LOOP_PATTERN.match(line)
            if match:
                loop_cmd = ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.LOOP,
                    raw_text=line,
                    loop_count=int(match.group(1))
                )
                commands.append(loop_cmd)
                loop_stack.append(line_num)
                continue

            # END_LOOP command
            match = self.END_LOOP_PATTERN.match(line)
            if match:
                if not loop_stack:
                    raise ScriptParseError(line_num, "END_LOOP without matching LOOP")
                loop_stack.pop()
                commands.append(ScriptCommand(
                    line_number=line_num,
                    command_type=CommandType.END_LOOP,
                    raw_text=line
                ))
                continue

            # Unknown command
            raise ScriptParseError(line_num, f"Unknown command: {line}")

        # Check for unclosed loops
        if loop_stack:
            raise ScriptParseError(loop_stack[-1], "LOOP without matching END_LOOP")

        return commands

    def load_script(self, script_path: str) -> bool:
        """
        Load and parse a script file.

        Args:
            script_path: Path to the script file

        Returns:
            True if script loaded successfully, False otherwise
        """
        try:
            self.commands = self.parse_script(script_path)
            self.script_path = script_path
            self.log(f"Script loaded: {script_path} ({len([c for c in self.commands if c.command_type not in (CommandType.EMPTY, CommandType.COMMENT)])} commands)")
            return True
        except ScriptParseError as e:
            self.log(f"Script parse error - {e}")
            return False
        except Exception as e:
            self.log(f"Failed to load script: {e}")
            return False

    def _get_field_info(self, db_number: int, variable_name: str):
        """Get field info (type, offset, bit) for a variable."""
        for db_def in self.simulator.db_definitions:
            if db_def['db_number'] == db_number:
                for field in db_def['fields']:
                    if field['name'] == variable_name:
                        return field
        return None

    def _parse_value(self, value_str: str, field_type: str):
        """Parse a string value according to the field type."""
        field_type_upper = field_type.upper()

        if field_type_upper == 'BOOL':
            return value_str.lower() in ('true', '1', 'yes')
        elif field_type_upper in ('BYTE', 'WORD', 'INT', 'DWORD', 'DINT'):
            return int(value_str)
        elif field_type_upper == 'REAL':
            return float(value_str)
        else:
            # String types - remove quotes if present
            if (value_str.startswith('"') and value_str.endswith('"')) or \
               (value_str.startswith("'") and value_str.endswith("'")):
                return value_str[1:-1]
            return value_str

    def _compare_values(self, actual, operator: str, expected) -> bool:
        """Compare two values using the specified operator."""
        try:
            if operator == '==':
                return actual == expected
            elif operator == '!=':
                return actual != expected
            elif operator == '>':
                return actual > expected
            elif operator == '<':
                return actual < expected
            elif operator == '>=':
                return actual >= expected
            elif operator == '<=':
                return actual <= expected
        except TypeError:
            return False
        return False

    def _execute_set(self, cmd: ScriptCommand):
        """Execute a SET command."""
        field = self._get_field_info(cmd.db_number, cmd.variable_name)
        if not field:
            self.log(f"ERROR: Variable {cmd.db_number}.{cmd.variable_name} not found")
            return False

        value = self._parse_value(cmd.value, field['type'])
        self.simulator.write_value(
            cmd.db_number,
            field['offset'],
            field['type'],
            value,
            field.get('bit')
        )
        self.log(f"SET {cmd.db_number}.{cmd.variable_name} = {value}")
        return True

    def _execute_wait(self, cmd: ScriptCommand):
        """Execute a WAIT command."""
        self.log(f"WAIT {cmd.wait_ms}ms")
        # Sleep in small increments to allow for stop requests
        elapsed = 0
        increment = 50  # Check every 50ms
        while elapsed < cmd.wait_ms and not self.stop_requested:
            time.sleep(min(increment, cmd.wait_ms - elapsed) / 1000)
            elapsed += increment
        return not self.stop_requested

    def _execute_wait_until(self, cmd: ScriptCommand):
        """Execute a WAIT_UNTIL command."""
        field = self._get_field_info(cmd.db_number, cmd.variable_name)
        if not field:
            self.log(f"ERROR: Variable {cmd.db_number}.{cmd.variable_name} not found")
            return False

        expected_value = self._parse_value(cmd.value, field['type'])
        timeout_str = f" (timeout: {cmd.timeout_ms}ms)" if cmd.timeout_ms else ""
        self.log(f"WAIT_UNTIL {cmd.db_number}.{cmd.variable_name} {cmd.operator} {expected_value}{timeout_str}")

        start_time = time.time()
        poll_interval = 50  # Poll every 50ms

        while not self.stop_requested:
            actual_value = self.simulator.read_value(
                cmd.db_number,
                field['offset'],
                field['type'],
                field.get('bit')
            )

            if self._compare_values(actual_value, cmd.operator, expected_value):
                self.log(f"  Condition met: {actual_value} {cmd.operator} {expected_value}")
                return True

            # Check timeout
            if cmd.timeout_ms:
                elapsed = (time.time() - start_time) * 1000
                if elapsed >= cmd.timeout_ms:
                    self.log(f"  TIMEOUT: Condition not met after {cmd.timeout_ms}ms (current value: {actual_value})")
                    return True  # Continue script execution after timeout

            time.sleep(poll_interval / 1000)

        return False

    def _execute_commands(self, commands: list[ScriptCommand], start_idx: int = 0) -> int:
        """
        Execute a list of commands starting from the given index.

        Returns:
            The index after the last executed command, or -1 if stopped
        """
        idx = start_idx

        while idx < len(commands) and not self.stop_requested:
            cmd = commands[idx]
            self.current_line = cmd.line_number

            if cmd.command_type == CommandType.EMPTY or cmd.command_type == CommandType.COMMENT:
                idx += 1
                continue

            if cmd.command_type == CommandType.SET:
                if not self._execute_set(cmd):
                    return -1
                idx += 1

            elif cmd.command_type == CommandType.WAIT:
                if not self._execute_wait(cmd):
                    return -1
                idx += 1

            elif cmd.command_type == CommandType.WAIT_UNTIL:
                if not self._execute_wait_until(cmd):
                    return -1
                idx += 1

            elif cmd.command_type == CommandType.LOOP:
                # Find matching END_LOOP
                loop_start = idx + 1
                loop_depth = 1
                loop_end = idx + 1

                while loop_end < len(commands) and loop_depth > 0:
                    if commands[loop_end].command_type == CommandType.LOOP:
                        loop_depth += 1
                    elif commands[loop_end].command_type == CommandType.END_LOOP:
                        loop_depth -= 1
                    loop_end += 1

                # Execute loop body
                self.log(f"LOOP {cmd.loop_count} iterations")
                for iteration in range(cmd.loop_count):
                    if self.stop_requested:
                        return -1
                    self.log(f"  Iteration {iteration + 1}/{cmd.loop_count}")
                    # Execute commands between LOOP and END_LOOP
                    loop_commands = commands[loop_start:loop_end - 1]
                    result = self._execute_commands(commands, loop_start)
                    if result == -1:
                        return -1
                    # Break out if we've reached END_LOOP
                    if result >= loop_end - 1:
                        continue

                idx = loop_end

            elif cmd.command_type == CommandType.END_LOOP:
                # Return to caller (loop handler)
                return idx

            else:
                idx += 1

        return idx

    def _run_script(self):
        """Internal method to run the script in a thread."""
        self.log("Script execution started")
        try:
            self._execute_commands(self.commands)
            if self.stop_requested:
                self.log("Script execution stopped by user")
            else:
                self.log("Script execution completed")
        except Exception as e:
            self.log(f"Script execution error: {e}")
            logger.exception("Script execution error")
        finally:
            self.running = False
            self.stop_requested = False

    def start(self) -> bool:
        """
        Start script execution in a background thread.

        Returns:
            True if script started, False if already running or no script loaded
        """
        if self.running:
            self.log("Script is already running")
            return False

        if not self.commands:
            self.log("No script loaded")
            return False

        if not self.simulator:
            self.log("No simulator available")
            return False

        self.running = True
        self.stop_requested = False
        self.thread = threading.Thread(target=self._run_script, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        """Request the script to stop execution."""
        if self.running:
            self.log("Stopping script...")
            self.stop_requested = True

    def is_running(self) -> bool:
        """Check if the script is currently running."""
        return self.running
