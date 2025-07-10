import db
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# Session guard utility
def is_market_open(session_start="09:14:58", session_end="15:30:05"):
    TZ = ZoneInfo("Asia/Kolkata")
    now = datetime.now(TZ).time()
    start = datetime.strptime(session_start, "%H:%M:%S").time()
    end = datetime.strptime(session_end, "%H:%M:%S").time()
    return start <= now <= end

def ist_epoch_for_date_time(date_obj, time_obj):
    TZ = ZoneInfo("Asia/Kolkata")
    dt = datetime.combine(date_obj, time_obj)
    dt_ist = dt.replace(tzinfo=TZ)
    ist_epoch_origin = datetime(1970, 1, 1, 5, 30, 0, tzinfo=TZ)
    return int((dt_ist - ist_epoch_origin).total_seconds())

def get_period_epochs(period: str, reference_dt: datetime = None):
    TZ = ZoneInfo("Asia/Kolkata")
    if reference_dt is None:
        now = datetime.now(TZ)
    else:
        now = reference_dt.astimezone(TZ)
    date_now = now.date()
    if period == "week":
        weekday = date_now.weekday()
        monday = date_now - timedelta(days=weekday)
        sunday = monday + timedelta(days=6)
        start_epoch = ist_epoch_for_date_time(monday, time(0, 0, 0))
        end_epoch = ist_epoch_for_date_time(sunday, time(23, 59, 59))
        return start_epoch, end_epoch
    elif period == "month":
        first = date_now.replace(day=1)
        if date_now.month == 12:
            next_month = date_now.replace(year=date_now.year + 1, month=1, day=1)
        else:
            next_month = date_now.replace(month=date_now.month + 1, day=1)
        last = next_month - timedelta(days=1)
        start_epoch = ist_epoch_for_date_time(first, time(0,0,0))
        end_epoch = ist_epoch_for_date_time(last, time(23,59,59))
        return start_epoch, end_epoch
    else:
        raise ValueError("period must be 'week' or 'month'")

def get_weekly_high_low_with_days(symbol, db_path=db.DB_PATH):
    if not is_market_open():
        return (None, None, 0)
    start_epoch, end_epoch = get_period_epochs("week")
    return db.get_high_low_days_for_period(symbol, start_epoch, end_epoch, db_path)

def get_monthly_high_low_with_days(symbol, db_path=db.DB_PATH):
    if not is_market_open():
        return (None, None, 0)
    start_epoch, end_epoch = get_period_epochs("month")
    return db.get_high_low_days_for_period(symbol, start_epoch, end_epoch, db_path)

def get_all_symbols_weekly_high_low_with_days(db_path=db.DB_PATH):
    if not is_market_open():
        return {}
    start_epoch, end_epoch = get_period_epochs("week")
    return db.get_high_low_days_for_period_all_symbols(start_epoch, end_epoch, db_path)

def get_all_symbols_monthly_high_low_with_days(db_path=db.DB_PATH):
    if not is_market_open():
        return {}
    start_epoch, end_epoch = get_period_epochs("month")
    return db.get_high_low_days_for_period_all_symbols(start_epoch, end_epoch, db_path)
