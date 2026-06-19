from engine.db import get_session
from app.models.config import EngineConfig
from sqlmodel import select

def run():
    session = get_session()
    # Fetch the exact same way the frontend API does
    config = session.exec(select(EngineConfig).where(EngineConfig.is_active == True)).first()
    
    if config:
        print(f"Current state: {config.telegram_enabled}")
        print("Changing to True...")
        config.telegram_enabled = True
        session.add(config)
        session.commit()
        session.refresh(config)
        print(f"New state: {config.telegram_enabled}")
    else:
        print("No active config found.")
    session.close()

if __name__ == "__main__":
    run()
