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
        
        # 1. Determine volatility regime (convert ATR points to pips)
        atr_pips = self.atr * 10.0
        
        if atr_pips <= 30.0:
            regime = 'LOW'
            sl_multiplier = 1.0
            tp_multiplier = 1.5
            min_sl_pips = 30.0
            max_sl_pips = 100.0
            min_tp_pips = 40.0
            max_tp_pips = 150.0
            
        elif atr_pips <= 60.0:
            regime = 'NORMAL'
            sl_multiplier = 1.2
            tp_multiplier = 1.4
            min_sl_pips = 40.0
            max_sl_pips = 150.0
            min_tp_pips = 50.0
            max_tp_pips = 200.0
            
        elif atr_pips <= 90.0:
            regime = 'HIGH'
            sl_multiplier = 1.5
            tp_multiplier = 1.2
            min_sl_pips = 60.0
            max_sl_pips = 200.0
            min_tp_pips = 70.0
            max_tp_pips = 250.0
            
        else:  # > 90.0
            regime = 'EXTREME'
            sl_multiplier = 2.0
            tp_multiplier = 1.0
            min_sl_pips = 80.0
            max_sl_pips = 300.0
            min_tp_pips = 80.0
            max_tp_pips = 300.0
        
        # 2. Calculate SL in pips
        sl_pips = atr_pips * sl_multiplier
        sl_pips = max(min_sl_pips, min(sl_pips, max_sl_pips))
        
        # 3. Calculate TP in pips
        tp_pips = sl_pips * tp_multiplier
        tp_pips = max(min_tp_pips, min(tp_pips, max_tp_pips))
        
        # 4. Ensure RR is at least 1.0
        rr = tp_pips / sl_pips
        if rr < 1.0:
            tp_pips = sl_pips * 1.0
            rr = 1.0
        
        # 5. Strategy-specific adjustments
        if self.strategy_type == 'SCALP':
            # Scalping: tighter parameters
            sl_pips = min(sl_pips, 120.0)
            tp_pips = min(tp_pips, 150.0)
            # Ensure minimum TP for scalping
            tp_pips = max(tp_pips, 60.0)
            sl_pips = max(sl_pips, 40.0)
        else:  # TCP
            # TCP: wider parameters
            sl_pips = min(sl_pips, 300.0)
            tp_pips = min(tp_pips, 400.0)
            tp_pips = max(tp_pips, 150.0)
            
        # 6. Convert back to raw price points for the engine
        sl = sl_pips / 10.0
        tp = tp_pips / 10.0
        
        # 7. Determine if we should trade
        should_trade = True
        if self.strategy_type == 'SCALP' and atr_pips > 150.0:
            should_trade = False  # Only skip if it's completely apocalyptic
        elif self.strategy_type == 'TCP' and atr_pips > 120.0:
            should_trade = False  # Skip TCP in extreme volatility
        
        return {
            'regime': regime,
            'sl': sl,
            'tp': tp,
            'rr': rr,
            'atr': self.atr,
            'should_trade': should_trade,
            'strategy_type': self.strategy_type,
            'reason': f"ATR={atr_pips:.1f}pips, Regime={regime}, SL={sl_pips:.1f}pips, TP={tp_pips:.1f}pips, RR={rr:.2f}"
        }
    
    def get_summary(self) -> str:
        """Get human-readable summary."""
        return (
            f"Adaptive Params: Strategy={self.strategy_type} | ATR={self.atr:.2f} pts | Regime={self.params['regime']} "
            f"| SL={self.params['sl']:.2f} | TP={self.params['tp']:.2f} | RR={self.params['rr']:.2f} "
            f"| Allowed={self.params['should_trade']}"
        )
