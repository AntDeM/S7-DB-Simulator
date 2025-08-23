import os
import snap7

dll_path = os.path.join(os.path.dirname(snap7.__file__), 'lib/snap7.dll')

block_cipher = None

a = Analysis(
    ['plc_simulator.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('db_example.yaml', '.'),
        (dll_path, '.'),  # Copies the snap7.dll to the output folder
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PLC DB Simulator',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
