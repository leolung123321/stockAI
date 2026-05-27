# -*- mode: python ; coding: utf-8 -*-


import os
import site

# 找 futu 套件路徑
_futu_dir = None
for p in site.getsitepackages():
    d = os.path.join(p, "futu")
    if os.path.isdir(d):
        _futu_dir = d
        break
if not _futu_dir:
    # fallback: site-packages in .venv
    _futu_dir = os.path.join(os.path.dirname(__file__), ".venv", "Lib", "site-packages", "futu")

_futu_datas = []
if _futu_dir:
    for f in ["VERSION.txt"]:
        fp = os.path.join(_futu_dir, f)
        if os.path.isfile(fp):
            _futu_datas.append((fp, "futu"))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=_futu_datas + [("watchlist.json", ".")],
    hiddenimports=['flask', 'yfinance', 'openai', 'telegram', 'telegram.ext', 'numpy', 'requests', 'dotenv', 'webbrowser', 'futu', 'futu.common', 'futu.quote', 'futu.trade', 'futu.tools', 'stock_bot.db', 'stock_bot.stock_data', 'stock_bot.futu_client', 'stock_bot.news_fetcher', 'stock_bot.sentiment', 'stock_bot.formatter', 'stock_bot.bot', 'web_app'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StockAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
