import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

def run_ws_collector_at_schedule(start_time_str, end_time_str, start_callback, stop_callback):
    """
    Schedules the start_callback to run at start_time_str (IST) and stop_callback at end_time_str (IST).
    This spawns a background thread and returns immediately.
    """
    def scheduler():
        TZ = ZoneInfo("Asia/Kolkata")
        START_TIME = datetime.strptime(start_time_str, "%H:%M:%S").time()
        END_TIME = datetime.strptime(end_time_str, "%H:%M:%S").time()
        started = False
        stopped = False
        warned = False

        while True:
            now_dt = datetime.now(TZ)
            now = now_dt.time()
            # Make start_dt timezone-aware
            start_dt = datetime.combine(now_dt.date(), START_TIME, tzinfo=TZ)
            delta_to_start = (start_dt - now_dt).total_seconds()
            if not warned and 0 < delta_to_start <= 60:
                print("Market data collection session will start in 60 seconds...")
                warned = True
            if not started and now >= START_TIME:
                start_callback()
                started = True
            if not stopped and now >= END_TIME:
                stop_callback()
                stopped = True
                break
            time.sleep(1)
    thread = threading.Thread(target=scheduler, daemon=True)
    thread.start()