# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('Z:\\\\home\\strocker755\\Documentos\\Synapse IT\\Juan_v2\\sistema_comercio\\assets', 'assets'), ('Z:\\\\home\\strocker755\\Documentos\\Synapse IT\\Juan_v2\\sistema_comercio\\db', 'db')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('reportlab')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


block_cipher = None


a = Analysis(['Z:\\\\home\\strocker755\\Documentos\\Synapse IT\\Juan_v2\\sistema_comercio\\main.py'],
             pathex=[],
             binaries=binaries,
             datas=datas,
             hiddenimports=hiddenimports,
             hookspath=[],
             hooksconfig={},
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts, 
          [],
          exclude_binaries=True,
          name='SistemaGestion',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          console=False,
          disable_windowed_traceback=False,
          target_arch=None,
          codesign_identity=None,
          entitlements_file=None , icon='Z:\\home\\strocker755\\Documentos\\Synapse IT\\Juan_v2\\sistema_comercio\\assets\\icon.ico')
coll = COLLECT(exe,
               a.binaries,
               a.zipfiles,
               a.datas, 
               strip=False,
               upx=True,
               upx_exclude=[],
               name='SistemaGestion')
