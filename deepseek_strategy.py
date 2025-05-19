import numpy as np
import pandas as pd
import itertools

class Intraday15MinStrategy:
    def __init__(
        self,
        bb_period=20,
        bb_std_dev=2,
        rsi_period=8,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        atr_period=14
    ):
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period

    def set_params(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)

    def get_params(self):
        return {
            'bb_period': self.bb_period,
            'bb_std_dev': self.bb_std_dev,
            'rsi_period': self.rsi_period,
            'macd_fast': self.macd_fast,
            'macd_slow': self.macd_slow,
            'macd_signal': self.macd_signal,
            'atr_period': self.atr_period
        }

    def calculate_indicators(self, df):
        df = df.copy()
        df['middle_band'] = df['close'].rolling(self.bb_period, min_periods=1).mean()
        rolling_std = df['close'].rolling(self.bb_period, min_periods=1).std()
        df['upper_band'] = df['middle_band'] + rolling_std * self.bb_std_dev
        df['lower_band'] = df['middle_band'] - rolling_std * self.bb_std_dev
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['cum_tp_vol'] = (df['typical_price'] * df['volume']).cumsum()
        df['cum_vol'] = df['volume'].cumsum()
        df['vwap'] = df['cum_tp_vol'] / df['cum_vol']
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self.rsi_period, min_periods=1).mean()
        avg_loss = loss.rolling(self.rsi_period, min_periods=1).mean()
        rs = avg_gain / (avg_loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['ema_fast'] = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd_line'] = df['ema_fast'] - df['ema_slow']
        df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal, adjust=False).mean()
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        df['tr'] = np.maximum(high_low, np.maximum(high_close, low_close))
        df['atr'] = df['tr'].rolling(self.atr_period, min_periods=1).mean()
        df.drop(['cum_tp_vol', 'cum_vol'], axis=1, inplace=True)
        return df

    def generate_signals(self, df):
        df = self.calculate_indicators(df.copy())
        buy_condition = (
            (df['close'] > df['vwap']) &
            (df['macd_line'] > df['macd_signal']) &
            (df['rsi'] < 70) &
            (df['close'] <= df['lower_band'])
        )
        sell_condition = (
            (df['close'] < df['vwap']) &
            (df['macd_line'] < df['macd_signal']) &
            (df['rsi'] > 30) &
            (df['close'] >= df['upper_band'])
        )
        signals = np.where(buy_condition, 'BUY', np.where(sell_condition, 'SELL', ''))
        entry_price = np.where(signals != '', df['close'], np.nan)
        stop_loss = np.where(
            signals == 'BUY',
            df['close'] - 1.5 * df['atr'],
            np.where(
                signals == 'SELL',
                df['close'] + 1.5 * df['atr'],
                np.nan
            )
        )
        target1 = np.where(
            signals == 'BUY',
            df['close'] + 1.5 * (df['close'] - stop_loss),
            np.where(
                signals == 'SELL',
                df['close'] - 2.0 * (stop_loss - df['close']),
                np.nan
            )
        )
        target2 = np.where(
            signals == 'BUY',
            df['close'] + 2.0 * (df['close'] - stop_loss),
            np.where(
                signals == 'SELL',
                df['close'] - 3.0 * (stop_loss - df['close']),
                np.nan
            )
        )
        signals_df = pd.DataFrame({
            'signal': signals,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'target1': target1,
            'target2': target2
        }, index=df.index)
        return signals_df

    def backtest_on_signals(self, df, signals):
        in_trade = False
        trades = []
        capital = 10000
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
        sharpe = self.compute_sharpe(equity)
        return {
            "sharpe": sharpe,
            "profit": capital - 10000,
            "win": win,
            "loss": loss,
            "gross_profit": gross_profit,
            "gross_loss": gross_loss
        }

    @staticmethod
    def compute_sharpe(equity_curve):
        if len(equity_curve) < 2:
            return np.nan
        rets = np.diff(equity_curve)
        if rets.std() == 0:
            return 0
        sharpe = np.mean(rets) / np.std(rets) * np.sqrt(252)
        return sharpe

    @staticmethod
    def _evaluate_param_combo(params_dict, train_df_dict):
        """
        Helper for multiprocessing: receives dict of params and dict version of DataFrame,
        reconstructs DataFrame, runs signals + backtest, returns (params, score, stats).
        """
        # Reconstruct DataFrame
        train_df = pd.DataFrame(train_df_dict)
        strat = Intraday15MinStrategy(**params_dict)
        signals = strat.generate_signals(train_df)
        stats = strat.backtest_on_signals(train_df, signals)
        score = stats.get('sharpe', 0)
        if np.isnan(score):
            score = -np.inf
        return (params_dict, score, stats)

    def fit(self, train_df, param_grid=None, metric='sharpe'):
        """
        Optimize parameters on training data using multiprocessing for grid search.
        param_grid: dict of {param: list of values}
        """
        import concurrent.futures

        if param_grid is None:
            param_grid = {
                "bb_period": [10, 15, 20],
                "bb_std_dev": [1.5, 2],
                "rsi_period": [6, 8, 14],
                "macd_fast": [8, 12],
                "macd_slow": [21, 26],
                "macd_signal": [7, 9],
                "atr_period": [10, 14]
            }

        param_names = list(param_grid.keys())
        param_combinations = list(itertools.product(*[param_grid[k] for k in param_names]))
        param_dicts = [dict(zip(param_names, vals)) for vals in param_combinations]
        train_df_dict = train_df.to_dict(orient='list')

        # Multiprocessing pool
        with concurrent.futures.ProcessPoolExecutor() as executor:
            results = list(executor.map(
                Intraday15MinStrategy._evaluate_param_combo,
                param_dicts,
                [train_df_dict]*len(param_dicts)
            ))

        # Find best
        best_score = -np.inf
        best_params = self.get_params()
        best_stats = None

        for params, score, stats in results:
            if score > best_score:
                best_score = score
                best_params = params.copy()
                best_stats = stats.copy() if stats else None

        self.set_params(**best_params)
        return best_params, best_stats
