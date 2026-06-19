import sys
from engine.db import get_session
from sqlmodel import select
from app.models.config import EngineConfig
from engine.scalping_integration import ScalpingIntegration

def run():
    session = get_session()
    config = session.exec(select(EngineConfig).order_by(EngineConfig.id.desc())).first()
    
    if not config:
        print("No config found.")
        return
        
    print("Running check_and_execute manually...")
    integ = ScalpingIntegration()
    try:
        executed = integ.check_and_execute(config)
        print(f"Executed signals: {executed}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run()
