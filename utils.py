# utils.py
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
import time
from config import get_tokens, CLIENT_ID
from fyers_apiv3 import fyersModel
import pandas as pd
import ta
import tkinter as tk
from tkinter import ttk
from holidays import is_trading_day

logging.basicConfig(level=logging.INFO)

# Define IST timezone
IST = timezone(timedelta(hours=5, minutes=30))

def load_symbol_master(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Failed to load symbol master: {e}")
        return {}

def get_fyers_instance():
    from config import load_latest_token_from_file, set_tokens

    # Attempt to use latest file-based token if current token is missing
    access, refresh = get_tokens()
    if not access:
        latest = load_latest_token_from_file()
        if latest:
            access, refresh = latest
            set_tokens(access, refresh)
        else:
            logging.warning("No valid token available.")
            return None

    return fyersModel.FyersModel(client_id=CLIENT_ID, is_async=False, token=access, log_path="")

def fetch_historical_data(symbol, start_date_str, end_date_str):
    """Fetch historical data for a symbol between dates, skipping non-trading days
    Returns: tuple of (success: bool, message: str)"""
    access_token, _ = get_tokens()
    if not access_token:
        return False, "Access token is missing or expired"

    # Convert input strings to date objects
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()

    # Check if any dates in the range are trading days
    trading_days = [
        single_date 
        for single_date in (
            start_date + timedelta(n) 
            for n in range((end_date - start_date).days + 1))
        if is_trading_day(single_date)
    ]

    if not trading_days:
        msg = f"No trading days between {start_date_str} and {end_date_str}"
        logging.info(msg)
        return False, msg

    fyers = fyersModel.FyersModel(client_id=CLIENT_ID, token=access_token, is_async=False, log_path="")

    # Convert dates to UNIX timestamp
    start_timestamp = int(time.mktime(start_date.timetuple()))
    end_timestamp = int(time.mktime(end_date.timetuple()))

    logging.info(f"Fetching data for {symbol} from {start_date_str} to {end_date_str}")

    # API request body
    data = {
        "symbol": symbol,
        "resolution": "5",
        "date_format": "1",
        "range_from": start_date_str,
        "range_to": end_date_str,
        "cont_flag": "0"
    }

    # Make API call
    response = fyers.history(data)

    if response.get("code") != 200 or "candles" not in response:
        error_msg = f"Failed to fetch data: {response.get('message', 'Unknown error')}"
        logging.error(error_msg)
        return False, error_msg

    candles = response["candles"]

    if not candles:
        error_msg = "No historical data found (likely due to holiday or wrong symbol)"
        logging.error(error_msg)
        return False, error_msg

    # Save to SQLite DB
    db_path = r"C:\Fyers Database\historical_data.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Insert or ignore duplicates
    for candle in candles:
        timestamp, open_, high, low, close, volume = candle
        c.execute("""
            INSERT OR IGNORE INTO historical_data
            (symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (symbol, int(timestamp), open_, high, low, close, volume))

    conn.commit()
    conn.close()
    success_msg = f"Successfully saved {len(candles)} rows for {symbol} into historical_data.db"
    logging.info(success_msg)
    return True, success_msg

def run_moving_average_crossover_backtest(symbol):
    db_path = r"C:\Fyers Database\historical_data.db"
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query(f"SELECT * FROM historical_data WHERE symbol = ? ORDER BY timestamp", conn, params=(symbol,))
    conn.close()

    if df.empty:
        raise Exception("No data found for symbol.")

    # Fix for FutureWarning: Ensure "timestamp" is numeric before converting
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")  # Ensure numeric values
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit='s', utc=True)  # Convert to UTC datetime
    df["timestamp"] = df["timestamp"].dt.tz_convert(IST)  # Convert to IST

    df = df.set_index("timestamp")  # Modified here to avoid inplace
    df = df.sort_index()  # Modified here to avoid inplace

    # Calculate indicators
    df["ema_5"] = df["close"].ewm(span=5).mean()
    df["ema_13"] = df["close"].ewm(span=13).mean()
    df["rsi"] = ta.momentum.RSIIndicator(close=df["close"], window=14).rsi().bfill()  # Backfill directly

    # Generate signals
    df["signal"] = 0
    df["signal"] = (
        ((df["ema_5"] > df["ema_13"]) & (df["ema_5"].shift(1) <= df["ema_13"].shift(1)) & (df["rsi"].between(40, 60))).astype(int)
        - ((df["ema_5"] < df["ema_13"]) & (df["ema_5"].shift(1) >= df["ema_13"].shift(1)) & (df["rsi"].between(40, 60))).astype(int)
    )

    trades = []
    last_trade = None
    for idx, row in df[df["signal"] != 0].iterrows():
        trade_type = "BUY" if row["signal"] == 1 else "SELL"
        profit_or_loss = None

        # Calculate profit or loss if there was a previous trade
        if last_trade:
            if last_trade["type"] != trade_type:  # Only calculate if the trade types are opposite
                profit_or_loss = round(row["close"] - last_trade["price"], 2)
                if last_trade["type"] == "SELL":  # Adjust sign for SELL → BUY sequence
                    profit_or_loss = -profit_or_loss

        trades.append({
            "time": idx.strftime("%Y-%m-%d %H:%M"),
            "price": round(row["close"], 2),
            "type": trade_type,
            "pnl": profit_or_loss
        })

        # Update the last trade
        last_trade = {"type": trade_type, "price": row["close"]}

    # Calculate total profit or loss
    total_pnl = sum(trade["pnl"] for trade in trades if trade["pnl"] is not None)

    # GUI Interface for displaying results
    def show_results_gui(trades, total_pnl):
        # Create a new Tkinter window
        window = tk.Tk()
        window.title("Backtest Results")

        # Add a Treeview widget to display the results in a table-like format
        tree = ttk.Treeview(window, columns=("Time", "Type", "Price", "PnL"), show="headings")
        tree.heading("Time", text="Time")
        tree.heading("Type", text="Type")
        tree.heading("Price", text="Price")
        tree.heading("PnL", text="Profit/Loss")

        # Insert trades into the Treeview
        for trade in trades:
            tree.insert("", "end", values=(trade["time"], trade["type"], trade["price"], trade["pnl"]))

        tree.pack(fill=tk.BOTH, expand=True)

        # Add total profit/loss label
        total_pnl_label = tk.Label(window, text=f"Total Profit/Loss: {total_pnl:.2f}", font=("Arial", 12, "bold"))
        total_pnl_label.pack(pady=10)

        # Add a close button
        close_button = tk.Button(window, text="Close", command=window.destroy)
        close_button.pack()

        # Run the Tkinter event loop
        window.mainloop()

    # Call the GUI function to show results
    if trades:
        show_results_gui(trades, total_pnl)
    else:
        print("\nNo trades were generated based on the backtest criteria.")  # Fallback for no trades

    return trades
