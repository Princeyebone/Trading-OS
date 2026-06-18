import json
from sqlmodel import Session, select
from app.database import engine
from app.models.optimizer import PromptVersion

def main():
    with Session(engine) as session:
        active_prompt = session.exec(select(PromptVersion).where(PromptVersion.is_active == True)).first()
        if active_prompt:
            if "[RAW TAPE METRICS]" not in active_prompt.user_template:
                new_template = active_prompt.user_template + "\n\n[RAW TAPE METRICS]\n{tape_metrics_json}\n"
                active_prompt.user_template = new_template
                session.add(active_prompt)
                session.commit()
                print("Successfully added [RAW TAPE METRICS] section to the active prompt template.")
            else:
                print("Prompt already has the [RAW TAPE METRICS] section.")
        else:
            print("No active prompt found in database.")

if __name__ == "__main__":
    main()
