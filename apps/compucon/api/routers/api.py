import re
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Bug,
    Escalation,
    Meeting,
    Plan,
    Project,
    QueuedCommand,
    Requirement,
    Task,
    VoiceCommandLog,
    utcnow,
)
from services.company import (
    COMPANY,
    log_activity,
    reset_quota_if_needed,
    try_consume_quota,
)
from models import Agent, Activity

router = APIRouter()


class RequirementIn(BaseModel):
    title: str
    description: str
    success_criteria: str = ""
    priority: str = "medium"


class ChairmanDecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject|meeting)$")
    notes: str = ""


class TaskIn(BaseModel):
    title: str
    description: str = ""
    task_type: str = "general"
    priority: str = "medium"
    project_id: int | None = None
    assignee_id: int | None = None
    assigner_name: str = "CTO"


class BugIn(BaseModel):
    project_id: int
    title: str
    steps: str = ""
    severity: str = "medium"
    assigned_to: str = "Cursor"


class EscalationIn(BaseModel):
    question: str
    asked_by: str
    context: str = ""


class EscalationAnswerIn(BaseModel):
    answer: str


class VoiceIn(BaseModel):
    text: str
    language: str = "en"


class QuotaAdjustIn(BaseModel):
    used_today: int | None = None
    daily_quota: int | None = None
    force_reset: bool = False


def agent_out(a: Agent) -> dict:
    reset_quota_if_needed(a)
    return {
        "id": a.id,
        "name": a.name,
        "provider": a.provider,
        "role": a.role,
        "specialty": a.specialty,
        "status": a.status,
        "is_human": a.is_human,
        "daily_quota": a.daily_quota,
        "used_today": a.used_today,
        "remaining": max(0, a.daily_quota - a.used_today),
        "quota_reset_at": a.quota_reset_at.isoformat() if a.quota_reset_at else None,
        "avatar_color": a.avatar_color,
        "quota_pct": round((a.used_today / a.daily_quota) * 100, 1) if a.daily_quota else 0,
    }


@router.get("/company")
def company_info(db: Session = Depends(get_db)):
    agents = db.query(Agent).all()
    for a in agents:
        reset_quota_if_needed(a)
    db.commit()
    return {
        **COMPANY,
        "stats": {
            "agents": len(agents),
            "requirements": db.query(Requirement).count(),
            "projects": db.query(Project).count(),
            "open_escalations": db.query(Escalation).filter(Escalation.status == "open").count(),
            "plans_pending": db.query(Plan).filter(Plan.status == "pending_chairman").count(),
            "queued_commands": db.query(QueuedCommand).filter(QueuedCommand.status == "waiting_quota").count(),
        },
    }


@router.get("/agents")
def list_agents(db: Session = Depends(get_db)):
    agents = db.query(Agent).order_by(Agent.id).all()
    for a in agents:
        reset_quota_if_needed(a)
    db.commit()
    return [agent_out(a) for a in agents]


@router.patch("/agents/{agent_id}/quota")
def adjust_quota(agent_id: int, body: QuotaAdjustIn, db: Session = Depends(get_db)):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if body.force_reset:
        agent.used_today = 0
        agent.quota_reset_at = utcnow() + timedelta(days=1)
        if agent.status == "quota_exhausted":
            agent.status = "idle"
        # release queued commands
        queued = (
            db.query(QueuedCommand)
            .filter(QueuedCommand.agent_id == agent.id, QueuedCommand.status == "waiting_quota")
            .all()
        )
        released = 0
        for q in queued:
            result = try_consume_quota(db, agent, q.command, 1)
            if result["ok"]:
                q.status = "released"
                released += 1
            else:
                break
        log_activity(db, "Claude (CTO)", f"Quota reset for {agent.name}. Released {released} queued command(s).")
    if body.daily_quota is not None:
        agent.daily_quota = body.daily_quota
    if body.used_today is not None:
        agent.used_today = body.used_today
        if agent.used_today >= agent.daily_quota:
            agent.status = "quota_exhausted"
    db.commit()
    return agent_out(agent)


