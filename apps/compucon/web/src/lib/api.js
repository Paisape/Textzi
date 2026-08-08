const API = '/api'

async function req(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || data.message || 'Request failed')
  return data
}

export const api = {
  company: () => req('/company'),
  agents: () => req('/agents'),
  quotaBoard: () => req('/cto/quota-board'),
  requirements: () => req('/requirements'),
  createRequirement: (body) => req('/requirements', { method: 'POST', body: JSON.stringify(body) }),
  plans: () => req('/plans'),
  chairmanDecide: (id, body) => req(`/plans/${id}/chairman`, { method: 'POST', body: JSON.stringify(body) }),
  projects: () => req('/projects'),
  project: (id) => req(`/projects/${id}`),
  tasks: () => req('/tasks'),
  createTask: (body) => req('/tasks', { method: 'POST', body: JSON.stringify(body) }),
  bugs: (body) => req('/bugs', { method: 'POST', body: JSON.stringify(body) }),
  meetings: () => req('/meetings'),
  activity: () => req('/activity'),
  escalations: () => req('/escalations'),
  answerEscalation: (id, answer) =>
    req(`/escalations/${id}/answer`, { method: 'POST', body: JSON.stringify({ answer }) }),
  createEscalation: (body) => req('/escalations', { method: 'POST', body: JSON.stringify(body) }),
  submitFinal: (id) => req(`/projects/${id}/submit-final`, { method: 'POST' }),
  adjustQuota: (id, body) => req(`/agents/${id}/quota`, { method: 'PATCH', body: JSON.stringify(body) }),
  piki: (text, language = 'en') =>
    req('/piki/command', { method: 'POST', body: JSON.stringify({ text, language }) }),
}
