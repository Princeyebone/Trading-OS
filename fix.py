import re

file_path = "c:/Users/HP/OneDrive/Desktop/tb/backend/engine/broker_executor.py"
with open(file_path, "r") as f:
    content = f.read()

content = content.replace("def place_order(", "def place_order(\n    symbol: str,")
content = content.replace("def place_limit_order(", "def place_limit_order(\n    symbol: str,")
content = content.replace("def get_open_positions() -> list:", "def get_open_positions(symbol: str = 'XAUUSD') -> list:")
content = content.replace("def close_position(ticket: int) -> bool:", "def close_position(ticket: int, symbol: str = 'XAUUSD') -> bool:")
content = content.replace("def modify_position_sl(ticket: int, new_sl: float) -> bool:", "def modify_position_sl(ticket: int, new_sl: float, symbol: str = 'XAUUSD') -> bool:")
content = content.replace("def close_partial_position(ticket: int, percent: float = 50.0) -> bool:", "def close_partial_position(ticket: int, percent: float = 50.0, symbol: str = 'XAUUSD') -> bool:")
content = content.replace("def check_spread(symbol: str = SYMBOL) -> float:", "def check_spread(symbol: str = 'XAUUSD') -> float:")
content = content.replace("def place_straddle_orders(", "def place_straddle_orders(\n    symbol: str,")
content = content.replace("def check_straddle_status(buy_ticket: int, sell_ticket: int) -> dict:", "def check_straddle_status(buy_ticket: int, sell_ticket: int, symbol: str = 'XAUUSD') -> dict:")

content = re.sub(r'(?<!_)SYMBOL(?!_)', 'symbol', content)
content = content.replace('symbol = "XAUUSD"', 'SYMBOL = "XAUUSD"')

content = content.replace("def place_order(\n    symbol: str,", "def place_order(\n    symbol: str = 'XAUUSD',")
content = content.replace("def place_limit_order(\n    symbol: str,", "def place_limit_order(\n    symbol: str = 'XAUUSD',")
content = content.replace("def place_straddle_orders(\n    symbol: str,", "def place_straddle_orders(\n    symbol: str = 'XAUUSD',")

with open(file_path, "w") as f:
    f.write(content)
print("Done")
