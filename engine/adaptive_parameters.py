"""
engine/adaptive_parameters.py — Dynamic SL/TP calculation based on ATR.
"""

class AdaptiveParameters:
    """
    Calculate adaptive SL/TP based on ATR.
    """
    
    def __init__(self, atr: float, strategy_type: str = 'TCP'):
        self.atr = atr
        self.strategy_type = strategy_type
        self.params = self.calculate()
    
    def calculate(self) -> dict:
        """Calculate all adaptive parameters."""
        
        # 1. Determine volatility regime
        if self.atr <= 3.0:
            regime = 'LOW'
            sl_multiplier = 1.0
            tp_multiplier = 1.5
            min_sl = 3.0
            max_sl = 10.0
            min_tp = 4.0
            max_tp = 15.0
            
        elif self.atr <= 6.0:
            regime = 'NORMAL'
            sl_multiplier = 1.2
            tp_multiplier = 1.4
            min_sl = 4.0
            max_sl = 15.0
            min_tp = 5.0
            max_tp = 20.0
            
        elif self.atr <= 9.0:
            regime = 'HIGH'
            sl_multiplier = 1.5
            tp_multiplier = 1.2
            min_sl = 6.0
            max_sl = 20.0
            min_tp = 7.0
            max_tp = 25.0
            
        else:  # > 9.0
            regime = 'EXTREME'
            sl_multiplier = 2.0
            tp_multiplier = 1.0
            min_sl = 8.0
            max_sl = 30.0
            min_tp = 8.0
            max_tp = 30.0
        
        # 2. Calculate SL
        sl = self.atr * sl_multiplier
        sl = max(min_sl, min(sl, max_sl))
        
        # 3. Calculate TP
        tp = sl * tp_multiplier
        tp = max(min_tp, min(tp, max_tp))
        
        # 4. Ensure RR is at least 1.0
        rr = tp / sl
        if rr < 1.0:
            tp = sl * 1.0
            rr = 1.0
        
        # 5. Strategy-specific adjustments
        if self.strategy_type == 'SCALP':
            # Scalping: tighter parameters
            sl = min(sl, 12.0)
            tp = min(tp, 15.0)
            # Ensure minimum TP for scalping
            tp = max(tp, 6.0)
            sl = max(sl, 4.0)
        else:  # TCP
            # TCP: wider parameters
            sl = min(sl, 30.0)
            tp = min(tp, 40.0)
            tp = max(tp, 15.0)
        
        # 6. Determine if we should trade
        should_trade = True
        if self.strategy_type == 'SCALP' and self.atr > 15.0:
            should_trade = False  # Only skip if it's completely apocalyptic
        elif self.strategy_type == 'TCP' and self.atr > 12.0:
            should_trade = False  # Skip TCP in extreme volatility
        
        return {
            'regime': regime,
            'sl': sl,
            'tp': tp,
            'rr': rr,
            'atr': self.atr,
            'should_trade': should_trade,
            'strategy_type': self.strategy_type,
            'reason': f"ATR={self.atr:.2f}, Regime={regime}, SL={sl:.2f}, TP={tp:.2f}, RR={rr:.2f}"
        }
    
    def get_summary(self) -> str:
        """Get human-readable summary."""
        return (
            f"Adaptive Params: Strategy={self.strategy_type} | ATR={self.atr:.2f} pts | Regime={self.params['regime']} "
            f"| SL={self.params['sl']:.2f} | TP={self.params['tp']:.2f} | RR={self.params['rr']:.2f} "
            f"| Allowed={self.params['should_trade']}"
        )
