import numpy as np
import pandas as pd

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
        """
        Initialize strategy parameters. Avoid TA-Lib; use Pandas/Numpy only.
        """
        self.bb_period = bb_period
        self.bb_std_dev = bb_std_dev
        self.rsi_period = rsi_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.atr_period = atr_period

    def calculate_indicators(self, df):
        """
        Compute all indicators manually:
        - Bollinger Bands (std dev rolling)
        - VWAP (cumulative volume-weighted price)
        - RSI (from price changes)
        - MACD (EMA differences)
        - ATR (true range rolling)
        """
        df = df.copy()

        # --- Bollinger Bands ---
        df['middle_band'] = df['close'].rolling(self.bb_period, min_periods=1).mean()
        rolling_std = df['close'].rolling(self.bb_period, min_periods=1).std()
        df['upper_band'] = df['middle_band'] + rolling_std * self.bb_std_dev
        df['lower_band'] = df['middle_band'] - rolling_std * self.bb_std_dev

        # --- VWAP ---
        df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3
        df['cum_tp_vol'] = (df['typical_price'] * df['volume']).cumsum()
        df['cum_vol'] = df['volume'].cumsum()
        df['vwap'] = df['cum_tp_vol'] / df['cum_vol']

        # --- RSI ---
        delta = df['close'].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(self.rsi_period, min_periods=1).mean()
        avg_loss = loss.rolling(self.rsi_period, min_periods=1).mean()
        rs = avg_gain / (avg_loss + 1e-10)  # Add epsilon to avoid division by zero
        df['rsi'] = 100 - (100 / (1 + rs))

        # --- MACD ---
        df['ema_fast'] = df['close'].ewm(span=self.macd_fast, adjust=False).mean()
        df['ema_slow'] = df['close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['macd_line'] = df['ema_fast'] - df['ema_slow']
        df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal, adjust=False).mean()

        # --- ATR ---
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        df['tr'] = np.maximum(high_low, np.maximum(high_close, low_close))
        df['atr'] = df['tr'].rolling(self.atr_period, min_periods=1).mean()

        # Clean up intermediate columns if desired
        df.drop(['cum_tp_vol', 'cum_vol'], axis=1, inplace=True)

        return df

    def generate_signals(self, df):
        """
        Generate signals with entry/stop/targets.
        Returns DataFrame with columns:
        ['signal', 'entry_price', 'stop_loss', 'target1', 'target2']
        """
        df = self.calculate_indicators(df.copy())

        # --- Buy Condition ---
        buy_condition = (
            (df['close'] > df['vwap']) &
            (df['macd_line'] > df['macd_signal']) &
            (df['rsi'] < 70) &
            (df['close'] <= df['lower_band'])
        )

        # --- Sell Condition ---
        sell_condition = (
            (df['close'] < df['vwap']) &
            (df['macd_line'] < df['macd_signal']) &
            (df['rsi'] > 30) &
            (df['close'] >= df['upper_band'])
        )

        signals = np.where(buy_condition, 'BUY', np.where(sell_condition, 'SELL', ''))

        # Entry price is current close for signal rows, otherwise NaN
        entry_price = np.where(signals != '', df['close'], np.nan)

        # Stop-loss logic
        stop_loss = np.where(
            signals == 'BUY',
            df['close'] - 1.5 * df['atr'],
            np.where(
                signals == 'SELL',
                df['close'] + 1.5 * df['atr'],
                np.nan
            )
        )

        # Targets
        # For BUY: RR 1.5, For SELL: RR 2.0
        target1 = np.where(
            signals == 'BUY',
            df['close'] + 1.5 * (df['close'] - stop_loss),
            np.where(
                signals == 'SELL',
                df['close'] - 2.0 * (stop_loss - df['close']),
                np.nan
            )
        )

        # You may define target2 differently or same as target1 for now.
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

        # Optionally, include timestamp/index and other indicators if desired
        return signals_df
