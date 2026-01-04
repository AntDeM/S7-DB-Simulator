A Siemens S7 DB simulator using Snap7

# Project Structure

```
S7-DB-Simulator/
├── plc_simulator.py      # Main entry point
├── src/
│   ├── __init__.py       # Package exports
│   ├── interfaces.py     # Abstract interfaces (IPlcSimulator, IConfigLoader, IConfigSaver)
│   ├── type_handlers.py  # PLC type handlers (BOOL, BYTE, WORD, INT, REAL, STRING, etc.)
│   ├── file_handlers.py  # File I/O handlers (YAML, CSV)
│   ├── config_validator.py # Configuration validation
│   ├── simulator.py      # PLCSimulator class (snap7 server)
│   └── gui.py            # PLCGui class (Tkinter GUI)
├── _version.py           # Version info
├── db_example.yaml       # Example DB configuration
├── requirements.txt      # Python dependencies
└── installer.nsi         # NSIS installer script
```


# Setup

pip install -r requirements.txt

# Build

pyinstaller plc_simulator.spec

# Create the installer using NSIS

- Install NSIS (Nullsoft Scriptable Install System)
- Right-click on the installer.nsi file
- Select "Compile NSIS Script"
- This will create "PLC DB Simulator Setup.exe" in your project directory

## User Manual

### Overview

**PLC DB Simulator** is a graphical tool to simulate Siemens S7 PLC Data Blocks (DBs).  
You can load, edit, and save DB definitions in YAML format, and export them to CSV for further processing.

### Main Features

- Load, edit, and save PLC DBs from YAML files.
- Live view and edit of DB values in a table.
- Detects external changes to the loaded YAML and notifies you.
- Export the current DBs to CSV.
- **Scripting support** for automated DB variable operations.

### How to Use

1. **Start the Application**
   - Run `python plc_simulator.py` or use the built executable.

2. **Toolbar Functions**
   - **Load DB**: Open a DB configuration YAML file.
   - **Reload DB**: Reload the current YAML file (useful if edited externally).
   - **Save**: Save changes to the current YAML file.
   - **Save As**: Save the current DBs to a new YAML file.
   - **Export CSV**: Export the current DBs to a CSV file.
   - **Load Script**: Load a script file for automation.
   - **▶ Start**: Start script execution.
   - **■ Stop**: Stop script execution.

3. **Editing Values**
   - Double-click a value cell in the table to edit it.
   - For BOOL types, enter `true`/`false`, `1`/`0`, `yes`/`no`.

4. **External Edits**
   - If the loaded YAML file is changed outside the app, you'll be notified and can reload it.

### Example YAML

```yaml
dbs:
  - db_number: 1
    fields:
      - name: MotorStatus
        type: BOOL
        offset: 0
        bit: 0
        value: true
      - name: Setpoint
        type: REAL
        offset: 2
        value: 42.5
      - name: Description
        type: STRING[20]
        offset: 6
        value: "Main motor"
      - name: OperatorName
        type: WSTRING[16]
        offset: 28
        value: "Jürgen Müller"
      - name: Calibration Date
        type: DTL
        offset: 26
        value: "2024-07-20 14:01:00.123123"
  - db_number: 2
    fields:
      - name: Counter
        type: DINT
        offset: 0
        value: 12345
```

### WSTRING[n] Support

The simulator supports Siemens S7 `WSTRING[n]` fields:

- **Encoding:** UTF-16BE (big-endian, 2 bytes per character)
- **Header:** 2 bytes for max length, 2 bytes for actual length (both big-endian)
- **Usage:**
  - In YAML, use `type: WSTRING[n]` (e.g., `WSTRING[16]`).
  - The value can be any Unicode string up to `n` characters.
  - Example: `type: WSTRING[16]`, `value: "Jürgen Müller"`

**Note:** The offset for a WSTRING field must have enough space for 2 bytes (max len) + 2 bytes (actual len) + `n*2` bytes (characters).

### Example CSV Export

The exported CSV will look like:

```
db_number,name,type,offset,bit,value
1,MotorStatus,BOOL,0,0,True
1,Setpoint,REAL,2,,42.5
1,Description,STRING[20],6,,Main motor
2,Counter,DINT,0,,12345
```

---

## Scripting

