import sys
sys.path.insert(0, '.')
import yfinance as yf

symbols = ["0992.HK", "1347.HK", "0522.HK", "0981.HK", "0005.HK"]
for s in symbols:
    t = yf.Ticker(s)
    df = t.history(period="6mo", auto_adjust=False)
    print(f"\n=== {s} ===")
    print(f"Columns: {list(df.columns)}")
    # 看最近5天數據
    last5 = df.tail(5)
    for idx, row in last5.iterrows():
        print(f"  {idx.date()} O={row['Open']:.2f} H={row['High']:.2f} L={row['Low']:.2f} C={row['Close']:.2f} AC={row.get('Adj Close', 'N/A')} Vol={int(row['Volume'])}")