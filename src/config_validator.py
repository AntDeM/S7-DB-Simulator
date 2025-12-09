# pylint: disable=line-too-long
# pylint: disable=too-many-statements
# pylint: disable=too-many-branches
# pylint: disable=raise-missing-from
"""
Configuration validator for PLC DB definitions.
Validates YAML config structure, types, offsets, and value compatibility.
"""

import re
import datetime


def sanity_check_config(config):
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

    def check_value_compatibility(type_, value, field_name, db_number):  # pylint: disable=too-many-statements, too-many-branches
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
