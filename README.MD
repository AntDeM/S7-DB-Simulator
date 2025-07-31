A Siemens S7 DB simulator using Snap7

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

### How to Use

1. **Start the Application**
   - Run `python plc_simulator.py` or use the built executable.

2. **Toolbar Functions**
   - **Load YAML**: Open a DB configuration YAML file.
   - **Reload**: Reload the current YAML file (useful if edited externally).
   - **Save**: Save changes to the current YAML file.
   - **Save As**: Save the current DBs to a new YAML file.
   - **Export CSV**: Export the current DBs to a CSV file.

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

## Extending the Simulator: Adding New Types and File Formats

### Adding a New PLC Data Type

The simulator uses a handler-based approach for PLC data types. To add a new type:

1. **Create a Handler Class**
   - In `plc_simulator.py`, subclass `PlcTypeHandler` and implement the `pack`, `unpack`, and `word_length` methods.

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
   - Add your handler to the `PLC_TYPE_HANDLERS` dictionary:

   ```python
   PLC_TYPE_HANDLERS = {
       ...
       'MYNEWTYPE': MyNewTypeHandler(),
   }
   ```

3. **(Optional) Handle Dynamic Types**
   - If your type requires parameters (like `STRING[n]`), update the `get_type_handler` function to handle it.

---

### Adding a New File Format

The simulator uses a handler-based approach for file formats. To add a new file format:

1. **Create a File Handler Class**
   - In `plc_simulator.py`, subclass `DbFileHandler` and implement the `load` and `save` methods.

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
   - Add your handler to the `get_file_handler` function:

   ```python
   def get_file_handler(file_path):
       if file_path.endswith('.myfmt'):
           return MyFormatFileHandler()
       ...
   ```

3. **Use the New Format in the GUI**
   - The GUI will automatically use your handler when opening or saving files with your extension.

---

**No changes to the GUI or simulator logic are needed—just add your handler and register it**
