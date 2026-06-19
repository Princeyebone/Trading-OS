from engine import telegram_notifier

def run():
    print("Sending test message to Telegram...")
    try:
        telegram_notifier.notify_info("Test System", "This is a test notification from the Trading Bot AI Assistant.")
        print("Test message sent successfully!")
    except Exception as e:
        print(f"Failed to send: {e}")

if __name__ == "__main__":
    run()
