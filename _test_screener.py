import sys
sys.path.insert(0, '.')
from stock_bot.screener import run_screen
r = run_screen('2026-05-26')
print('=== RESULT ===')
print(f'hits: {len(r["hits"])}')
for h in r['hits']:
    print(f'  {h["name"]} ({h["symbol"]}) {h["change_pct"]:+.2f}% body/atr={h["atr_ratio"]:.2f}x')
print(f'errors: {len(r["errors"])}')
for e in r['errors'][:5]:
    print(f'  {e}')