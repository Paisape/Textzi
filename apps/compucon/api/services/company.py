from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from models import Activity, Agent, utcnow


COMPANY = {
    "name": "Compucon",
    "chairman": "Baloda",
    "voice_assistant": "Piki",
    "tagline": "AI Agent IT Company OS",
}


SEED_AGENTS = [
    {
        "name": "Baloda",
        "provider": "Human",
        "role": "chairman",
        "specialty": "Final authority, strategy, approvals",
        "is_human": True,
        "daily_quota": 9999,
        "avatar_color": "#d4a574",
        "status": "online",
    },
    {
        "name": "Claude",
        "provider": "Anthropic",
        "role": "cto",
        "specialty": "Architecture, planning, quality & quota control",
        "daily_quota": 80,
        "avatar_color": "#c4a484",
        "status": "idle",
    },
    {
        "name": "Cursor",
        "provider": "Cursor",
        "role": "senior_developer",
        "specialty": "Full-stack implementation, refactors, PRs",
        "daily_quota": 120,
        "avatar_color": "#2dd4bf",
        "status": "idle",
    },
    {
        "name": "ChatGPT",
        "provider": "OpenAI",
        "role": "senior_developer",
        "specialty": "Backend modules, APIs, integrations",
        "daily_quota": 100,
        "avatar_color": "#5eead4",
        "status": "idle",
    },
    {
        "name": "Gemini",
        "provider": "Google",
        "role": "senior_designer",
        "specialty": "Human-like UI, fonts, product design systems",
        "daily_quota": 90,
        "avatar_color": "#38bdf8",
        "status": "idle",
    },
    {
        "name": "Groq",
        "provider": "Groq (free tier)",
        "role": "tester",
        "specialty": "Test cases, bugs, regression, release checks",
        "daily_quota": 150,
        "avatar_color": "#f59e0b",
        "status": "idle",
    },
    {
        "name": "DeepSeek",
        "provider": "DeepSeek (free tier)",
        "role": "bde",
        "specialty": "Requirement intake, client needs, scope clarity",
        "daily_quota": 100,
        "avatar_color": "#a78bfa",
        "status": "idle",
    },
]


def log_activity(db: Session, actor: str, message: str, level: str = "info") -> None:
    db.add(Activity(actor=actor, message=message, level=level))


def ensure_seed(db: Session) -> None:
    if db.query(Agent).count() == 0:
        for item in SEED_AGENTS:
            agent = Agent(**item)
            agent.quota_reset_at = utcnow() + timedelta(days=1)
            db.add(agent)
        log_activity(db, "Compucon", "Company bootstrapped. Chairman Baloda online. Piki ready.")
        db.commit()


def reset_quota_if_needed(agent: Agent) -> bool:
    now = utcnow()
    reset_at = agent.quota_reset_at
    if reset_at is not None and reset_at.tzinfo is None:
        reset_at = reset_at.replace(tzinfo=timezone.utc)
    if reset_at is None or now >= reset_at:
        agent.used_today = 0
        agent.quota_reset_at = now + timedelta(days=1)
        if agent.status == "quota_exhausted":
            agent.status = "idle"
        return True
    return False


def try_consume_quota(db: Session, agent: Agent, action: str, cost: int = 1) -> dict:
    reset_quota_if_needed(agent)
    remaining = agent.daily_quota - agent.used_today
    if remaining < cost:
        agent.status = "quota_exhausted"
        db.commit()
        return {
            "ok": False,
            "queued": True,
            "reason": f"{agent.name} daily limit over. Command queued until quota resets.",
            "remaining": max(0, remaining),
            "resets_at": agent.quota_reset_at.isoformat() if agent.quota_reset_at else None,
        }

    agent.used_today += cost
    if agent.used_today >= agent.daily_quota:
        agent.status = "quota_exhausted"
    elif agent.status == "idle":
        agent.status = "busy"

    from models import UsageLog

    db.add(UsageLog(agent_id=agent.id, action=action, tokens_used=cost, queued=False))
    db.commit()
    return {
        "ok": True,
        "queued": False,
        "remaining": agent.daily_quota - agent.used_today,
        "resets_at": agent.quota_reset_at.isoformat() if agent.quota_reset_at else None,
    }
