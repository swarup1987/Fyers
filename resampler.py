import sqlite3
import pandas as pd
from datetime import datetime

resampled_data = []          # Holds 5 min data as list of dicts
resampled_15min = []         # Holds 15 min resampled data as list of dicts
resampled_1hour = []         # Holds 1 hour resampled data as list of dicts

def fetch_and_store_symbol(symbol, db_path=r"C:\Fyers Database\historical_data.db"):
    global resampled_data, resampled_15min, resampled_1hour
    resampled_data = []
    resampled_15min = []
    resampled_1hour = []
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol, timestamp, open, high, low, close, volume 
            FROM historical_data 
            WHERE UPPER(symbol) = ?
            ORDER BY timestamp ASC
        """, (symbol.strip().upper(),))
        rows = cur.fetchall()
        conn.close()
        if rows:
            resampled_data = [
                {
                    "id": row[0],
                    "symbol": row[1],
                    "timestamp": row[2],
                    "open": row[3],
                    "high": row[4],
                    "low": row[5],
                    "close": row[6],
                    "volume": row[7]
                }
                for row in rows
            ]
            resample_all()
            return True
        else:
            return False
    except Exception as e:
        print(f"Error in fetch_and_store_symbol: {e}")
        return False

def get_resampled_data(interval="5min"):
    if interval == "5min":
        return resampled_data
    elif interval == "15min":
        return resampled_15min
    elif interval == "1hour":
        return resampled_1hour
    else:
        return []

def resample_all():
    """Resample the 5 min data to 15 min and 1 hour data."""
    global resampled_15min, resampled_1hour
    resampled_15min = resample(resampled_data, "15min")
    resampled_1hour = resample(resampled_data, "60min")

def resample(data, pandas_interval):
    """
    data: list of dicts (must have keys: timestamp, open, high, low, close, volume)
    pandas_interval: pandas offset alias, e.g., "15T" for 15 min, "60T" for 1 hour
    Returns: list of dicts (same keys as input, timestamp is start of resampled interval)
    """
    if not data:
        return []
    df = pd.DataFrame(data)
    if 'timestamp' not in df.columns or len(df) == 0:
        return []
    # Future-proof: Cast timestamp to numeric before to_datetime to avoid pandas warning
    df['timestamp'] = pd.to_datetime(pd.to_numeric(df['timestamp'], errors='coerce'), unit='s')
    df = df.sort_values('timestamp')
    df.set_index('timestamp', inplace=True)

    agg_dict = {
        'id': 'first',
        'symbol': 'first',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }

    # Drop rows with NaNs in OHLCV (just in case)
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])

    df_resampled = df.resample(pandas_interval, label='left', closed='left').agg(agg_dict)
    df_resampled = df_resampled.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
    df_resampled = df_resampled.reset_index()

    # Convert timestamp back to int seconds
    df_resampled['timestamp'] = df_resampled['timestamp'].astype(int) // 10**9

    # Convert back to list of dicts
    result = df_resampled.to_dict(orient='records')
    return result
