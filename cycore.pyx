# cycore.pyx - Cython-accelerated core for fast trade simulation

import numpy as np
cimport numpy as np

def simulate_trades_core(
    np.ndarray[np.float64_t, ndim=1] arr_high,
    np.ndarray[np.float64_t, ndim=1] arr_low,
    np.ndarray[np.float64_t, ndim=1] arr_close,
    np.ndarray[np.int64_t, ndim=1] arr_timestamp,
    np.ndarray arr_signal,  # unicode type, assume "U8"
    np.ndarray[np.float64_t, ndim=1] arr_entry_price,
    np.ndarray[np.float64_t, ndim=1] arr_stop_loss,
    np.ndarray[np.float64_t, ndim=1] arr_target1,
    double capital_start
):
    cdef Py_ssize_t n = arr_high.shape[0]
    cdef Py_ssize_t i, j, entry_idx, exit_idx
    cdef double capital = capital_start
    cdef double max_equity = capital
    cdef double max_drawdown = 0.0
    cdef double gross_profit = 0.0
    cdef double gross_loss = 0.0
    cdef int win = 0
    cdef int loss = 0
    cdef int in_trade = 0
    cdef double entry_price = 0.0
    cdef double stop_loss = 0.0
    cdef double target1 = 0.0
    cdef double exit_price = 0.0
    cdef double pl = 0.0
    cdef object direction = None
    trades = []
    equity = [capital]
    for i in range(n):
        sig = arr_signal[i]
        if not in_trade and (sig == "BUY" or sig == "SELL"):
            entry_idx = i
            entry_price = arr_entry_price[i]
            stop_loss = arr_stop_loss[i]
            target1 = arr_target1[i]
            direction = sig
            in_trade = 1
            exit_idx = -1
            exit_price = 0.0
            exit_reason = None
            for j in range(i+1, n):
                high = arr_high[j]
                low = arr_low[j]
                if direction == "BUY":
                    if low <= stop_loss:
                        exit_idx = j
                        exit_price = stop_loss
                        exit_reason = "Stop"
                        break
                    elif high >= target1:
                        exit_idx = j
                        exit_price = target1
                        exit_reason = "Target"
                        break
                else:
                    if high >= stop_loss:
                        exit_idx = j
                        exit_price = stop_loss
                        exit_reason = "Stop"
                        break
                    elif low <= target1:
                        exit_idx = j
                        exit_price = target1
                        exit_reason = "Target"
                        break
            if exit_idx == -1:
                exit_idx = n-1
                exit_price = arr_close[exit_idx]
                exit_reason = "EOD"
            size = 1
            if direction == "BUY":
                pl = (exit_price - entry_price) * size
            else:
                pl = (entry_price - exit_price) * size
            capital += pl
            trades.append({
                "entry_idx": int(entry_idx),
                "exit_idx": int(exit_idx),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "direction": direction,
                "exit_reason": exit_reason,
                "pl": float(pl),
                "capital": float(capital),
                "entry_time": int(arr_timestamp[entry_idx]),
                "exit_time": int(arr_timestamp[exit_idx])
            })
            equity.append(capital)
            if pl > 0:
                win += 1
                gross_profit += pl
            else:
                loss += 1
                gross_loss -= pl
            if capital > max_equity:
                max_equity = capital
            dd = (max_equity - capital)
            if dd > max_drawdown:
                max_drawdown = dd
            in_trade = 0
    eq = np.array(equity)
    sharpe = 0.0
    if eq.shape[0] >= 2:
        rets = np.diff(eq)
        std = np.std(rets)
        if std == 0:
            sharpe = 0.0
        else:
            sharpe = np.mean(rets) / std * np.sqrt(252)
    stats = {
        "sharpe": sharpe,
        "profit": capital - capital_start,
        "win": win,
        "loss": loss,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "num_trades": win + loss
    }
    return stats, trades
