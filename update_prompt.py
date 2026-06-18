from sqlmodel import Session, select
from app.database import engine
from app.models.optimizer import PromptVersion

with Session(engine) as session:
    active_prompt = session.exec(select(PromptVersion).where(PromptVersion.is_active == True)).first()
    if active_prompt:
        updated_system_prompt = active_prompt.system_prompt.replace(
            "Clear consolidation box, equal highs/lows compression",
            "Consolidation box, partial compression OR repeated liquidity clustering"
        ).replace(
            "clear consolidation / compression structure (range, equal highs/lows, or buildup)",
            "partial compression OR repeated liquidity clustering"
        )
        active_prompt.system_prompt = updated_system_prompt
        session.add(active_prompt)
        session.commit()
        print("Updated active prompt in database.")
    else:
        print("No active prompt found.")