The simulator supports automation through human-readable script files. Scripts allow you to automate sequences of operations on DB variables.

### Script File Format

Script files are plain text files (`.script` or `.txt`) with one command per line. Comments start with `#`.

### Available Commands

| Command | Description | Example |
|---------|-------------|---------|
| `SET` | Set a variable value | `SET 1.MotorStatus = true` |
| `WAIT` | Wait for specified milliseconds | `WAIT 1000` |
| `WAIT_UNTIL` | Wait until condition is met | `WAIT_UNTIL 1.Temperature > 50 TIMEOUT 5000` |
| `LOOP` / `END_LOOP` | Repeat commands N times | `LOOP 3` ... `END_LOOP` |

### Command Syntax

#### SET
```
SET <db_number>.<variable_name> = <value>
```
Sets a DB variable to the specified value.
- For BOOL: `true`, `false`, `1`, `0`, `yes`, `no`
- For numeric types: integer or decimal number
- For strings: text (quotes optional)

#### WAIT
```
WAIT <milliseconds>
```
Pauses script execution for the specified time.

#### WAIT_UNTIL
```
WAIT_UNTIL <db_number>.<variable_name> <operator> <value> [TIMEOUT <ms>]
```
Waits until the condition is met. Operators: `==`, `!=`, `>`, `<`, `>=`, `<=`

The optional `TIMEOUT` specifies maximum wait time in milliseconds. If timeout is reached, script continues.

#### LOOP / END_LOOP
```
LOOP <count>
    <commands>
END_LOOP
```
Repeats the enclosed commands the specified number of times. Loops can be nested.

### Example Script

```
# Example PLC Simulator Script

# Set initial values
SET 1.MotorStatus = true
SET 1.Setpoint = 25.5

# Wait for 1 second
WAIT 1000

# Wait until temperature exceeds 50 (with 5 second timeout)
WAIT_UNTIL 1.Temperature > 50 TIMEOUT 5000

# Loop example - cycle 3 times
LOOP 3
    SET 1.Counter = 100
    WAIT 500
    SET 1.Counter = 200
    WAIT 500
END_LOOP

# Final state
SET 1.MotorStatus = false
```

### Running Scripts

1. Load a DB configuration first (Load DB button)
2. Click "Load Script" and select your script file
3. Click "▶ Start" to begin execution
4. Click "■ Stop" to abort execution at any time
5. Script execution is logged with timestamps in the Script Log panel

---

## Extending the Simulator: Adding New Types and File Formats

### Adding a New PLC Data Type

The simulator uses a handler-based approach for PLC data types. To add a new type:

1. **Create a Handler Class**
   - In `src/type_handlers.py`, subclass `PlcTypeHandler` and implement the `pack`, `unpack`, and `word_length` methods.

   ```python
   class MyNewTypeHandler(PlcTypeHandler):
       def pack(self, value):
           # Convert value to bytes
           ...
       def unpack(self, data):
           # Convert bytes to value
           ...
       def word_length(self):
           # Return appropriate WordLen
           ...
   ```

2. **Register the Handler**
   - Add your handler to the `PLC_TYPE_HANDLERS` dictionary in `src/type_handlers.py`:

   ```python
   PLC_TYPE_HANDLERS = {
       ...
       'MYNEWTYPE': MyNewTypeHandler(),
   }
   ```

3. **(Optional) Handle Dynamic Types**
   - If your type requires parameters (like `STRING[n]`), update the `get_type_handler` function in `src/type_handlers.py` to handle it.

---

### Adding a New File Format

The simulator uses a handler-based approach for file formats. To add a new file format:

1. **Create a File Handler Class**
   - In `src/file_handlers.py`, subclass `DbFileHandler` and implement the `load` and `save` methods.

   ```python
   class MyFormatFileHandler(DbFileHandler):
       def load(self, path):
           # Load and parse file
           ...
       def save(self, path, data):
           # Write data to file
           ...
   ```

2. **Update the File Handler Selector**
   - Add your handler to the `get_file_handler` function in `src/file_handlers.py`:

   ```python
   def get_file_handler(file_path):
       if file_path.endswith('.myfmt'):
           return MyFormatFileHandler()
       ...
   ```

3. **Use the New Format in the GUI**
   - The GUI will automatically use your handler when opening or saving files with your extension.
