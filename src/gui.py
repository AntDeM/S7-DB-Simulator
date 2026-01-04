# pylint: disable=line-too-long
# pylint: disable=broad-exception-caught
"""
PLC Simulator GUI - Tkinter interface for viewing and editing PLC DBs.
Supports loading, saving, reloading, and exporting DB configurations.
"""

import os
import logging
import traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from src.interfaces import IPlcSimulator, IConfigLoader, IConfigSaver
from src.file_handlers import get_file_handler, CsvFileHandler
from src.config_validator import sanity_check_config
from src.simulator import PLCSimulator
from src.script_engine import ScriptEngine

logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 2000  # Increased to reduce lock contention and CPU usage


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
        self.gui_polling_enabled = False  # Disabled by default to reduce lock contention
        self.script_engine: ScriptEngine | None = None
        self.script_log_box: tk.Text | None = None
        self.script_path_label: ttk.Label | None = None
        self.script_start_btn: ttk.Button | None = None
        self.script_stop_btn: ttk.Button | None = None
        self.polling_var = None  # Will be set in build_toolbar
        self.build_toolbar()
        self.build_script_panel()
        self.build_ui()
        # GUI polling disabled by default - use Auto-refresh checkbox to enable
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

        # Separator
        ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=5, pady=2)

        # GUI Polling toggle
        self.polling_var = tk.BooleanVar(value=self.gui_polling_enabled)
        polling_check = ttk.Checkbutton(toolbar, text="Auto-refresh GUI", variable=self.polling_var, command=self.toggle_polling)
        polling_check.pack(side='left', padx=2, pady=2)
        
        # Manual refresh button
        refresh_btn = ttk.Button(toolbar, text="🔄 Refresh", command=self.manual_refresh)
        refresh_btn.pack(side='left', padx=2, pady=2)

        # Script controls
        ttk.Label(toolbar, text="Script:").pack(side='left', padx=2, pady=2)
        load_script_btn = ttk.Button(toolbar, text="Load Script", command=self.on_load_script)
        load_script_btn.pack(side='left', padx=2, pady=2)
        self.script_start_btn = ttk.Button(toolbar, text="▶ Start", command=self.on_start_script, state='disabled')
        self.script_start_btn.pack(side='left', padx=2, pady=2)
        self.script_stop_btn = ttk.Button(toolbar, text="■ Stop", command=self.on_stop_script, state='disabled')
        self.script_stop_btn.pack(side='left', padx=2, pady=2)

    def build_script_panel(self):
        """
        Builds the script log panel at the bottom of the window.
        """
        script_frame = ttk.LabelFrame(self.root, text="Script Log")
        script_frame.pack(fill='x', side='bottom', padx=5, pady=5)

        # Script path label
        path_frame = ttk.Frame(script_frame)
        path_frame.pack(fill='x', padx=2, pady=2)
        ttk.Label(path_frame, text="Loaded:").pack(side='left')
        self.script_path_label = ttk.Label(path_frame, text="(no script loaded)", foreground='gray')
        self.script_path_label.pack(side='left', padx=5)

        # Clear log button
        clear_btn = ttk.Button(path_frame, text="Clear Log", command=self.on_clear_script_log)
        clear_btn.pack(side='right', padx=2)

        # Script log text box
        log_frame = ttk.Frame(script_frame)
        log_frame.pack(fill='both', expand=True, padx=2, pady=2)
        self.script_log_box = tk.Text(log_frame, height=6, state='disabled', bg='#1e1e1e', fg='#00ff00', font=('Consolas', 9))
        script_vsb = ttk.Scrollbar(log_frame, orient='vertical', command=self.script_log_box.yview)
        self.script_log_box.configure(yscrollcommand=script_vsb.set)
        self.script_log_box.pack(side='left', fill='both', expand=True)
        script_vsb.pack(side='right', fill='y')

    def on_load_script(self):
        """
        Loads a script file.
        """
        file_path = filedialog.askopenfilename(
            title="Select Script file",
            filetypes=[("Script files", "*.script *.txt"), ("All files", "*.*")]
        )
        if not file_path:
            return

        if not self.simulator:
            messagebox.showwarning("Warning", "Please load a DB configuration first.")
            return

        # Create script engine with log callback
        self.script_engine = ScriptEngine(self.simulator, self.append_script_log)

        if self.script_engine.load_script(file_path):
            self.script_path_label.config(text=os.path.basename(file_path), foreground='black')
            self.script_start_btn.config(state='normal')
        else:
            self.script_path_label.config(text="(load failed)", foreground='red')
            self.script_start_btn.config(state='disabled')

    def on_start_script(self):
        """
        Starts script execution.
        """
        if not self.script_engine:
            return

        if self.script_engine.start():
            self.script_start_btn.config(state='disabled')
            self.script_stop_btn.config(state='normal')
            # Start polling for script completion
            self.check_script_status()

    def on_stop_script(self):
        """
        Stops script execution.
        """
        if self.script_engine:
            self.script_engine.stop()

    def check_script_status(self):
        """
        Periodically checks if the script has finished running.
        """
        if self.script_engine and self.script_engine.is_running():
            self.root.after(100, self.check_script_status)
        else:
            self.script_start_btn.config(state='normal')
            self.script_stop_btn.config(state='disabled')

    def append_script_log(self, message: str):
        """
        Appends a message to the script log box. Thread-safe.
        """
        def _append():
            if self.script_log_box:
                self.script_log_box.config(state='normal')
                self.script_log_box.insert('end', message + '\n')
                self.script_log_box.see('end')
                self.script_log_box.config(state='disabled')
        # Schedule on main thread for thread safety
        self.root.after(0, _append)

    def on_clear_script_log(self):
        """
        Clears the script log box.
        """
        if self.script_log_box:
            self.script_log_box.config(state='normal')
            self.script_log_box.delete('1.0', 'end')
            self.script_log_box.config(state='disabled')

    def build_ui(self):
        """
        Builds the main notebook/tables for each DB. Clears previous tables if any.
        """
        try:
            # Remove previous widgets if any
            for widget in self.root.pack_slaves():
                if isinstance(widget, ttk.Notebook):
                    widget.destroy()

            self.tables.clear()  # Clear stale table references

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
            # Update script engine's simulator reference if loaded
            if self.script_engine:
                self.script_engine.simulator = simulator
            self.build_ui()
            # Only start polling if user has it enabled
            if self.gui_polling_enabled:
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
            # Update script engine's simulator reference if loaded
            if self.script_engine:
                self.script_engine.simulator = simulator
            self.build_ui()
            self.last_yaml_mtime = os.path.getmtime(self.current_yaml_path)
            # Only restart polling if user has it enabled
            if self.gui_polling_enabled:
                self.update_gui()
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

    def toggle_polling(self):
        """
        Toggles GUI auto-refresh on/off.
        """
        self.gui_polling_enabled = self.polling_var.get()
        if self.gui_polling_enabled:
            logger.info("GUI polling enabled")
            if self.simulator:
                self.update_gui()
        else:
            logger.info("GUI polling disabled")
            if self.update_gui_id is not None:
                try:
                    self.root.after_cancel(self.update_gui_id)
                except Exception:
                    pass
                self.update_gui_id = None

    def manual_refresh(self):
        """
        Manually refreshes the GUI once without enabling auto-refresh.
        """
        if not self.simulator:
            return
        try:
            for db_def in self.db_definitions:
                db_number = db_def['db_number']
                if db_number not in self.tables:
                    continue
                tree, _ = self.tables[db_number]
                for field in db_def['fields']:
                    name = field['name']
                    type_ = field['type']
                    offset = field['offset']
                    bit = field.get('bit', None)
                    new_val = self.read_value(db_number, offset, type_, bit)
                    # Convert boolean to string for consistent display
                    if type_.upper() == 'BOOL':
                        new_val = str(bool(new_val))
                    tree.set(name, 'Value', new_val)
            logger.info("GUI manually refreshed")
        except Exception as e:
            logger.error("Error during manual refresh: %s", e)

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

        def on_enter(event):  # pylint: disable=unused-argument
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
        Only runs if GUI polling is enabled.
        """
        # Cancel any previous polling before starting a new one
        if hasattr(self, 'update_gui_id') and self.update_gui_id is not None:
            try:
                self.root.after_cancel(self.update_gui_id)
            except Exception:
                pass
            self.update_gui_id = None
        if not self.simulator or not self.gui_polling_enabled:
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
                        # Handle both string and non-string values in tree
                        if isinstance(current_val, str):
                            current_val_bool = current_val.lower() in ('true', '1', 'yes')
                        else:
                            current_val_bool = bool(current_val)
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
