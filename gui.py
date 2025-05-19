from tkinter import messagebox
from tkinter import *
from tkinter import ttk
from tkcalendar import DateEntry
from auth import authenticate, generate_token, start_scheduler
from config import get_tokens, CLIENT_ID
from utils import load_symbol_master, fetch_historical_data
from fyers_apiv3 import fyersModel
import sqlite3
import logging
from datetime import datetime, timedelta
from holidays import is_trading_day
import resampler

# --- Strategy imports ---
from deepseek_strategy import Intraday15MinStrategy
from walkforward import WalkForwardBacktester

import numbers  # for robust timestamp conversion

logging.basicConfig(level=logging.INFO)

symbol_data = load_symbol_master(r"C:\Fyers Database\symbol_master.json")

# Global to hold the selected strategy instance and metadata for future usage
active_strategy_instance = None
active_strategy_key = None

def to_human_time(ts):
    import numbers
    from datetime import datetime
    try:
        if ts is None:
            return ""
        if isinstance(ts, numbers.Number):
            # Avoid nan and inf
            if ts != ts or ts == float('inf') or ts == float('-inf'):
                return ""
            # If the number is too small for a timestamp, just show as is
            if ts < 100000000:  # not a plausible UNIX timestamp
                return str(ts)
            return datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M:%S')
        if isinstance(ts, str) and ts.isdigit():
            return datetime.fromtimestamp(float(ts)).strftime('%Y-%m-%d %H:%M:%S')
        return str(ts)
    except Exception:
        return str(ts)

def launch_gui():
    main = Tk()
    main.title("Fyers Authentication")
    main.geometry("600x400")

    top = Frame(main)
    top.pack(fill=X, pady=5)
    Button(top, text="Home", command=lambda: None).pack(side=LEFT, padx=10)
    Button(top, text="Profile", command=lambda: show_profile(main)).pack(side=LEFT, padx=10)
    Button(top, text="Funds", command=lambda: show_funds(main)).pack(side=LEFT, padx=10)
    Button(top, text="Historical Data", command=lambda: open_historical_data_window(main)).pack(side=LEFT, padx=10)
    Button(top, text="Backtest", command=lambda: open_backtest_window(main)).pack(side=LEFT, padx=10)

    Label(main, text="Enter Auth Code:").pack(pady=5)
    auth_entry = Entry(main, width=40)
    auth_entry.pack(pady=5)

    Button(main, text="Authenticate", command=authenticate).pack(pady=5)
    Button(main, text="Generate Access Token", command=lambda: generate_token(auth_entry.get())).pack(pady=5)
    Button(main, text="Start Background Tasks", command=start_scheduler).pack(pady=5)

    main.mainloop()

def get_fyers_instance():
    from config import load_latest_token_from_file, set_tokens

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

def show_profile(parent):
    fyers = get_fyers_instance()
    if not fyers:
        show_error(parent, "Access token is missing or expired.")
        return

    win = Toplevel(parent)
    win.title("Profile Details")
    win.geometry("600x400")

    Button(win, text="Close", command=win.destroy).pack()
    try:
        profile = fyers.get_profile()
        Label(win, text=str(profile), wraplength=550, justify="left").pack(pady=20)
    except Exception as e:
        show_error(win, f"Error fetching profile: {str(e)}")

def show_funds(parent):
    fyers = get_fyers_instance()
    if not fyers:
        show_error(parent, "Access token is missing or expired.")
        return

    win = Toplevel(parent)
    win.title("Funds")
    win.geometry("600x400")

    Button(win, text="Close", command=win.destroy).pack()
    try:
        funds = fyers.funds()
        Label(win, text=str(funds), wraplength=550, justify="left").pack(pady=20)
    except Exception as e:
        show_error(win, f"Error fetching funds: {str(e)}")

