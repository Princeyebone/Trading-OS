from sqlmodel import Session, select
from app.database import engine
from app.models.optimizer import PromptVersion

with Session(engine) as session:
    active_prompt = session.exec(select(PromptVersion).where(PromptVersion.is_active == True)).first()
    if active_prompt:
        updated_system_prompt = active_prompt.system_prompt.replace(
            "Setup: Consolidation box, partial compression OR repeated liquidity clustering. Volatility squeeze.",
            "Setup: ANY ONE of the following: compression, OR liquidity clustering, OR repeated rejections near same level."
        ).replace(
            "Note: ABE is only valid when low volatility is accompanied by partial compression OR repeated liquidity clustering.",
            "Note: ABE is valid if the market shows probabilistic structure: compression OR liquidity clustering OR repeated rejections near the same level."
        )
        active_prompt.system_prompt = updated_system_prompt
        session.add(active_prompt)
        session.commit()
        print("Updated active prompt in database with probabilistic structure.")
    else:
        print("No active prompt found.")
