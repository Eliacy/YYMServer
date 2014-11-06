# -*- mode: python -*-
a = Analysis(['uploader.py'],
             pathex=['C:\\Users\\elias\\Documents\\yym\\YYMServer\\YYMUploader'],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='uploader.exe',
          debug=False,
          strip=None,
          upx=True,
          console=True )