def open_backtest_window(parent):
    global active_strategy_instance, active_strategy_key
    win = Toplevel(parent)
    win.title("Backtest Interface")
    win.geometry("900x750")

    Label(win, text="Backtest interface").pack(pady=10)

    # --- Search box for symbol presence in symbol_master.json ---
    search_frame = Frame(win)
    search_frame.pack(pady=10)
    Label(search_frame, text="Search or Enter Stock Name/Symbol:").pack(side=LEFT, padx=5)
    search_entry = Entry(search_frame, width=30)
    search_entry.pack(side=LEFT, padx=5)

    result_list = Listbox(win, width=60, height=7)
    result_list.pack(pady=5)

    selected_symbol_var = StringVar()
    selected_exsym_var = StringVar()
    active_interval_var = StringVar(value="5min")  # For tracking the active interval for future operations

    def on_search(*_):
        query = search_entry.get().strip().lower()
        result_list.delete(0, END)
        for symbol, data in symbol_data.items():
            exsym = data.get("exSymName", "").lower()
            if query in symbol.lower() or query in exsym:
                exsym_disp = data.get("exSymName", "")
                result_list.insert(END, f"{symbol} - {exsym_disp}")

    def on_select(_):
        selection = result_list.curselection()
        if selection:
            selected = result_list.get(selection[0])
            symbol, exsym_disp = selected.split(" - ", 1)
            selected_symbol_var.set(symbol)
            selected_exsym_var.set(exsym_disp)
            # Fetch and resample upon selection
            success = resampler.fetch_and_store_symbol(symbol)
            if success:
                result_label.config(text=f"Fetched & resampled data for '{symbol}'.", fg="green")
            else:
                conn = sqlite3.connect(r"C:\Fyers Database\historical_data.db")
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT symbol FROM historical_data LIMIT 5")
                sample = [row[0] for row in cur.fetchall()]
                conn.close()
                result_label.config(
                    text=f"Symbol '{symbol}' is NOT present in historical_data.db.\nSample symbols: {sample}", fg="red")

    search_entry.bind("<KeyRelease>", on_search)
    result_list.bind("<<ListboxSelect>>", on_select)

    Label(win, textvariable=selected_symbol_var, font=("Arial", 11), fg="blue").pack()
    Label(win, textvariable=selected_exsym_var, font=("Arial", 10), fg="gray").pack()

    result_label = Label(win, text="", fg="blue", font=("Arial", 10))
    result_label.pack(pady=10)

    # --- Dropdown for timeframes ---
    timeframe_frame = Frame(win)
    timeframe_frame.pack(pady=10)
    Label(timeframe_frame, text="Select Resample Timeframe:").pack(side=LEFT, padx=5)
    timeframe_var = StringVar(value="5 min")
    timeframe_dropdown = ttk.Combobox(
        timeframe_frame,
        textvariable=timeframe_var,
        values=["5 min", "15 min", "1 hour"],
        state="readonly",
        width=10
    )
    timeframe_dropdown.pack(side=LEFT, padx=5)

    def on_interval_change(*_):
        val = timeframe_var.get()
        if val == "5 min":
            active_interval_var.set("5min")
        elif val == "15 min":
            active_interval_var.set("15min")
        elif val == "1 hour":
            active_interval_var.set("1hour")
        else:
            active_interval_var.set("5min")

    timeframe_dropdown.bind("<<ComboboxSelected>>", on_interval_change)

    # --- Dropdown for strategy selection ---
    strategy_frame = Frame(win)
    strategy_frame.pack(pady=10)
    Label(strategy_frame, text="Select Strategy:").pack(side=LEFT, padx=5)
    strategy_var = StringVar(value="deep.boll.vwap.rsi.macd")
    strategy_dropdown = ttk.Combobox(
        strategy_frame,
        textvariable=strategy_var,
        values=["deep.boll.vwap.rsi.macd"],  # Add more strategies as you create them
        state="readonly",
        width=30
    )
    strategy_dropdown.pack(side=LEFT, padx=5)

    # --- Activate strategy instance on dropdown change ---
    def on_strategy_change(*_):
        global active_strategy_instance, active_strategy_key
        selected = strategy_var.get()
        active_strategy_key = selected
        if selected == "deep.boll.vwap.rsi.macd":
            active_strategy_instance = Intraday15MinStrategy()
            result_label.config(text="Strategy 'deep.boll.vwap.rsi.macd' loaded and ready.", fg="green")
        # Add further elif branches for future strategies

    strategy_dropdown.bind("<<ComboboxSelected>>", on_strategy_change)
    # Immediately call to set initial state
    on_strategy_change()

    def show_current_resampled_data():
        interval = active_interval_var.get()
        if interval == "5min":
            data = resampler.get_resampled_data("5min")
        elif interval == "15min":
            data = resampler.get_resampled_data("15min")
        elif interval == "1hour":
            data = resampler.get_resampled_data("1hour")
        else:
            data = []
        if not data:
            messagebox.showinfo("Info", "No data to display. Please select a symbol first.")
            return
        display_win = Toplevel(win)
        display_win.title(f"Resampled Data ({interval})")
        display_win.geometry("1100x600")

        columns = ["id", "symbol", "timestamp", "open", "high", "low", "close", "volume"]
        tree = ttk.Treeview(display_win, columns=columns, show="headings")
        for col in columns:
            tree.heading(col, text=col)
            if col == "symbol":
                tree.column(col, width=120)
            elif col == "timestamp":
                tree.column(col, width=140)
            else:
                tree.column(col, width=80)
        tree.pack(fill=BOTH, expand=True)
        max_rows = 1000
        for i, row in enumerate(data):
            if i >= max_rows:
                break
            ts = row["timestamp"]
            ts_str = to_human_time(ts)
            tree.insert("", END, values=(
                row.get("id", ""), row.get("symbol", ""), ts_str,
                row.get("open", ""), row.get("high", ""), row.get("low", ""),
                row.get("close", ""), row.get("volume", "")
            ))
        if len(data) > max_rows:
            Label(display_win, text=f"Showing first {max_rows} rows (out of {len(data)})", fg="red").pack()
        Button(display_win, text="Close", command=display_win.destroy).pack(pady=10)

    def on_backtest():
        symbol = selected_symbol_var.get()
        interval = active_interval_var.get()
        strategy_key = strategy_var.get()
        if not symbol:
            messagebox.showwarning("Warning", "Please select a symbol.")
            return
        if not interval:
            messagebox.showwarning("Warning", "Please select an interval.")
            return
        if not strategy_key:
            messagebox.showwarning("Warning", "Please select a strategy.")
            return
        # Run walkforward backtest
        try:
            backtester = WalkForwardBacktester(
                strategy_key=strategy_key,
                interval=interval,
                symbol=symbol,
                capital=10000
            )
            results = backtester.run_backtest()
            # Show results in a popup window
            stats = results["stats"]
            trades = results["trades"]
            show_backtest_results(win, stats, trades)
        except Exception as e:
            messagebox.showerror("Error", f"Backtest failed: {e}")

    Button(win, text="Show", command=show_current_resampled_data).pack(pady=5)
    Button(win, text="Backtest", command=on_backtest).pack(pady=5)
    Button(win, text="Close", command=win.destroy).pack(pady=30)

