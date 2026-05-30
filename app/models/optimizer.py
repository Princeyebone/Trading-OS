"""
Optimizer-related SQLModel table definitions.
Tables: improvements, prompt_versions, performance_stats
"""
from datetime import datetime, date, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, Column, Text, JSON


# ─── prompt_versions ───────────────────────────────────────────────────────────
class PromptVersion(SQLModel, table=True):
    __tablename__ = "prompt_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    version: int = Field(unique=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = Field(default=False)
    system_prompt: str = Field(sa_column=Column(Text))
    user_template: str = Field(sa_column=Column(Text))
    activated_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
    # Performance metrics tracked per version
    total_signals: int = Field(default=0)
    total_trades: int = Field(default=0)
    win_rate: Optional[float] = None
    avg_r_achieved: Optional[float] = None
    notes: Optional[str] = Field(default=None, sa_column=Column(Text))


# ─── improvements ──────────────────────────────────────────────────────────────
class Improvement(SQLModel, table=True):
    __tablename__ = "improvements"

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    week_ending: date
    period_start: date
    period_end: date
    total_trades: int = Field(default=0)
    win_rate: Optional[float] = None
    avg_r: Optional[float] = None

    # Suggestion 1
    suggestion_1_impact: Optional[str] = Field(default=None, max_length=20)  # HIGH, MEDIUM, LOW
    suggestion_1_finding: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_1_recommendation: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_1_expected_impact: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_1_verify_by: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_1_status: str = Field(default="PENDING", max_length=20)  # PENDING, APPROVED, REJECTED
    suggestion_1_reviewed_at: Optional[datetime] = None
    suggestion_1_rejection_reason: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Suggestion 2
    suggestion_2_impact: Optional[str] = Field(default=None, max_length=20)
    suggestion_2_finding: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_2_recommendation: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_2_expected_impact: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_2_verify_by: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_2_status: str = Field(default="PENDING", max_length=20)
    suggestion_2_reviewed_at: Optional[datetime] = None
    suggestion_2_rejection_reason: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Suggestion 3
    suggestion_3_impact: Optional[str] = Field(default=None, max_length=20)
    suggestion_3_finding: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_3_recommendation: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_3_expected_impact: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_3_verify_by: Optional[str] = Field(default=None, sa_column=Column(Text))
    suggestion_3_status: str = Field(default="PENDING", max_length=20)
    suggestion_3_reviewed_at: Optional[datetime] = None
    suggestion_3_rejection_reason: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Raw Claude output for audit
    raw_optimizer_response: Optional[str] = Field(default=None, sa_column=Column(Text))
    prompt_version_at_analysis: int = Field(default=1)


# ─── performance_stats ─────────────────────────────────────────────────────────
class PerformanceStat(SQLModel, table=True):
    __tablename__ = "performance_stats"

    id: Optional[int] = Field(default=None, primary_key=True)
    stat_date: date = Field(unique=True)
    granularity: str = Field(default="DAILY", max_length=10)  # DAILY, WEEKLY
    total_signals: int = Field(default=0)
    trade_signals: int = Field(default=0)
    wait_signals: int = Field(default=0)
    total_trades: int = Field(default=0)
    wins: int = Field(default=0)
    losses: int = Field(default=0)
    breakevens: int = Field(default=0)
    win_rate: Optional[float] = None
    avg_r_achieved: Optional[float] = None
    total_pnl_dollars: Optional[float] = None
    equity_end_of_day: Optional[float] = None
    avg_confidence: Optional[float] = None
    # Pattern breakdown (JSON string)
    win_rate_by_pattern: Optional[str] = Field(default=None, sa_column=Column(Text))
    win_rate_by_session: Optional[str] = Field(default=None, sa_column=Column(Text))
    win_rate_by_hour: Optional[str] = Field(default=None, sa_column=Column(Text))
