import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv(dotenv_path="c:/Users/HP/OneDrive/Desktop/tb/backend/.env")

login = int(os.getenv("MT5_LOGIN", 0))
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "")

if not mt5.initialize(login=login, password=password, server=server):
    print("MT5 Init Failed:", mt5.last_error())
    exit(1)

positions = mt5.positions_get(symbol="XAUUSD")
if positions is None or len(positions) == 0:
    print("No open positions for XAUUSD.")
else:
    print(f"Found {len(positions)} open positions for XAUUSD:\n")
    for p in positions:
        direction = "LONG" if p.type == mt5.POSITION_TYPE_BUY else "SHORT"
        
        # Determine strategy from magic map (from trade_manager.py)
        _MAGIC_MAP = {
            202600: "XAGI1",  202601: "XAGI1-Swing",
            202602: "XAGI2",  202603: "XAGI3",
            202604: "XAGI4",  202700: "XAGI3",
            202800: "XAGI5",  202900: "XAGI6",
            202808: "XAGI8-IFVG", 202809: "XAGI9-3Candle",
            203000: "EUSDI6", 203100: "EUSDI7",
            203200: "GI2",    203300: "GI3",
        }
        sys_name = _MAGIC_MAP.get(p.magic, f"Unknown (Magic: {p.magic})")
        
        # If there's a comment, display it
        comment = p.comment if p.comment else "No comment"
        
        print(f"Ticket: {p.ticket}")
        print(f"Strategy: {sys_name} | Comment: {comment}")
        print(f"Direction: {direction} | Volume: {p.volume} lots")
        print(f"Entry Price: {p.price_open:.2f}")
        print(f"Current Price: {p.price_current:.2f}")
        print(f"Stop Loss: {p.sl:.2f} | Take Profit: {p.tp:.2f}")
        
        pips_profit = (p.price_current - p.price_open) * 10 if direction == "LONG" else (p.price_open - p.price_current) * 10
        print(f"Profit: ${p.profit:.2f} ({pips_profit:+.1f} pips)\n")

mt5.shutdown()