def show_backtest_results(parent, stats, trades):
    win = Toplevel(parent)
    win.title("Backtest Results")
    win.geometry("950x700")
    stat_text = ""
    for k, v in stats.items():
        if isinstance(v, float):
            stat_text += f"{k}: {v:.3f}\n"
        else:
            stat_text += f"{k}: {v}\n"

    # Prepare trade lines for copying
    trade_lines = []
    header = "Entry Time,Exit Time,Direction,P&L,Exit Reason"
    trade_lines.append(header)
    for t in trades:
        entry_time = to_human_time(t.get('entry_time', ''))
        exit_time = to_human_time(t.get('exit_time', ''))
        trade_lines.append(f"{entry_time},{exit_time},{t['direction']},{round(t['pl'],2)},{t['exit_reason']}")
    trades_text = "\n".join(trade_lines)

    # Place a Text widget for copiable output
    results_box = Text(win, height=15, width=110, wrap='none', font=("Courier New", 10))
    results_box.insert("1.0", "Backtest Statistics:\n" + stat_text + "\nTrades:\n" + trades_text)
    results_box.config(state="disabled")
    results_box.pack(pady=6)

    # Copy button to clipboard
    def copy_results():
        win.clipboard_clear()
        win.clipboard_append(results_box.get("1.0", END).rstrip())
        win.update()  # keep clipboard after window closes

    Button(win, text="Copy Results", command=copy_results).pack(pady=3)

    # Treeview for nice display
    Label(win, text="Tabular View", font=("Arial", 11, "bold")).pack()
    frame = Frame(win)
    frame.pack(fill=BOTH, expand=True, padx=8, pady=8)
    tree = ttk.Treeview(frame, columns=("entry_time","exit_time","direction","pl","exit_reason"), show="headings")
    for col in tree["columns"]:
        tree.heading(col, text=col)
        tree.column(col, width=150)
    for t in trades:
        entry_time = to_human_time(t.get('entry_time', ''))
        exit_time = to_human_time(t.get('exit_time', ''))
        tree.insert("", END, values=(entry_time, exit_time, t['direction'], round(t['pl'],2), t['exit_reason']))
    tree.pack(fill=BOTH, expand=True)
    Button(win, text="Close", command=win.destroy).pack(pady=10)

