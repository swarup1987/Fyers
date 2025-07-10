import threading
import time
import db
import analytics
from typing import Dict, Any, Callable
from datetime import datetime, date
import csv
import os
from zoneinfo import ZoneInfo
import event_log

class Screener(threading.Thread):
    CIRCUIT_RELOAD_INTERVAL = 600  # seconds
    PERIODIC_HIGHLOW_REFRESH = 300  # seconds

    WEEK_MIN_DAYS = 4
    MONTH_MIN_DAYS = 18

    SESSION_START = "09:14:58"
    SESSION_END = "15:30:05"

    def __init__(
        self,
        db_path,
        notice_callback: Callable[[dict], None],
        proximity_threshold_percent=1.0,
        poll_interval=2.0,
        circuit_file="daily_circuits.csv",
        session_start=SESSION_START,
        session_end=SESSION_END
    ):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.notice_callback = notice_callback
        self.threshold = proximity_threshold_percent
        self.poll_interval = poll_interval
        self.prev_ltp: Dict[str, float] = {}
        self.last_alert: Dict[str, str] = {}
        self.circuit_file = circuit_file
        self.circuits = self.load_circuit_file(circuit_file)
        self._last_circuit_reload = time.time()
        self._last_circuit_mtime = self.get_circuit_file_mtime()
        self.weekly_high_low: Dict[str, Any] = {}
        self.monthly_high_low: Dict[str, Any] = {}
        self._last_highlow_refresh = 0
        self.highlow_alert_flags: Dict[str, Dict[str, bool]] = {}
        self.session_start = session_start
        self.session_end = session_end
        self._last_alert_reset_date = None

    def is_market_open(self):
        TZ = ZoneInfo("Asia/Kolkata")
        now = datetime.now(TZ).time()
        start = datetime.strptime(self.session_start, "%H:%M:%S").time()
        end = datetime.strptime(self.session_end, "%H:%M:%S").time()
        return start <= now <= end

    def get_circuit_file_mtime(self):
        try:
            return os.path.getmtime(self.circuit_file)
        except Exception:
            return None

    def load_circuit_file(self, path) -> Dict[str, Dict[str, float]]:
        circuits = {}
        try:
            with open(path, newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    symbol = row["symbol"].strip()
                    try:
                        upper = float(row["upper_ckt"].replace(",", ""))
                        lower = float(row["lower_ckt"].replace(",", ""))
                        circuits[symbol] = {"upper": upper, "lower": lower}
                    except Exception:
                        continue
        except Exception as e:
            print(f"[Screener] Failed to load circuit file: {e}")
        return circuits

    def maybe_reload_circuits(self):
        now = time.time()
        if now - self._last_circuit_reload >= self.CIRCUIT_RELOAD_INTERVAL:
            current_mtime = self.get_circuit_file_mtime()
            if current_mtime != self._last_circuit_mtime:
                print("[Screener] Detected change in daily_circuits.csv, reloading circuit bands.")
                new_circuits = self.load_circuit_file(self.circuit_file)
                if new_circuits:
                    self.circuits = new_circuits
                    self._last_circuit_mtime = current_mtime
            self._last_circuit_reload = now

    def reset_all_alert_flags(self):
        # Called at the start of each new trading session (date)
        for flags in self.highlow_alert_flags.values():
            for key in flags:
                flags[key] = False

    def _reset_alert_flags_if_period_changed(self, symbol, old_period_highlow, new_period_highlow, period_prefix):
        if old_period_highlow != new_period_highlow:
            flags = self.highlow_alert_flags.setdefault(symbol, {
                "WEEKLY_HIGH_NEAR": False,
                "WEEKLY_HIGH_CROSSED": False,
                "WEEKLY_LOW_NEAR": False,
                "WEEKLY_LOW_CROSSED": False,
                "MONTHLY_HIGH_NEAR": False,
                "MONTHLY_HIGH_CROSSED": False,
                "MONTHLY_LOW_NEAR": False,
                "MONTHLY_LOW_CROSSED": False,
            })
            for key in flags:
                if key.startswith(period_prefix):
                    flags[key] = False

    def refresh_high_lows(self):
        try:
            old_weekly = self.weekly_high_low.copy()
            old_monthly = self.monthly_high_low.copy()
            self.weekly_high_low = analytics.get_all_symbols_weekly_high_low_with_days(self.db_path)
            self.monthly_high_low = analytics.get_all_symbols_monthly_high_low_with_days(self.db_path)
            self._last_highlow_refresh = time.time()
            # Also reset period-specific flags if period boundary crossed
            for symbol, new_highlow in self.weekly_high_low.items():
                old_highlow = old_weekly.get(symbol)
                self._reset_alert_flags_if_period_changed(symbol, old_highlow, new_highlow, "WEEKLY_")
            for symbol, new_highlow in self.monthly_high_low.items():
                old_highlow = old_monthly.get(symbol)
                self._reset_alert_flags_if_period_changed(symbol, old_highlow, new_highlow, "MONTHLY_")
        except Exception as e:
            print("[Screener] Failed to refresh weekly/monthly high/lows:", e)

    def run(self):
        self.refresh_high_lows()
        self._last_alert_reset_date = None
        while True:
            # Reset alert flags at the start of every new date (trading session)
            tz = ZoneInfo("Asia/Kolkata")
            today = datetime.now(tz).date()
            if today != self._last_alert_reset_date:
                self.reset_all_alert_flags()
                self._last_alert_reset_date = today

            if not self.is_market_open():
                time.sleep(30)
                continue
            try:
                self.maybe_reload_circuits()
                now = time.time()
                if now - self._last_highlow_refresh >= self.PERIODIC_HIGHLOW_REFRESH:
                    self.refresh_high_lows()
                latest_ticks = db.get_latest_ticks(self.db_path)
                for symbol, tick in latest_ticks.items():
                    ltp = tick.get("ltp")
                    circuit = self.circuits.get(symbol)
                    if ltp is not None and circuit:
                        upper_ckt = circuit["upper"]
                        lower_ckt = circuit["lower"]
                        if upper_ckt != 0 and lower_ckt != 0:
                            prev_ltp = self.prev_ltp.get(symbol, ltp)
                            event_type = self.detect_event(symbol, ltp, prev_ltp, upper_ckt, lower_ckt)
                            if event_type and self.last_alert.get(symbol) != event_type:
                                self.last_alert[symbol] = event_type
                                event = self._make_event_dict(symbol, event_type, ltp, upper_ckt, lower_ckt, "circuit")
                                event_log.log_event(event)
                                self.notice_callback(event)
                            self.prev_ltp[symbol] = ltp
                    self.check_highlow_alert(symbol, ltp)
            except Exception as e:
                print("[Screener Error]", e)
            time.sleep(self.poll_interval)

    def detect_event(self, symbol, ltp, prev_ltp, upper_ckt, lower_ckt):
        proximity = self.threshold / 100.0
        upper_threshold = upper_ckt * (1 - proximity)
        lower_threshold = lower_ckt * (1 + proximity)
        if upper_threshold <= ltp < upper_ckt:
            return "VERY CLOSE TO UPPER CIRCUIT"
        if lower_ckt < ltp <= lower_threshold:
            return "VERY CLOSE TO LOWER CIRCUIT"
        if prev_ltp < upper_ckt and ltp >= upper_ckt:
            return "CROSSING UPPER CIRCUIT"
        if prev_ltp > lower_ckt and ltp <= lower_ckt:
            return "CROSSING LOWER CIRCUIT"
        if ltp >= upper_ckt:
            return "CROSSED UPPER CIRCUIT"
        if ltp <= lower_ckt:
            return "CROSSED LOWER CIRCUIT"
        return None

    def check_highlow_alert(self, symbol, ltp):
        if ltp is None:
            return
        flags = self.highlow_alert_flags.setdefault(symbol, {
            "WEEKLY_HIGH_NEAR": False,
            "WEEKLY_HIGH_CROSSED": False,
            "WEEKLY_LOW_NEAR": False,
            "WEEKLY_LOW_CROSSED": False,
            "MONTHLY_HIGH_NEAR": False,
            "MONTHLY_HIGH_CROSSED": False,
            "MONTHLY_LOW_NEAR": False,
            "MONTHLY_LOW_CROSSED": False,
        })
        week_high, week_low, week_days = self.weekly_high_low.get(symbol, (None, None, 0))
        month_high, month_low, month_days = self.monthly_high_low.get(symbol, (None, None, 0))
        proximity = self.threshold / 100.0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Weekly high/low events
        if week_days >= self.WEEK_MIN_DAYS and week_high is not None and week_low is not None:
            if abs(ltp - week_high) / week_high <= proximity and not flags["WEEKLY_HIGH_NEAR"]:
                flags["WEEKLY_HIGH_NEAR"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "VERY CLOSE TO WEEKLY HIGH",
                    "ltp": ltp,
                    "high": week_high,
                    "low": week_low,
                    "period": "week"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif ltp > week_high and not flags["WEEKLY_HIGH_CROSSED"]:
                flags["WEEKLY_HIGH_CROSSED"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "CROSSED WEEKLY HIGH",
                    "ltp": ltp,
                    "high": week_high,
                    "low": week_low,
                    "period": "week"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif abs(ltp - week_low) / week_low <= proximity and not flags["WEEKLY_LOW_NEAR"]:
                flags["WEEKLY_LOW_NEAR"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "VERY CLOSE TO WEEKLY LOW",
                    "ltp": ltp,
                    "high": week_high,
                    "low": week_low,
                    "period": "week"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif ltp < week_low and not flags["WEEKLY_LOW_CROSSED"]:
                flags["WEEKLY_LOW_CROSSED"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "CROSSED WEEKLY LOW",
                    "ltp": ltp,
                    "high": week_high,
                    "low": week_low,
                    "period": "week"
                }
                event_log.log_event(event)
                self.notice_callback(event)

        # Monthly high/low events
        if month_days >= self.MONTH_MIN_DAYS and month_high is not None and month_low is not None:
            if abs(ltp - month_high) / month_high <= proximity and not flags["MONTHLY_HIGH_NEAR"]:
                flags["MONTHLY_HIGH_NEAR"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "VERY CLOSE TO MONTHLY HIGH",
                    "ltp": ltp,
                    "high": month_high,
                    "low": month_low,
                    "period": "month"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif ltp > month_high and not flags["MONTHLY_HIGH_CROSSED"]:
                flags["MONTHLY_HIGH_CROSSED"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "CROSSED MONTHLY HIGH",
                    "ltp": ltp,
                    "high": month_high,
                    "low": month_low,
                    "period": "month"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif abs(ltp - month_low) / month_low <= proximity and not flags["MONTHLY_LOW_NEAR"]:
                flags["MONTHLY_LOW_NEAR"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "VERY CLOSE TO MONTHLY LOW",
                    "ltp": ltp,
                    "high": month_high,
                    "low": month_low,
                    "period": "month"
                }
                event_log.log_event(event)
                self.notice_callback(event)
            elif ltp < month_low and not flags["MONTHLY_LOW_CROSSED"]:
                flags["MONTHLY_LOW_CROSSED"] = True
                event = {
                    "timestamp": now,
                    "symbol": symbol,
                    "event_type": "CROSSED MONTHLY LOW",
                    "ltp": ltp,
                    "high": month_high,
                    "low": month_low,
                    "period": "month"
                }
                event_log.log_event(event)
                self.notice_callback(event)

    def _make_event_dict(self, symbol, event_type, ltp, high, low, period):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "timestamp": now,
            "symbol": symbol,
            "event_type": event_type,
            "ltp": ltp,
            "high": high,
            "low": low,
            "period": period
        }