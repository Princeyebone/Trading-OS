import re

with open('engine/trade_manager.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update the telegram_notifier.notify_trade_executed call inside trade_manager.py
content = re.sub(
    r'(reasoning=f"\{strat_name\} Limit Order Filled"\s*\n\s*\))',
    r'\1,\n                        symbol=trade_symbol,\n                        system=sig.session if (sig := session.get(Signal, trade.signal_id)) else "Unknown"\n                    )',
    content
)

# 2. Add sig fetch globally at the start of open_trades loop
content = re.sub(
    r'(ticket = int\(trade\.broker_order_id\))',
    r'\1\n            from app.models.signals import Signal\n            sig = session.get(Signal, trade.signal_id)\n            sys_num = sig.session if sig else "Unknown"',
    content
)

# 3. Update notify_success and notify_info title strings
content = re.sub(
    r'telegram_notifier\.notify_info\("([^"]+)", f"🚀 Trade #\{trade\.id\} LOCKED',
    r'telegram_notifier.notify_info(f"[{trade_symbol} | Sys #{sys_num}] \1", f"🚀 Trade #{trade.id} (Ticket #{ticket}) LOCKED',
    content
)

content = re.sub(
    r'telegram_notifier\.notify_success\("([^"]+)", f"🎯 Trade #\{trade\.id\} closed at',
    r'telegram_notifier.notify_success(f"[{trade_symbol} | Sys #{sys_num}] \1", f"🎯 Trade #{trade.id} (Ticket #{ticket}) closed at',
    content
)

# 4. Update the terminal logs
content = re.sub(
    r'logger\.info\(f"📈 \[([^\]]+)\] Trade #\{trade\.id\}: ACTIVE:',
    r'logger.info(f"📈 [{trade_symbol} | Sys #{sys_num} | Ticket #{ticket}] Trade #{trade.id}: ACTIVE:',
    content
)

# 5. Fix Step TP logs and force closes
content = re.sub(
    r'logger\.info\(f"📊 \[Step TP Monitor\] Trade #\{trade\.id\} \(\{trade_type\}\): ACTIVE:',
    r'logger.info(f"📊 [{trade_symbol} | Sys #{sys_num} | Ticket #{ticket}] Trade #{trade.id} ({trade_type}): ACTIVE:',
    content
)

content = re.sub(
    r'telegram_notifier\.notify_info\("Step TP", f"🔒 Trade #\{trade\.id\} \(Ticket #\{ticket\}\) LOCKED',
    r'telegram_notifier.notify_info(f"[{trade_symbol} | Sys #{sys_num}] Step TP", f"🔒 Trade #{trade.id} (Ticket #{ticket}) LOCKED',
    content
)

content = re.sub(
    r'telegram_notifier\.notify_success\("Step TP Hit", f"🎯 Trade #\{trade\.id\} \(Ticket #\{ticket\}\) closed',
    r'telegram_notifier.notify_success(f"[{trade_symbol} | Sys #{sys_num}] Step TP Hit", f"🎯 Trade #{trade.id} (Ticket #{ticket}) closed',
    content
)

content = re.sub(
    r'telegram_notifier\.notify_success\("XAGI4 Force Close", f"⏰ Trade #\{trade\.id\} Force Closed',
    r'telegram_notifier.notify_success(f"[{trade_symbol} | Sys #{sys_num}] Force Close", f"⏰ Trade #{trade.id} (Ticket #{ticket}) Force Closed',
    content
)

with open('engine/trade_manager.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Patch generated successfully.')