@router.get("/cto/quota-board")
def quota_board(db: Session = Depends(get_db)):
    agents = db.query(Agent).filter(Agent.is_human.is_(False)).order_by(Agent.id).all()
    for a in agents:
        reset_quota_if_needed(a)
    db.commit()
    queued = db.query(QueuedCommand).filter(QueuedCommand.status == "waiting_quota").all()
    return {
        "monitored_by": "Claude (CTO)",
        "agents": [agent_out(a) for a in agents],
        "queued_commands": [
            {
                "id": q.id,
                "agent_id": q.agent_id,
                "command": q.command,
                "source": q.source,
                "status": q.status,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in queued
        ],
    }


@router.post("/requirements")
def create_requirement(body: RequirementIn, db: Session = Depends(get_db)):
    bde = db.query(Agent).filter(Agent.role == "bde").first()
    if bde:
        usage = try_consume_quota(db, bde, f"Add requirement: {body.title}")
        if not usage["ok"]:
            db.add(
                QueuedCommand(
                    agent_id=bde.id,
                    command=f"Add requirement: {body.title}",
                    source="bde",
                )
            )
            log_activity(db, "Claude (CTO)", f"DeepSeek quota over. Requirement intake queued.", "warn")
            db.commit()
            return {"queued": True, "message": usage["reason"]}

    req = Requirement(
        title=body.title,
        description=body.description,
        success_criteria=body.success_criteria,
        priority=body.priority,
        status="intake",
        created_by="DeepSeek (BDE)",
    )
    db.add(req)
    db.flush()

    # CTO starts planning meeting with available agents
    cto = db.query(Agent).filter(Agent.role == "cto").first()
    available = (
        db.query(Agent)
        .filter(Agent.is_human.is_(False), Agent.status != "quota_exhausted")
        .all()
    )
    names = ", ".join(a.name for a in available) or "none"
    meeting = Meeting(
        requirement_id=req.id,
        title=f"Planning: {body.title}",
        meeting_type="planning",
        status="completed",
        agenda="Scope, modules, design approach, test strategy, risks",
        participants=names,
        transcript=(
            f"Claude (CTO): Starting planning for '{body.title}'.\n"
            f"DeepSeek (BDE): Shared client requirement and success criteria.\n"
            f"Gemini (Designer): Will propose human-like UI system and fonts.\n"
            f"Cursor & ChatGPT (Devs): Proposed module split and API contracts.\n"
            f"Groq (Tester): Defined acceptance and regression checks.\n"
            f"Claude (CTO): Drafting plan for Chairman Baloda review."
        ),
        decisions="Draft plan ready for Chairman review.",
    )
    db.add(meeting)

    plan = Plan(
        requirement_id=req.id,
        title=f"Delivery Plan — {body.title}",
        summary=f"Compucon delivery plan for: {body.description[:280]}",
        modules="1) Design system & screens\n2) Core APIs\n3) Feature modules\n4) QA suite\n5) Security review",
        risks="Unclear edge cases → escalate to Chairman Baloda\nQuota exhaustion → CTO queues work",
        timeline="Design → Develop → Test → CTO gate → Chairman final review",
        status="pending_chairman",
    )
    db.add(plan)
    req.status = "chairman_review"
    if cto:
        try_consume_quota(db, cto, f"Planning meeting for {body.title}", 2)
    log_activity(db, "DeepSeek (BDE)", f"Requirement added: {body.title}")
    log_activity(db, "Claude (CTO)", f"Planning meeting completed. Plan submitted to Chairman Baloda.")
    db.commit()
    return {"requirement_id": req.id, "plan_pending": True, "meeting_id": meeting.id}


@router.get("/requirements")
def list_requirements(db: Session = Depends(get_db)):
    rows = db.query(Requirement).order_by(Requirement.id.desc()).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "success_criteria": r.success_criteria,
            "priority": r.priority,
            "status": r.status,
            "created_by": r.created_by,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)):
    rows = db.query(Plan).order_by(Plan.id.desc()).all()
    return [
        {
            "id": p.id,
            "requirement_id": p.requirement_id,
            "title": p.title,
            "summary": p.summary,
            "modules": p.modules,
            "risks": p.risks,
            "timeline": p.timeline,
            "status": p.status,
            "chairman_notes": p.chairman_notes,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]


@router.post("/plans/{plan_id}/chairman")
def chairman_decide(plan_id: int, body: ChairmanDecisionIn, db: Session = Depends(get_db)):
    plan = db.query(Plan).filter(Plan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    req = db.query(Requirement).filter(Requirement.id == plan.requirement_id).first()
    plan.chairman_notes = body.notes

    if body.decision == "reject":
        plan.status = "rejected"
        if req:
            req.status = "rejected"
        log_activity(db, "Baloda (Chairman)", f"Rejected plan: {plan.title}. {body.notes}", "warn")
        db.commit()
        return {"status": "rejected"}

    if body.decision == "meeting":
        plan.status = "chairman_meeting"
        meeting = Meeting(
            requirement_id=plan.requirement_id,
            title=f"Chairman Discussion — {plan.title}",
            meeting_type="chairman",
            status="live",
            agenda="Clarify scope with all agents under Chairman Baloda",
            participants="Baloda, Claude, Cursor, ChatGPT, Gemini, Groq, DeepSeek",
            transcript="Baloda: Calling all agents. Let's discuss this plan together.",
            decisions="Awaiting Chairman direction.",
        )
        db.add(meeting)
        log_activity(db, "Baloda (Chairman)", f"Called meeting on plan: {plan.title}")
        db.commit()
        return {"status": "meeting_called", "meeting_id": meeting.id}

    # approve → create project + starter tasks
    plan.status = "approved"
    if req:
        req.status = "approved"
    project = Project(
        requirement_id=plan.requirement_id,
        name=req.title if req else plan.title,
        status="active",
        phase="design",
        remote_workspace=f"/workspaces/compucon/{(req.title if req else 'project').lower().replace(' ', '-')}",
    )
    db.add(project)
    db.flush()

    designer = db.query(Agent).filter(Agent.role == "senior_designer").first()
    devs = db.query(Agent).filter(Agent.role == "senior_developer").all()
    tester = db.query(Agent).filter(Agent.role == "tester").first()
    cto = db.query(Agent).filter(Agent.role == "cto").first()

    starter = [
        ("Design complete product UI system", "design", designer),
        ("Implement core module A", "develop", devs[0] if devs else None),
        ("Implement core module B", "develop", devs[1] if len(devs) > 1 else (devs[0] if devs else None)),
        ("Write test plan & execute", "test", tester),
        ("Monitor quality, security, quotas", "monitor", cto),
    ]
    for title, ttype, agent in starter:
        db.add(
            Task(
                project_id=project.id,
                title=title,
                description=f"Auto-created after Chairman Baloda approved plan.",
                task_type=ttype,
                status="assigned",
                assignee_id=agent.id if agent else None,
                assigner_name="Baloda / Claude",
            )
        )
        if agent and not agent.is_human:
            agent.status = "busy"

    log_activity(db, "Baloda (Chairman)", f"Approved plan. Project created: {project.name}")
    log_activity(db, "Claude (CTO)", f"Assigned design/dev/test/monitor tasks for {project.name}")
    db.commit()
    return {"status": "approved", "project_id": project.id}


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    rows = db.query(Project).order_by(Project.id.desc()).all()
    out = []
    for p in rows:
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "status": p.status,
                "phase": p.phase,
                "remote_workspace": p.remote_workspace,
                "task_count": len(p.tasks),
                "bug_count": len(p.bugs),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )
    return out


@router.get("/projects/{project_id}")
def project_detail(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    tasks = []
    for t in p.tasks:
        tasks.append(
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "task_type": t.task_type,
                "status": t.status,
                "priority": t.priority,
                "assignee": t.assignee.name if t.assignee else None,
                "assigner_name": t.assigner_name,
                "blocked_reason": t.blocked_reason,
            }
        )
    bugs = [
        {
            "id": b.id,
            "title": b.title,
            "steps": b.steps,
            "severity": b.severity,
            "status": b.status,
            "reported_by": b.reported_by,
            "assigned_to": b.assigned_to,
        }
        for b in p.bugs
    ]
    return {
        "id": p.id,
        "name": p.name,
        "status": p.status,
        "phase": p.phase,
        "remote_workspace": p.remote_workspace,
        "tasks": tasks,
        "bugs": bugs,
    }


@router.post("/tasks")
def create_task(body: TaskIn, db: Session = Depends(get_db)):
    task = Task(
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        task_type=body.task_type,
        priority=body.priority,
        status="assigned",
        assignee_id=body.assignee_id,
        assigner_name=body.assigner_name,
    )
    db.add(task)
    if body.assignee_id:
        agent = db.query(Agent).filter(Agent.id == body.assignee_id).first()
        if agent and not agent.is_human:
            usage = try_consume_quota(db, agent, body.title)
            if not usage["ok"]:
                db.add(QueuedCommand(agent_id=agent.id, command=body.title, source="task"))
                task.status = "queued_quota"
                task.blocked_reason = usage["reason"]
                log_activity(db, "Claude (CTO)", usage["reason"], "warn")
            else:
                agent.status = "busy"
    log_activity(db, body.assigner_name, f"Assigned task: {body.title}")
    db.commit()
    return {"id": task.id, "status": task.status}


@router.get("/tasks")
def list_tasks(db: Session = Depends(get_db)):
    rows = db.query(Task).order_by(Task.id.desc()).all()
    return [
        {
            "id": t.id,
            "project_id": t.project_id,
            "title": t.title,
            "description": t.description,
            "task_type": t.task_type,
            "status": t.status,
            "priority": t.priority,
            "assignee": t.assignee.name if t.assignee else None,
            "assigner_name": t.assigner_name,
            "blocked_reason": t.blocked_reason,
        }
        for t in rows
    ]


@router.post("/bugs")
def raise_bug(body: BugIn, db: Session = Depends(get_db)):
    tester = db.query(Agent).filter(Agent.role == "tester").first()
    if tester:
        usage = try_consume_quota(db, tester, f"Bug: {body.title}")
        if not usage["ok"]:
            db.add(QueuedCommand(agent_id=tester.id, command=f"Raise bug: {body.title}", source="qa"))
            db.commit()
            return {"queued": True, "message": usage["reason"]}

    bug = Bug(
        project_id=body.project_id,
        title=body.title,
        steps=body.steps,
        severity=body.severity,
        assigned_to=body.assigned_to,
        reported_by="Groq (Tester)",
    )
    db.add(bug)
    # create fix task for developer
    dev = db.query(Agent).filter(Agent.name == body.assigned_to).first()
    fix = Task(
        project_id=body.project_id,
        title=f"Fix bug: {body.title}",
        description=body.steps,
        task_type="bugfix",
        status="assigned",
        priority="high" if body.severity in {"high", "critical"} else "medium",
        assignee_id=dev.id if dev else None,
        assigner_name="Groq (Tester)",
    )
    db.add(fix)
    log_activity(db, "Groq (Tester)", f"Raised bug to {body.assigned_to}: {body.title}", "warn")
    db.commit()
    return {"bug_id": bug.id, "fix_task_id": fix.id}


@router.post("/escalations")
def create_escalation(body: EscalationIn, db: Session = Depends(get_db)):
    esc = Escalation(question=body.question, asked_by=body.asked_by, context=body.context)
    db.add(esc)
    log_activity(db, body.asked_by, f"Escalated to Chairman Baloda: {body.question}", "warn")
    db.commit()
    return {"id": esc.id}


@router.get("/escalations")
def list_escalations(db: Session = Depends(get_db)):
    rows = db.query(Escalation).order_by(Escalation.id.desc()).all()
    return [
        {
            "id": e.id,
            "question": e.question,
            "asked_by": e.asked_by,
            "context": e.context,
            "status": e.status,
            "chairman_answer": e.chairman_answer,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in rows
    ]


@router.post("/escalations/{esc_id}/answer")
def answer_escalation(esc_id: int, body: EscalationAnswerIn, db: Session = Depends(get_db)):
    esc = db.query(Escalation).filter(Escalation.id == esc_id).first()
    if not esc:
        raise HTTPException(404, "Not found")
    esc.chairman_answer = body.answer
    esc.status = "answered"
    log_activity(db, "Baloda (Chairman)", f"Answered escalation: {body.answer}")
    db.commit()
    return {"status": "answered"}


@router.get("/meetings")
def list_meetings(db: Session = Depends(get_db)):
    rows = db.query(Meeting).order_by(Meeting.id.desc()).all()
    return [
        {
            "id": m.id,
            "requirement_id": m.requirement_id,
            "title": m.title,
            "meeting_type": m.meeting_type,
            "status": m.status,
            "agenda": m.agenda,
            "transcript": m.transcript,
            "decisions": m.decisions,
            "participants": m.participants,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in rows
    ]


@router.get("/activity")
def activity_feed(db: Session = Depends(get_db)):
    rows = db.query(Activity).order_by(Activity.id.desc()).limit(50).all()
    return [
        {
            "id": a.id,
            "actor": a.actor,
            "message": a.message,
            "level": a.level,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in rows
    ]


@router.post("/projects/{project_id}/submit-final")
def submit_final(project_id: int, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    open_bugs = [b for b in project.bugs if b.status == "open" and b.severity in {"high", "critical"}]
    if open_bugs:
        raise HTTPException(400, "Critical/high bugs still open. CTO blocked final submit.")
    project.phase = "chairman_final_review"
    project.status = "final_review"
    log_activity(db, "Claude (CTO)", f"All agents satisfied. Submitted {project.name} to Chairman Baloda.")
    db.commit()
    return {"status": "final_review"}


def parse_piki_intent(text: str) -> dict:
    t = text.strip().lower()
    # wake words
    wake = any(
        w in t
        for w in [
            "hi piki",
            "hello piki",
            "hey piki",
            "piki",
            "हाय पिकी",
            "हेलो पिकी",
            "नमस्ते पिकी",
            "पिकी",
        ]
    )
    intent = "unknown"
    if any(x in t for x in ["status", "स्थिति", "स्टेटस", "kya chal", "क्या चल"]):
        intent = "status"
    elif any(x in t for x in ["requirement", "आवश्यकता", "requirement add", "नया requirement"]):
        intent = "add_requirement_hint"
    elif any(x in t for x in ["quota", "limit", "कोटा", "लिमिट"]):
        intent = "quota"
    elif any(x in t for x in ["meeting", "मीटिंग", "बैठक"]):
        intent = "meetings"
    elif any(x in t for x in ["project", "प्रोजेक्ट"]):
        intent = "projects"
    elif any(x in t for x in ["approve", "मंजूर", "approve plan"]):
        intent = "approve_hint"
    elif any(x in t for x in ["escalat", "सवाल", "chairman", "बलोदा"]):
        intent = "escalations"
    return {"wake": wake or t.startswith("piki"), "intent": intent, "normalized": t}


@router.post("/piki/command")
def piki_command(body: VoiceIn, db: Session = Depends(get_db)):
    parsed = parse_piki_intent(body.text)
    result = ""
    if not parsed["wake"] and parsed["intent"] == "unknown":
        result = "Piki is listening for: hi piki / hello piki / हाय पिकी"
    elif parsed["intent"] == "status":
        stats = company_info(db)["stats"]
        result = (
            f"Compucon status for Chairman Baloda — "
            f"projects {stats['projects']}, pending plans {stats['plans_pending']}, "
            f"escalations {stats['open_escalations']}, queued commands {stats['queued_commands']}."
        )
    elif parsed["intent"] == "quota":
        board = quota_board(db)
        exhausted = [a["name"] for a in board["agents"] if a["status"] == "quota_exhausted"]
        result = (
            "CTO Claude quota board: "
            + (", ".join(f"{a['name']} {a['remaining']}/{a['daily_quota']}" for a in board["agents"]))
            + (f". Exhausted: {', '.join(exhausted)}" if exhausted else ". All agents within limit.")
        )
    elif parsed["intent"] == "meetings":
        n = db.query(Meeting).count()
        result = f"There are {n} meetings logged. Open Meeting Room for transcripts."
    elif parsed["intent"] == "projects":
        n = db.query(Project).count()
        result = f"Compucon has {n} active project workspace(s)."
    elif parsed["intent"] == "escalations":
        n = db.query(Escalation).filter(Escalation.status == "open").count()
        result = f"{n} open escalation(s) waiting for Chairman Baloda."
    elif parsed["intent"] == "add_requirement_hint":
        result = "Bolo requirement details — use BDE panel or say project goal after hi piki."
    elif parsed["intent"] == "approve_hint":
        pending = db.query(Plan).filter(Plan.status == "pending_chairman").count()
        result = f"{pending} plan(s) waiting. Open Chairman HQ to Approve / Reject / Call Meeting."
    else:
        result = "Piki ready. Try: hi piki status | hello piki quota | हाय पिकी प्रोजेक्ट"

    # optional: consume tiny quota on a free helper if command targets work — skip for voice OS itself
    db.add(
        VoiceCommandLog(
            raw_text=body.text,
            language=body.language,
            intent=parsed["intent"],
            result=result,
        )
    )
    log_activity(db, "Piki", f"Heard: “{body.text}” → {result}")
    db.commit()
    return {"ok": True, "intent": parsed["intent"], "result": result}
