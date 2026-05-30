"""
Prompt versions router.
GET /api/prompts              — all prompt versions
GET /api/prompts/active       — currently active prompt
PUT /api/prompts/activate/{id} — activate a specific version
POST /api/prompts             — create new prompt version
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, col
from app.database import get_session
from app.models.optimizer import PromptVersion

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    system_prompt: str
    user_template: str
    notes: str | None = None


@router.get("")
def list_prompts(session: Session = Depends(get_session)):
    prompts = session.exec(
        select(PromptVersion).order_by(col(PromptVersion.version).desc())
    ).all()
    return prompts


@router.get("/active")
def get_active_prompt(session: Session = Depends(get_session)):
    prompt = session.exec(
        select(PromptVersion).where(PromptVersion.is_active == True)
    ).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="No active prompt version found")
    return prompt


@router.put("/activate/{prompt_id}")
def activate_prompt(prompt_id: int, session: Session = Depends(get_session)):
    """Deactivate current active prompt, activate the specified one."""
    # Deactivate all
    all_prompts = session.exec(select(PromptVersion)).all()
    now = datetime.now(timezone.utc)
    for p in all_prompts:
        if p.is_active:
            p.is_active = False
            p.deactivated_at = now
            session.add(p)

    # Activate target
    target = session.get(PromptVersion, prompt_id)
    if not target:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    target.is_active = True
    target.activated_at = now
    session.add(target)
    session.commit()
    session.refresh(target)
    return {"message": f"Prompt version {target.version} activated", "prompt": target}


@router.post("")
def create_prompt(body: PromptCreate, session: Session = Depends(get_session)):
    """Create a new prompt version (auto-increments version number)."""
    existing = session.exec(select(PromptVersion)).all()
    next_version = max((p.version for p in existing), default=0) + 1

    new_prompt = PromptVersion(
        version=next_version,
        system_prompt=body.system_prompt,
        user_template=body.user_template,
        notes=body.notes,
        is_active=False,
    )
    session.add(new_prompt)
    session.commit()
    session.refresh(new_prompt)
    return new_prompt
