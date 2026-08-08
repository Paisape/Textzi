import { useEffect, useMemo, useState } from 'react'
import { api } from './lib/api'

const NAV = [
  ['hq', 'Chairman HQ'],
  ['floor', 'Company Floor'],
  ['intake', 'BDE Intake'],
  ['meetings', 'Meeting Room'],
  ['projects', 'Project Floor'],
  ['quota', 'CTO Quotas'],
]

function statusPill(status) {
  if (status === 'quota_exhausted') return 'pill danger'
  if (status === 'busy' || status === 'live') return 'pill warn'
  return 'pill'
}

function PikiDock({ onDone }) {
  const [listening, setListening] = useState(false)
  const [text, setText] = useState('')
  const [reply, setReply] = useState('Say “Hi Piki” or “हाय पिकी”…')
  const [lang, setLang] = useState('en-IN')

  async function send(raw, language = 'en') {
    const value = (raw || text).trim()
    if (!value) return
    const res = await api.piki(value, language)
    setReply(res.result)
    setText('')
    onDone?.()
    if ('speechSynthesis' in window) {
      const u = new SpeechSynthesisUtterance(res.result)
      u.lang = language === 'hi' ? 'hi-IN' : 'en-IN'
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(u)
    }
  }

  function startListen() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SR) {
      setReply('Voice API not supported in this browser. Type commands instead.')
      return
    }
    const rec = new SR()
    rec.lang = lang
    rec.interimResults = false
    rec.maxAlternatives = 1
    setListening(true)
    rec.onresult = (e) => {
      const said = e.results[0][0].transcript
      setText(said)
      send(said, lang.startsWith('hi') ? 'hi' : 'en')
    }
    rec.onerror = () => setListening(false)
    rec.onend = () => setListening(false)
    rec.start()
  }

  return (
    <div className={`panel piki ${listening ? 'listening' : ''}`}>
      <h3>Piki · Voice OS</h3>
      <p className="muted" style={{ marginTop: 0 }}>
        Wake: hi piki / hello piki / हाय पिकी
      </p>
      <div className="row" style={{ marginBottom: '0.6rem' }}>
        <select value={lang} onChange={(e) => setLang(e.target.value)} style={{ width: 'auto' }}>
          <option value="en-IN">English</option>
          <option value="hi-IN">Hindi</option>
        </select>
        <button className="primary" onClick={startListen}>
          {listening ? 'Listening…' : 'Listen'}
        </button>
      </div>
      <div className="form-stack">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="hi piki status / हाय पिकी कोटा"
          onKeyDown={(e) => e.key === 'Enter' && send()}
        />
        <button onClick={() => send()}>Send to Piki</button>
      </div>
      <p style={{ marginBottom: 0, marginTop: '0.75rem' }}>{reply}</p>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('hq')
  const [company, setCompany] = useState(null)
  const [agents, setAgents] = useState([])
  const [plans, setPlans] = useState([])
  const [projects, setProjects] = useState([])
  const [meetings, setMeetings] = useState([])
  const [activity, setActivity] = useState([])
  const [escalations, setEscalations] = useState([])
  const [quota, setQuota] = useState(null)
  const [tasks, setTasks] = useState([])
  const [selectedProject, setSelectedProject] = useState(null)
  const [reqForm, setReqForm] = useState({
    title: '',
    description: '',
    success_criteria: '',
    priority: 'medium',
  })
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState('')

  async function refresh() {
    const [c, a, p, pr, m, act, esc, q, t] = await Promise.all([
      api.company(),
      api.agents(),
      api.plans(),
      api.projects(),
      api.meetings(),
      api.activity(),
      api.escalations(),
      api.quotaBoard(),
      api.tasks(),
    ])
    setCompany(c)
    setAgents(a)
    setPlans(p)
    setProjects(pr)
    setMeetings(m)
    setActivity(act)
    setEscalations(esc)
    setQuota(q)
    setTasks(t)
  }

  useEffect(() => {
    refresh().catch((e) => setToast(e.message))
    const id = setInterval(() => refresh().catch(() => {}), 8000)
    return () => clearInterval(id)
  }, [])

  const pendingPlans = useMemo(() => plans.filter((p) => p.status === 'pending_chairman' || p.status === 'chairman_meeting'), [plans])
  const openEsc = useMemo(() => escalations.filter((e) => e.status === 'open'), [escalations])

  async function decide(planId, decision) {
    setBusy(true)
    try {
      const notes = decision === 'reject' ? window.prompt('Rejection notes?', '') || '' : ''
      await api.chairmanDecide(planId, { decision, notes })
      setToast(decision === 'approve' ? 'Project created after approval' : `Plan ${decision}`)
      await refresh()
      if (decision === 'approve') setTab('projects')
    } catch (e) {
      setToast(e.message)
    } finally {
      setBusy(false)
    }
  }

  async function submitRequirement(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await api.createRequirement(reqForm)
      setReqForm({ title: '', description: '', success_criteria: '', priority: 'medium' })
      setToast('BDE submitted. CTO planned. Awaiting Chairman Baloda.')
      await refresh()
      setTab('hq')
    } catch (err) {
      setToast(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function openProject(id) {
    const detail = await api.project(id)
    setSelectedProject(detail)
  }

  async function raiseDemoBug() {
    if (!selectedProject) return
    await api.bugs({
      project_id: selectedProject.id,
      title: 'Checkout button misaligned on mobile',
      steps: 'Open mobile viewport → cart → pay CTA overlaps footer',
      severity: 'high',
      assigned_to: 'Cursor',
    })
    await openProject(selectedProject.id)
    await refresh()
    setToast('Tester raised bug to Cursor')
  }

  async function askChairman() {
    const q = window.prompt('Question for Chairman Baloda?')
    if (!q) return
    await api.createEscalation({
      question: q,
      asked_by: 'Gemini (Designer)',
      context: 'No agent could confirm feature rule',
    })
    await refresh()
    setTab('hq')
  }

  return (
    <div className="app-shell">
      <aside className="side">
        <div className="brand">
          <h1>Compucon</h1>
          <p>Chairman · Baloda</p>
          <p>Voice · Piki</p>
        </div>
        <nav className="nav">
          {NAV.map(([id, label]) => (
            <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
              {label}
            </button>
          ))}
        </nav>
        <div className="panel" style={{ marginTop: 'auto' }}>
          <h3>Live pulse</h3>
          <div className="stat">{company?.stats?.projects ?? 0}</div>
          <div className="muted">projects · {company?.stats?.plans_pending ?? 0} plans waiting</div>
        </div>
      </aside>

      <main className="main">
        <div className="topbar">
          <div>
            <h2>
              {tab === 'hq' && 'Chairman HQ'}
              {tab === 'floor' && 'Company Floor'}
              {tab === 'intake' && 'BDE Requirement Intake'}
              {tab === 'meetings' && 'Meeting Room'}
              {tab === 'projects' && 'Project Floor'}
              {tab === 'quota' && 'CTO Quota Monitor'}
            </h2>
            <div className="meta">Real IT company workflow · agents collaborate · Baloda approves</div>
          </div>
          <div className="row">
            <button onClick={() => refresh()}>Refresh</button>
            {toast && <span className="muted">{toast}</span>}
          </div>
        </div>

        {tab === 'hq' && (
          <div className="grid-2">
            <section className="panel">
              <h3>Plans awaiting Baloda</h3>
              {pendingPlans.length === 0 && <p className="muted">No pending plans. BDE can add a requirement.</p>}
              {pendingPlans.map((p) => (
                <div className="list-item" key={p.id}>
                  <strong>{p.title}</strong>
                  <p className="muted">{p.summary}</p>
                  <pre style={{ whiteSpace: 'pre-wrap', color: 'var(--muted)', fontFamily: 'var(--sans)', fontSize: 13 }}>
                    {p.modules}
                  </pre>
                  <div className="row">
                    <button className="primary" disabled={busy} onClick={() => decide(p.id, 'approve')}>
                      Approve
                    </button>
                    <button className="danger" disabled={busy} onClick={() => decide(p.id, 'reject')}>
                      Reject
                    </button>
                    <button disabled={busy} onClick={() => decide(p.id, 'meeting')}>
                      Call Meeting
                    </button>
                  </div>
                </div>
              ))}
            </section>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <section className="panel">
                <h3>Escalations</h3>
                {openEsc.length === 0 && <p className="muted">No open escalations.</p>}
                {openEsc.map((e) => (
                  <div className="list-item" key={e.id}>
                    <strong>{e.asked_by}</strong>
                    <p>{e.question}</p>
                    <button
                      className="primary"
                      onClick={async () => {
                        const answer = window.prompt('Your answer as Chairman Baloda?')
                        if (!answer) return
                        await api.answerEscalation(e.id, answer)
                        await refresh()
                      }}
                    >
                      Answer
                    </button>
                  </div>
                ))}
                <button className="ghost" onClick={askChairman}>
                  Simulate designer escalate
                </button>
              </section>
              <section className="panel">
                <h3>Activity</h3>
                {activity.slice(0, 8).map((a) => (
                  <div className="list-item" key={a.id}>
                    <strong>{a.actor}</strong>
                    <span className="muted">{a.message}</span>
                  </div>
                ))}
              </section>
            </div>
          </div>
        )}

        {tab === 'floor' && (
          <section className="panel">
            <h3>Agents · Cursor · Claude · Gemini · ChatGPT · Groq · DeepSeek</h3>
            {agents.map((a) => (
              <div className="agent-card" key={a.id}>
                <div className="avatar" style={{ background: a.avatar_color }}>
                  {a.name.slice(0, 1)}
                </div>
                <div>
                  <div className="row" style={{ justifyContent: 'space-between' }}>
                    <div>
                      <strong>
                        {a.name} {a.is_human ? '· Human Chairman' : ''}
                      </strong>
                      <div className="muted">
                        {a.role.replaceAll('_', ' ')} · {a.provider}
                      </div>
                    </div>
                    <span className={statusPill(a.status)}>
                      <span className="dot" />
                      {a.status}
                    </span>
                  </div>
                  <div className="muted">{a.specialty}</div>
                  {!a.is_human && (
                    <>
                      <div className="bar">
                        <span style={{ width: `${Math.min(100, a.quota_pct)}%` }} />
                      </div>
                      <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                        Quota {a.used_today}/{a.daily_quota} · remaining {a.remaining}
                      </div>
                    </>
                  )}
                </div>
              </div>
            ))}
          </section>
        )}

        {tab === 'intake' && (
          <section className="panel" style={{ maxWidth: 720 }}>
            <h3>DeepSeek (BDE) · New requirement</h3>
            <form className="form-stack" onSubmit={submitRequirement}>
              <input
                required
                placeholder="Project / requirement title"
                value={reqForm.title}
                onChange={(e) => setReqForm({ ...reqForm, title: e.target.value })}
              />
              <textarea
                required
                rows={4}
                placeholder="Client need / problem statement"
                value={reqForm.description}
                onChange={(e) => setReqForm({ ...reqForm, description: e.target.value })}
              />
              <textarea
                rows={3}
                placeholder="Success criteria"
                value={reqForm.success_criteria}
                onChange={(e) => setReqForm({ ...reqForm, success_criteria: e.target.value })}
              />
              <select
                value={reqForm.priority}
                onChange={(e) => setReqForm({ ...reqForm, priority: e.target.value })}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <button className="primary" disabled={busy}>
                Submit to CTO planning
              </button>
            </form>
          </section>
        )}

        {tab === 'meetings' && (
          <section className="panel">
            <h3>Meetings</h3>
            {meetings.length === 0 && <p className="muted">No meetings yet.</p>}
            {meetings.map((m) => (
              <div className="list-item" key={m.id}>
                <strong>
                  {m.title} · {m.meeting_type}
                </strong>
                <div className="muted">Participants: {m.participants}</div>
                <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--sans)', fontSize: 13 }}>{m.transcript}</pre>
                <div className="muted">Decision: {m.decisions}</div>
              </div>
            ))}
          </section>
        )}

        {tab === 'projects' && (
          <div className="grid-2">
            <section className="panel">
              <h3>Projects</h3>
              {projects.length === 0 && <p className="muted">Approve a plan to create a project workspace.</p>}
              {projects.map((p) => (
                <div className="list-item" key={p.id}>
                  <strong>{p.name}</strong>
                  <div className="muted">
                    Phase {p.phase} · {p.remote_workspace}
                  </div>
                  <div className="row">
                    <button onClick={() => openProject(p.id)}>Open</button>
                    <button
                      onClick={async () => {
                        try {
                          await api.submitFinal(p.id)
                          setToast('Submitted to Chairman Baloda for final review')
                          await refresh()
                        } catch (e) {
                          setToast(e.message)
                        }
                      }}
                    >
                      CTO final submit
                    </button>
                  </div>
                </div>
              ))}
              <h3 style={{ marginTop: '1rem' }}>All tasks</h3>
              {tasks.slice(0, 10).map((t) => (
                <div className="list-item" key={t.id}>
                  <strong>
                    {t.title} → {t.assignee || 'Unassigned'}
                  </strong>
                  <div className="muted">
                    {t.task_type} · {t.status} · by {t.assigner_name}
                  </div>
                </div>
              ))}
            </section>
            <section className="panel">
              <h3>Workspace detail</h3>
              {!selectedProject && <p className="muted">Select a project.</p>}
              {selectedProject && (
                <>
                  <div className="phase">
                    {['design', 'build', 'qa', 'chairman_final_review'].map((ph) => (
                      <span key={ph} className={selectedProject.phase === ph ? 'on' : ''}>
                        {ph}
                      </span>
                    ))}
                  </div>
                  <strong>{selectedProject.name}</strong>
                  <p className="muted">{selectedProject.remote_workspace}</p>
                  <h3>Tasks</h3>
                  {selectedProject.tasks.map((t) => (
                    <div className="list-item" key={t.id}>
                      <strong>
                        {t.title} · {t.assignee}
                      </strong>
                      <div className="muted">{t.status}</div>
                    </div>
                  ))}
                  <h3>Bugs</h3>
                  {selectedProject.bugs.length === 0 && <p className="muted">No bugs.</p>}
                  {selectedProject.bugs.map((b) => (
                    <div className="list-item" key={b.id}>
                      <strong>
                        {b.title} → {b.assigned_to}
                      </strong>
                      <div className="muted">
                        {b.severity} · {b.status}
                      </div>
                    </div>
                  ))}
                  <button onClick={raiseDemoBug}>Tester raise bug → Developer</button>
                </>
              )}
            </section>
          </div>
        )}

        {tab === 'quota' && (
          <div className="grid-2">
            <section className="panel">
              <h3>Claude (CTO) monitors agent limits</h3>
              <p className="muted">
                If an agent hits daily quota, new commands are queued until reset. CTO can force-reset to release the
                queue.
              </p>
              {(quota?.agents || []).map((a) => (
                <div className="agent-card" key={a.id}>
                  <div className="avatar" style={{ background: a.avatar_color }}>
                    {a.name.slice(0, 1)}
                  </div>
                  <div style={{ width: '100%' }}>
                    <div className="row" style={{ justifyContent: 'space-between' }}>
                      <strong>
                        {a.name} · {a.role.replaceAll('_', ' ')}
                      </strong>
                      <span className={statusPill(a.status)}>
                        <span className="dot" />
                        {a.status}
                      </span>
                    </div>
                    <div className="bar">
                      <span style={{ width: `${Math.min(100, a.quota_pct)}%` }} />
                    </div>
                    <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                      {a.used_today}/{a.daily_quota} used · resets {a.quota_reset_at || '—'}
                    </div>
                    <div className="row" style={{ marginTop: 8 }}>
                      <button
                        onClick={async () => {
                          await api.adjustQuota(a.id, { used_today: a.daily_quota })
                          await refresh()
                          setToast(`${a.name} marked quota exhausted (demo)`)
                        }}
                      >
                        Exhaust (demo)
                      </button>
                      <button
                        className="primary"
                        onClick={async () => {
                          await api.adjustQuota(a.id, { force_reset: true })
                          await refresh()
                          setToast(`${a.name} quota reset · queued commands released`)
                        }}
                      >
                        Reset & release queue
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </section>
            <section className="panel">
              <h3>Queued commands</h3>
              {(quota?.queued_commands || []).length === 0 && (
                <p className="muted">No commands waiting on quota.</p>
              )}
              {(quota?.queued_commands || []).map((q) => (
                <div className="list-item" key={q.id}>
                  <strong>Agent #{q.agent_id}</strong>
                  <div>{q.command}</div>
                  <div className="muted">
                    {q.source} · {q.status}
                  </div>
                </div>
              ))}
            </section>
          </div>
        )}
      </main>

      <PikiDock onDone={refresh} />
    </div>
  )
}
