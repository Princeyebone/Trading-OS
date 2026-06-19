from engine.db import get_session
from app.models.config import EngineConfig
from sqlmodel import select

def run():
    session = get_session()
    config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
    if config:
        print(f"telegram_enabled in DB: {config.telegram_enabled}")
    else:
        print("No config found in DB.")
    session.close()

if __name__ == "__main__":
    run()