def open_historical_data_window(parent):
    win = Toplevel(parent)
    win.title("Historical Data")
    win.geometry("700x600")

    Label(win, text="Search Stock Symbol:").pack(pady=5)
    search_entry = Entry(win, width=50)
    search_entry.pack(pady=5)

    result_list = Listbox(win, width=80, height=10)
    result_list.pack(pady=5)

    selected_symbol_var = StringVar()

    def on_search(*_):
        query = search_entry.get().strip().lower()
        result_list.delete(0, END)
        for symbol, data in symbol_data.items():
            name = data.get("exSymName", "").lower()
            if query in symbol.lower() or query in name:
                result_list.insert(END, symbol)

    def on_select(_):
        selection = result_list.curselection()
        if selection:
            selected = result_list.get(selection[0])
            selected_symbol_var.set(selected)

    search_entry.bind("<KeyRelease>", on_search)
    result_list.bind("<<ListboxSelect>>", on_select)

    Label(win, text="Start Date:").pack(pady=5)
    start_cal = DateEntry(win, width=20, background='darkblue', foreground='white', borderwidth=2)
    start_cal.pack(pady=5)

    Label(win, text="End Date:").pack(pady=5)
    end_cal = DateEntry(win, width=20, background='darkblue', foreground='white', borderwidth=2)
    end_cal.pack(pady=5)

    def handle_download():
        symbol = selected_symbol_var.get()
        start_date = start_cal.get_date().strftime("%Y-%m-%d")
        end_date = end_cal.get_date().strftime("%Y-%m-%d")
        if not symbol:
            show_error(win, "Please select a symbol.")
            return
        
        try:
            success, message = fetch_historical_data(symbol, start_date, end_date)
            if success:
                messagebox.showinfo("Success", message)
            else:
                messagebox.showinfo("No Data", message)
        except Exception as e:
            logging.error(f"Download error: {e}")
            messagebox.showerror("Error", str(e))

    def handle_show_data():
        symbol = selected_symbol_var.get()
        start_date = start_cal.get_date().strftime("%Y-%m-%d")
        end_date = end_cal.get_date().strftime("%Y-%m-%d")
        if not symbol:
            show_error(win, "Please select a symbol.")
            return

        try:
            start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            end_ts = int(datetime(end_dt.year, end_dt.month, end_dt.day, 23, 59, 59).timestamp())

            conn = sqlite3.connect(r"C:\Fyers Database\historical_data.db")
            cursor = conn.cursor()
            cursor.execute("""
                SELECT timestamp, open, high, low, close, volume 
                FROM historical_data 
                WHERE symbol = ? AND timestamp BETWEEN ? AND ?
                ORDER BY timestamp ASC
            """, (symbol, start_ts, end_ts))
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                show_error(win, "No historical data found for selected date range.")
                return

            result_win = Toplevel(win)
            result_win.title(f"Historical Data for {symbol}")
            result_win.geometry("800x600")

            tree = ttk.Treeview(result_win, columns=("timestamp", "open", "high", "low", "close", "volume"), show="headings")
            for col in tree["columns"]:
                tree.heading(col, text=col)
                tree.column(col, width=120)
            tree.pack(fill=BOTH, expand=True)

            for row in rows:
                readable_ts = to_human_time(row[0])
                tree.insert("", END, values=(readable_ts, *row[1:]))

        except Exception as e:
            show_error(win, f"Error retrieving data: {e}")

    Button(win, text="Download", command=handle_download).pack(pady=10)
    Button(win, text="Show Data", command=handle_show_data).pack(pady=5)
    Button(win, text="Close", command=win.destroy).pack(pady=10)

def show_error(parent, message):
    win = Toplevel(parent)
    win.title("Error")
    win.geometry("400x200")
    Label(win, text=message, fg="red").pack(pady=20)
    Button(win, text="Close", command=win.destroy).pack()

if __name__ == "__main__":
    launch_gui()
