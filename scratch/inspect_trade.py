import sys
import MetaTrader5 as mt5

def main():
    if not mt5.initialize():
        print("MT5 initialize failed")
        return

    p = mt5.positions_get(ticket=58121431357)
    if p:
        p = p[0]
        print(f"Ticket: {p.ticket}")
        print(f"Symbol: {p.symbol}")
        print(f"Magic: {p.magic}")
        print(f"Comment: '{p.comment}'")
        print(f"Time: {p.time}")
        print(f"Price Open: {p.price_open}")
    else:
        print("Position not found in MT5.")

    mt5.shutdown()

if __name__ == "__main__":
    main()
