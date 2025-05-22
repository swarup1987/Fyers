import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import logging
import resampler
from deepseek_strategy import Intraday15MinStrategy

STRATEGY_MAP = {
    "deep.boll.vwap.rsi.macd": Intraday15MinStrategy,
}

class WalkForwardBacktester:
    def __init__(
        self,
        strategy_key,
        interval,
        symbol,
        capital=10000,
        param_optimization=True,
        param_grid=None,
        train_days=60,
        test_days=10,
        step_days=5,
        progress_callback=None,
        param_sampler="bayesian",
        n_trials=50,
        n_random_trials=20,
        log_file="walkforward_windows.log"
    ):
        self.strategy_key = strategy_key
        self.interval = interval
        self.symbol = symbol
        self.capital = capital
        self.param_optimization = param_optimization
        self.param_grid = param_grid
        self.train_days = train_days
        self.test_days = test_days
        self.step_days = step_days
        self.progress_callback = progress_callback
        self.param_sampler = param_sampler
        self.n_trials = n_trials
        self.n_random_trials = n_random_trials
        self.log_file = log_file

        self.strategy_cls = STRATEGY_MAP.get(strategy_key)
        if self.strategy_cls is None:
            raise ValueError(f"Strategy '{strategy_key}' not implemented.")
        self.strategy = self.strategy_cls()

        self._logger = logging.getLogger("WalkForwardLogger")
        file_handler = logging.FileHandler(self.log_file)
        formatter = logging.Formatter('%(asctime)s %(message)s')
        file_handler.setFormatter(formatter)
        if not self._logger.hasHandlers():
            self._logger.addHandler(file_handler)
        self._logger.setLevel(logging.INFO)

    def load_data(self):
        data_list = resampler.get_resampled_data(self.interval)
        data_list = [row for row in data_list if row['symbol'] == self.symbol]
        if not data_list:
            raise ValueError(f"No data for symbol {self.symbol} and interval {self.interval}.")
        df = pd.DataFrame(data_list)
        df = df.sort_values("timestamp").reset_index(drop=True)
        return df

    def walkforward_splits(self, df):
        if 'timestamp' not in df.columns:
            raise ValueError("DataFrame must have 'timestamp' column.")

        df = df.copy()
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="s")
        min_date = df["datetime"].min()
        max_date = df["datetime"].max()

        walk_start = min_date

        while True:
            train_start = walk_start
            train_end = train_start + timedelta(days=self.train_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_days)
            if test_start > max_date:
                break
            train_mask = (df["datetime"] >= train_start) & (df["datetime"] < train_end)
            test_mask = (df["datetime"] >= test_start) & (df["datetime"] < test_end)
            train_df = df.loc[train_mask].reset_index(drop=True)
            test_df = df.loc[test_mask].reset_index(drop=True)
            if len(test_df) == 0 or len(train_df) == 0:
                break
            yield train_df, test_df, train_start, test_start
            walk_start = walk_start + timedelta(days=self.step_days)

    def run_backtest(self):
        df = self.load_data()
        windows = list(self.walkforward_splits(df))
        total_windows = len(windows)
        all_trades = []
        equity_curve = []
        capital = self.capital
        results_per_window = []
        param_log = []

        prev_best_params = None

        for idx, (train_df, test_df, train_start, test_start) in enumerate(windows):
            strategy = self.strategy_cls()
            best_params = None
            best_stats = None
            if self.param_optimization and hasattr(strategy, "fit"):
                def trial_print_callback(trial_num, params, score):
                    msg = f"[Win {idx+1} Trial {trial_num}] Params={params} | Sharpe={score:.5f}"
                    print(msg)
                    self._logger.info(msg)
                best_params, best_stats = strategy.fit(
                    train_df,
                    param_grid=self.param_grid,
                    sampler=self.param_sampler,
                    n_trials=self.n_trials,
                    n_random_trials=self.n_random_trials,
                    prev_best_params=prev_best_params,
                    print_callback=trial_print_callback,
                )
                print(f"[Walkforward window {idx+1}] Best parameters: {strategy.params_to_str(best_params)}")
                param_log.append(dict(window=idx+1, train_start=str(train_start), test_start=str(test_start),
                                     best_params=best_params))
                strategy.set_params(**best_params)
                prev_best_params = best_params
            signals = strategy.generate_signals(test_df)
            test_df = test_df.reset_index(drop=True)
            signals = signals.reset_index(drop=True)

            trades, equity, win, loss, gross_profit, gross_loss, max_drawdown = self.simulate_trades(test_df, signals, capital)
            all_trades.extend(trades)
            equity_curve.extend(equity)
            if len(equity) > 0:
                capital = equity[-1]

            window_result = {
                "window": idx+1,
                "train_start": train_start,
                "test_start": test_start,
                "num_trades": len(trades),
                "win": win,
                "loss": loss,
                "gross_profit": gross_profit,
                "gross_loss": gross_loss,
                "max_drawdown": max_drawdown,
                "capital_end": capital,
                "best_params": strategy.params_to_str(best_params) if best_params else "",
                "train_stats": best_stats
            }
            results_per_window.append(window_result)

            # Incremental print/log after each window
            summary_msg = (f"Window {idx+1}: {train_start.date()} - {test_start.date()} | "
                           f"Trades: {len(trades)}, P/L: {gross_profit-gross_loss:.2f}, "
                           f"Best Params: {strategy.params_to_str(best_params) if best_params else 'N/A'}")
            print(summary_msg)
            self._logger.info(summary_msg)

            if self.progress_callback is not None:
                try:
                    self.progress_callback(idx+1, total_windows, window_result)
                except Exception as ex:
                    print(f"Progress callback error: {ex}")

        total_trades = len(all_trades)
        wins = sum(1 for t in all_trades if t['pl'] > 0)
        losses = sum(1 for t in all_trades if t['pl'] <= 0)
        gross_profit = sum(t['pl'] for t in all_trades if t['pl'] > 0)
        gross_loss = -sum(t['pl'] for t in all_trades if t['pl'] <= 0)
        total_return = (equity_curve[-1]-self.capital)/self.capital if equity_curve else 0
        win_rate = wins/total_trades if total_trades else 0
        profit_factor = gross_profit/gross_loss if gross_loss else np.nan
        max_drawdown = self.compute_max_drawdown(equity_curve)
        sharpe = self.compute_sharpe(equity_curve)

        stats = {
            "Total Return": total_return,
            "Win Rate": win_rate,
            "Profit Factor": profit_factor,
            "Max Drawdown": max_drawdown,
            "Sharpe Ratio": sharpe,
            "Total Trades": total_trades,
            "Gross Profit": gross_profit,
            "Gross Loss": gross_loss
        }

        return {
            "stats": stats,
            "trades": all_trades,
            "equity_curve": equity_curve,
            "per_window": results_per_window,
            "param_log": param_log
        }

    def simulate_trades(self, df, signals, capital):
        in_trade = False
        trades = []
        equity = [capital]
        win = 0
        loss = 0
        gross_profit = 0
        gross_loss = 0
        max_equity = capital
        max_drawdown = 0

        for i, row in df.iterrows():
            sig = signals.iloc[i]
            if not in_trade and sig["signal"] in ("BUY", "SELL"):
                entry_idx = i
                entry_price = sig["entry_price"]
                stop_loss = sig["stop_loss"]
                target1 = sig["target1"]
                direction = sig["signal"]
                in_trade = True

                exit_idx = None
                exit_price = None
                exit_reason = None
                for j in range(i+1, len(df)):
                    high = df.loc[j, "high"]
                    low = df.loc[j, "low"]
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
                if exit_idx is None:
                    exit_idx = len(df)-1
                    exit_price = df.loc[exit_idx, "close"]
                    exit_reason = "EOD"
                size = 1
                if direction == "BUY":
                    pl = (exit_price - entry_price) * size
                else:
                    pl = (entry_price - exit_price) * size
                capital += pl
                trades.append({
                    "entry_idx": entry_idx,
                    "exit_idx": exit_idx,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "direction": direction,
                    "exit_reason": exit_reason,
                    "pl": pl,
                    "capital": capital,
                    "entry_time": df.loc[entry_idx, "timestamp"],
                    "exit_time": df.loc[exit_idx, "timestamp"]
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
                in_trade = False
        return trades, equity, win, loss, gross_profit, gross_loss, max_drawdown

    @staticmethod
    def compute_max_drawdown(equity_curve):
        if not equity_curve:
            return 0
        peak = equity_curve[0]
        max_dd = 0
        for x in equity_curve:
            if x > peak:
                peak = x
            dd = peak - x
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def compute_sharpe(equity_curve):
        if len(equity_curve) < 2:
            return np.nan
        rets = np.diff(equity_curve)
        if rets.std() == 0:
            return 0
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252)
        return sharpe
