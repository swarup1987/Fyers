# gui.py
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

logging.basicConfig(level=logging.INFO)

symbol_data = load_symbol_master(r"C:\Fyers Database\symbol_master.json")

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
    win = Toplevel(parent)
    win.title("Test")
    win.geometry("700x500")

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
                result_list.insert(END, f"{symbol} - {data.get('exSymName')}")

    def on_select(_):
        selection = result_list.curselection()
        if selection:
            selected_line = result_list.get(selection[0])
            selected_symbol = selected_line.split(" - ")[0]
            selected_symbol_var.set(selected_symbol)

    search_entry.bind("<KeyRelease>", on_search)
    result_list.bind("<<ListboxSelect>>", on_select)

    Label(win, textvariable=selected_symbol_var, font=("Arial", 12), fg="blue").pack(pady=10)

    strategy_var = BooleanVar()
    Checkbutton(win, text="Moving Average Crossover", variable=strategy_var).pack(pady=10)

    def run_backtest():
        symbol = selected_symbol_var.get()
        if not symbol:
            messagebox.showwarning("No Symbol", "Please select a stock symbol.")
            return
        if not strategy_var.get():
            messagebox.showwarning("No Strategy", "Please check a strategy to run.")
            return
        try:
            from utils import run_moving_average_crossover_backtest
            trades = run_moving_average_crossover_backtest(symbol)
            if trades:
                results = "\n".join([f"{t['type']} @ {t['price']} on {t['time']}" for t in trades])
                messagebox.showinfo("Backtest Results", results)
            else:
                messagebox.showinfo("Backtest Results", "No trades found for the selected symbol.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    Button(win, text="Run Backtest", command=run_backtest).pack(pady=10)
    Button(win, text="Close", command=win.destroy).pack(pady=20)

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
                readable_ts = datetime.fromtimestamp(int(row[0])).strftime("%Y-%m-%d %H:%M")
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
