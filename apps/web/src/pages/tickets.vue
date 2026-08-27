<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    layoutWrapperClasses: 'layout-content-width-fluid',
    channel: 'crm',
  },
})

type Contact = {
  id: string
  wa_id: string | null
  email: string | null
  name: string | null
  custom_attributes: Record<string, any>
  opted_out: boolean
  labels: Label[]
  company_id: string | null
  consent_given_at: string | null
  created_at: string
}
type Company = { id: string, name: string }
type Label = { id: string, scope: 'conversation' | 'contact', name: string, color: string }
type ConversationMessage = {
  id: string
  direction: 'inbound' | 'outbound'
  is_private: boolean
  message_type: string
  body: string | null
  payload: Record<string, any> | null
  sent_by_user_id: string | null
  created_at: string
}
type Ticket = {
  id: string
  contact: Contact
  channel: string
  status: string
  unread: boolean
  assigned_user_id: string | null
  last_message_preview: string | null
  last_message_at: string | null
  is_ticket: boolean
  ticket_number: string | null
  created_at: string
  first_response_due_at: string | null
  sla_breached: boolean
  resolution_due_at: string | null
  resolution_breached: boolean
  priority: 'low' | 'medium' | 'high' | 'urgent'
  category: 'question' | 'incident' | 'problem' | 'task'
  group_id: string | null
  labels: Label[]
  ticket_custom_fields: Record<string, any>
  subject: string | null
  cc_emails: string[]
}
type TicketDetail = Ticket & { messages: ConversationMessage[] }
type TicketCounts = { unassigned: number, assigned_to_me: number, all: number, open: number, pending: number, resolved: number }
type AssignableUser = { id: string, full_name: string, email: string }
type TicketGroup = { id: string, name: string, member_user_ids: string[] }
type CannedResponse = { id: string, shortcut: string, body: string }
type CustomField = { id: string, name: string, field_type: 'text' | 'number' | 'date' | 'dropdown', options: string[], required: boolean }

const STATUSES = ['open', 'pending', 'resolved'] as const
const STATUS_ITEMS: string[] = ['open', 'pending', 'resolved']
const PRIORITY_COLORS: Record<string, string | undefined> = { low: undefined, medium: 'info', high: 'warning', urgent: 'error' }

// --- Live SLA/resolution countdown -- ticks every 30s so "Due in 12m" stays accurate without a
// full reload, matching Freshdesk/Salesforce's own urgency-forward due-date display. -------------
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | undefined
onMounted(() => { clock = setInterval(() => { now.value = Date.now() }, 30_000) })
onUnmounted(() => clearInterval(clock))

function dueLabel(dueAt: string | null, breached: boolean) {
  if (!dueAt)
    return null
  const diffMs = new Date(dueAt).getTime() - now.value
  const minutes = Math.round(Math.abs(diffMs) / 60_000)
  const hours = Math.floor(minutes / 60)
  const rem = minutes % 60
  const span = hours ? `${hours}h ${rem}m` : `${minutes}m`
  return breached || diffMs < 0 ? `Overdue by ${span}` : `Due in ${span}`
}

type FilterKey = 'all' | 'unassigned' | 'mine' | 'open' | 'pending' | 'resolved'
const activeFilter = ref<FilterKey>('open')
const search = ref('')
const tickets = ref<Ticket[]>([])
const loading = ref(false)
const loadError = ref('')
const counts = ref<TicketCounts>({ unassigned: 0, assigned_to_me: 0, all: 0, open: 0, pending: 0, resolved: 0 })
const assignableUsers = ref<AssignableUser[]>([])
const ticketGroups = ref<TicketGroup[]>([])
const cannedResponses = ref<CannedResponse[]>([])
const availableLabels = ref<Label[]>([])
const customFields = ref<CustomField[]>([])

function contactLabel(c: Contact) {
  return c.name || c.wa_id || c.email || 'Unknown'
}

function ticketParams(): Record<string, string | boolean | number> {
  const params: Record<string, string | boolean | number> = { is_ticket: true, limit: 100 }
  if (activeFilter.value === 'unassigned')
    params.assignment = 'unassigned'
  else if (activeFilter.value === 'mine')
    params.assignment = 'mine'
  else if ((STATUSES as readonly string[]).includes(activeFilter.value))
    params.status = activeFilter.value
  if (search.value.trim())
    params.search = search.value.trim()
  return params
}

async function loadTickets() {
  loading.value = true
  loadError.value = ''
  try {
    tickets.value = await $api<Ticket[]>('/v1/waba/conversations', { params: ticketParams() })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load tickets.')
  }
  finally {
    loading.value = false
  }
}

async function loadCounts() {
  try {
    counts.value = await $api<TicketCounts>('/v1/waba/conversations/ticket-counts')
  }
  catch {
    // Non-critical -- the status rail just shows stale/zero counts this session.
  }
}

async function loadStatic() {
  try {
    const [users, groups, canned, labels, fields] = await Promise.all([
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<TicketGroup[]>('/v1/waba/ticket-groups'),
      $api<CannedResponse[]>('/v1/waba/canned-responses'),
      $api<Label[]>('/v1/waba/labels'),
      $api<CustomField[]>('/v1/crm/custom-fields?applies_to=ticket'),
    ])
    assignableUsers.value = users
    ticketGroups.value = groups
    cannedResponses.value = canned
    availableLabels.value = labels.filter(l => l.scope === 'conversation')
    customFields.value = fields
  }
  catch {
    // Non-critical -- the Agent/Group selects, canned-response picker, labels, and custom
    // fields just show fewer options this session.
  }
}

let searchDebounce: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(searchDebounce)
  searchDebounce = setTimeout(loadTickets, 350)
})
watch(activeFilter, loadTickets)

// --- Selected ticket + thread ------------------------------------------------------------------

const selected = ref<TicketDetail | null>(null)
const threadLoading = ref(false)
const threadError = ref('')
const customerCompany = ref<Company | null>(null)

const view = ref<'list' | 'detail'>('list')

async function selectTicket(id: string) {
  view.value = 'detail'
  threadLoading.value = true
  threadError.value = ''
  customerCompany.value = null
  try {
    selected.value = await $api<TicketDetail>(`/v1/waba/conversations/${id}`)
    $api(`/v1/waba/conversations/${id}/read`, { method: 'POST' })
      .then(() => {
        const row = tickets.value.find(t => t.id === id)
        if (row)
          row.unread = false
      })
      .catch(() => {})
    if (selected.value.contact.company_id) {
      $api<{ company: Company }>(`/v1/crm/companies/${selected.value.contact.company_id}`)
        .then(r => { customerCompany.value = r.company })
        .catch(() => {})
    }
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not load this ticket.')
  }
  finally {
    threadLoading.value = false
  }
}

function backToList() {
  view.value = 'list'
  selected.value = null
}

// --- Reply / private note --------------------------------------------------------------------

const replyBody = ref('')
const isPrivateNote = ref(false)
const replySending = ref(false)
const replyError = ref('')
const cannedMenuOpen = ref(false)
const cannedMatches = computed(() => {
  if (!replyBody.value.startsWith('/'))
    return []
  const query = replyBody.value.slice(1).toLowerCase()
  return cannedResponses.value.filter(c => c.shortcut.toLowerCase().startsWith(query))
})
watch(replyBody, (value) => {
  cannedMenuOpen.value = value.startsWith('/')
})
function pickCanned(canned: CannedResponse) {
  replyBody.value = canned.body
  cannedMenuOpen.value = false
}

async function sendReply() {
  if (!selected.value || !replyBody.value.trim())
    return
  replySending.value = true
  replyError.value = ''
  try {
    if (selected.value.channel === 'email') {
      await $api('/v1/crm/email/send', {
        method: 'POST',
        body: {
          contact_id: selected.value.contact.id,
          subject: selected.value.subject ? `Re: ${selected.value.subject}` : `Re: ${selected.value.ticket_number}`,
          body: replyBody.value,
          cc: selected.value.cc_emails,
        },
      })
      await selectTicket(selected.value.id)
    }
    else {
      const message = await $api<ConversationMessage>(`/v1/waba/conversations/${selected.value.id}/messages`, {
        method: 'POST',
        body: { body: replyBody.value, is_private: isPrivateNote.value },
      })
      selected.value.messages.push(message)
    }
    replyBody.value = ''
    isPrivateNote.value = false
    await loadTickets()
    await loadCounts()
  }
  catch (error: any) {
    replyError.value = extractErrorMessage(error, 'Could not send this reply.')
  }
  finally {
    replySending.value = false
  }
}

// --- Ticket properties -------------------------------------------------------------------------

async function updateStatus(status: string) {
  if (!selected.value)
    return
  try {
    const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}`, { method: 'PUT', body: { status } })
    selected.value.status = updated.status
    await loadTickets()
    await loadCounts()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update status.')
  }
}

async function updateAssignee(assignedUserId: string | null) {
  if (!selected.value)
    return
  try {
    const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}`, { method: 'PUT', body: { assigned_user_id: assignedUserId } })
    selected.value.assigned_user_id = updated.assigned_user_id
    await loadTickets()
    await loadCounts()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update the assignee.')
  }
}

async function updatePriority(priority: string) {
  if (!selected.value)
    return
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/priority`, { method: 'PATCH', body: { priority } })
  selected.value.priority = updated.priority
  const row = tickets.value.find(t => t.id === selected.value?.id)
  if (row)
    row.priority = updated.priority
}

async function updateCategory(category: string) {
  if (!selected.value)
    return
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/category`, { method: 'PATCH', body: { category } })
  selected.value.category = updated.category
}

async function updateGroup(groupId: string | null) {
  if (!selected.value)
    return
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/group`, { method: 'PATCH', body: { group_id: groupId } })
  selected.value.group_id = updated.group_id
}

async function updateTicketCustomField(name: string, value: any) {
  if (!selected.value)
    return
  const fields = { ...selected.value.ticket_custom_fields, [name]: value }
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/custom-fields`, { method: 'PATCH', body: { ticket_custom_fields: fields } })
  selected.value.ticket_custom_fields = updated.ticket_custom_fields
}

// --- Subject (inline-editable, defaults to the last message preview until set) -----------------

const subjectDraft = ref('')
watch(selected, (t) => { subjectDraft.value = t?.subject || '' })

async function saveSubject() {
  if (!selected.value)
    return
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/subject`, { method: 'PATCH', body: { subject: subjectDraft.value.trim() || null } })
  selected.value.subject = updated.subject
  const row = tickets.value.find(t => t.id === selected.value?.id)
  if (row)
    row.subject = updated.subject
}

// --- Labels ------------------------------------------------------------------------------------

const togglingLabelId = ref<string | null>(null)

async function toggleLabel(label: Label) {
  if (!selected.value || togglingLabelId.value)
    return
  togglingLabelId.value = label.id
  try {
    const attached = selected.value.labels.some(l => l.id === label.id)
    const method = attached ? 'DELETE' : 'POST'
    const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/labels/${label.id}`, { method })
    selected.value.labels = updated.labels
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update this label.')
  }
  finally {
    togglingLabelId.value = null
  }
}

// --- CC (email tickets only) --------------------------------------------------------------------

const ccDraft = ref('')
watch(selected, (t) => { ccDraft.value = t?.cc_emails.join(', ') || '' })

async function saveCc() {
  if (!selected.value)
    return
  const cc = ccDraft.value.split(',').map(e => e.trim()).filter(Boolean)
  const updated = await $api<Ticket>(`/v1/waba/conversations/${selected.value.id}/cc`, { method: 'PATCH', body: { cc_emails: cc } })
  selected.value.cc_emails = updated.cc_emails
}

function ownerName(id: string | null) {
  return assignableUsers.value.find(u => u.id === id)?.full_name || null
}

function formatTime(iso: string | null) {
  if (!iso)
    return ''
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

onMounted(() => {
  loadTickets()
  loadCounts()
  loadStatic()
})
</script>

<template>
  <h1 class="text-h4 mb-4">
    Tickets
  </h1>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <div v-if="view === 'list'" class="d-flex ga-4" style="min-height: 72vh; overflow-x: auto;">
    <VCard style="min-inline-size: 180px; max-inline-size: 180px;">
      <VList density="compact" nav>
        <VListSubheader>Views</VListSubheader>
        <VListItem :active="activeFilter === 'all'" @click="activeFilter = 'all'">
          <VListItemTitle>All</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.all }}
            </VChip>
          </template>
        </VListItem>
        <VListItem :active="activeFilter === 'unassigned'" @click="activeFilter = 'unassigned'">
          <VListItemTitle>Unassigned</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.unassigned }}
            </VChip>
          </template>
        </VListItem>
        <VListItem :active="activeFilter === 'mine'" @click="activeFilter = 'mine'">
          <VListItemTitle>My open</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.assigned_to_me }}
            </VChip>
          </template>
        </VListItem>
        <VDivider class="my-2" />
        <VListSubheader>Status</VListSubheader>
        <VListItem :active="activeFilter === 'open'" @click="activeFilter = 'open'">
          <VListItemTitle>Open</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.open }}
            </VChip>
          </template>
        </VListItem>
        <VListItem :active="activeFilter === 'pending'" @click="activeFilter = 'pending'">
          <VListItemTitle>Pending</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.pending }}
            </VChip>
          </template>
        </VListItem>
        <VListItem :active="activeFilter === 'resolved'" @click="activeFilter = 'resolved'">
          <VListItemTitle>Resolved</VListItemTitle>
          <template #append>
            <VChip size="x-small">
              {{ counts.resolved }}
            </VChip>
          </template>
        </VListItem>
      </VList>
    </VCard>

    <VCard class="flex-grow-1 d-flex flex-column">
      <VCardText class="pb-2 flex-grow-0">
        <VTextField v-model="search" placeholder="Search tickets" density="compact" prepend-inner-icon="tabler-search" hide-details clearable style="max-inline-size: 320px;" />
      </VCardText>
      <VDivider />
      <div style="overflow-y: auto;">
        <VTable>
          <thead>
            <tr>
              <th style="inline-size: 28px;" />
              <th>Customer / Subject</th>
              <th>Priority</th>
              <th>Category</th>
              <th>Status</th>
              <th class="text-end">
                Updated
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="t in tickets" :key="t.id"
              style="cursor: pointer;"
              @click="selectTicket(t.id)"
            >
              <td style="inline-size: 28px;">
                <VIcon :icon="t.channel === 'email' ? 'tabler-mail' : 'tabler-brand-whatsapp'" size="16" :color="t.channel === 'email' ? undefined : 'success'" />
              </td>
              <td>
                <div class="text-body-2 text-truncate" :class="t.unread ? 'font-weight-bold' : 'font-weight-medium'" style="max-inline-size: 260px;">
                  {{ contactLabel(t.contact) }}
                </div>
                <div class="text-caption text-medium-emphasis text-truncate" style="max-inline-size: 260px;" :class="t.unread ? 'text-high-emphasis font-weight-medium' : ''">
                  {{ t.subject || t.last_message_preview || '(no messages yet)' }}
                </div>
                <VChip size="x-small" variant="text" class="pl-0">
                  {{ t.ticket_number }}
                </VChip>
              </td>
              <td>
                <VChip size="x-small" :color="PRIORITY_COLORS[t.priority]" class="text-capitalize">
                  {{ t.priority }}
                </VChip>
                <div v-if="dueLabel(t.resolution_due_at, t.resolution_breached)" class="text-caption mt-1" :class="t.resolution_breached ? 'text-error' : 'text-medium-emphasis'">
                  {{ dueLabel(t.resolution_due_at, t.resolution_breached) }}
                </div>
              </td>
              <td class="text-capitalize">
                {{ t.category }}
              </td>
              <td class="text-capitalize">
                {{ t.status }}
              </td>
              <td class="text-end text-caption text-medium-emphasis">
                {{ formatTime(t.last_message_at || t.created_at) }}
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!loading && !tickets.length" class="text-medium-emphasis text-center pa-6 mb-0">
          No tickets here.
        </p>
      </div>
    </VCard>
  </div>

  <div v-else-if="selected" class="d-flex flex-column ga-3" style="min-height: 72vh;">
    <VBtn variant="text" prepend-icon="tabler-arrow-left" style="align-self: start;" @click="backToList">
      Back to tickets
    </VBtn>
    <div class="d-flex ga-4" style="overflow-x: auto;">
    <VCard class="flex-grow-1 d-flex flex-column overflow-hidden" style="min-inline-size: 380px;">
      <VCardText class="flex-grow-0 pb-2">
        <div class="d-flex align-center flex-wrap ga-2 mb-2">
          <strong>{{ contactLabel(selected.contact) }}</strong>
          <VChip size="small" color="info" prepend-icon="tabler-ticket">
            {{ selected.ticket_number }}
          </VChip>
          <VSpacer />
          <VSelect
            :model-value="selected.status" :items="STATUS_ITEMS" density="compact" variant="outlined" hide-details
            style="max-inline-size: 140px;" @update:model-value="(v: string) => updateStatus(v)"
          />
        </div>
        <VTextField
          v-model="subjectDraft" placeholder="Add a subject..." density="compact" variant="plain" hide-details
          class="mb-2 font-weight-medium" style="font-size: 1.05rem;" @blur="saveSubject" @keyup.enter="saveSubject"
        />
        <div class="d-flex align-center flex-wrap ga-2">
          <VChip v-if="selected.sla_breached" size="small" color="error" prepend-icon="tabler-alert-triangle">
            First response overdue
          </VChip>
          <VChip
            v-else-if="dueLabel(selected.first_response_due_at, false)" size="small" variant="tonal"
            prepend-icon="tabler-clock"
          >
            First response: {{ dueLabel(selected.first_response_due_at, false) }}
          </VChip>
          <VChip v-if="selected.resolution_breached" size="small" color="error" prepend-icon="tabler-alert-triangle">
            Resolution overdue
          </VChip>
          <VChip
            v-else-if="dueLabel(selected.resolution_due_at, false)" size="small" variant="tonal"
            prepend-icon="tabler-clock"
          >
            Resolution: {{ dueLabel(selected.resolution_due_at, false) }}
          </VChip>
          <VChip
            v-for="label in selected.labels" :key="label.id" size="small" :color="label.color" variant="tonal"
            :closable="!togglingLabelId" @click:close="toggleLabel(label)"
          >
            {{ label.name }}
          </VChip>
          <VMenu v-if="availableLabels.length">
            <template #activator="{ props: menuProps }">
              <VBtn size="x-small" variant="text" icon="tabler-tag-plus" :loading="!!togglingLabelId" v-bind="menuProps" />
            </template>
            <VList density="compact">
              <VListItem v-for="label in availableLabels" :key="label.id" :disabled="!!togglingLabelId" @click="toggleLabel(label)">
                <template #prepend>
                  <VIcon icon="tabler-circle-filled" size="10" :color="label.color" />
                </template>
                <VListItemTitle>{{ label.name }}</VListItemTitle>
                <template #append>
                  <VIcon v-if="selected.labels.some(l => l.id === label.id)" icon="tabler-check" size="14" />
                </template>
              </VListItem>
            </VList>
          </VMenu>
        </div>
      </VCardText>
      <VDivider />

      <VAlert v-if="threadError" type="error" variant="tonal" density="compact" class="ma-3">
        {{ threadError }}
      </VAlert>

      <div class="flex-grow-1 overflow-y-auto pa-4">
        <div v-for="m in selected.messages" :key="m.id" class="mb-4">
          <div class="d-flex align-center ga-2 mb-1">
            <VAvatar size="24" :color="m.direction === 'outbound' ? 'primary' : undefined" variant="tonal">
              <span class="text-caption">{{ (m.direction === 'outbound' ? (ownerName(m.sent_by_user_id) || 'A') : contactLabel(selected.contact)).slice(0, 1).toUpperCase() }}</span>
            </VAvatar>
            <span class="text-body-2 font-weight-medium">{{ m.direction === 'outbound' ? (ownerName(m.sent_by_user_id) || 'You') : contactLabel(selected.contact) }}</span>
            <VChip v-if="m.is_private" size="x-small" color="warning" variant="tonal">
              Private note
            </VChip>
            <span class="text-caption text-medium-emphasis">{{ formatTime(m.created_at) }}</span>
          </div>
          <div
            class="pa-3 rounded"
            :style="{ backgroundColor: m.is_private ? 'rgb(var(--v-theme-warning), 0.1)' : 'rgb(var(--v-theme-on-surface), 0.04)', marginInlineStart: '32px' }"
          >
            <p v-if="selected.channel === 'email' && m.payload?.subject" class="text-caption text-medium-emphasis mb-1">
              {{ m.payload.subject }}
            </p>
            <p class="mb-0" style="white-space: pre-wrap;">
              {{ m.body }}
            </p>
          </div>
        </div>
        <p v-if="!threadLoading && !selected.messages.length" class="text-medium-emphasis text-center pa-6">
          No messages yet.
        </p>
      </div>
      <VDivider />
      <VCardText class="flex-grow-0">
        <VAlert v-if="replyError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ replyError }}
        </VAlert>
        <div v-if="selected.channel !== 'email'" class="d-flex ga-2 mb-2">
          <VBtn
            size="small" :variant="!isPrivateNote ? 'flat' : 'tonal'" :color="!isPrivateNote ? 'primary' : undefined"
            @click="isPrivateNote = false"
          >
            Reply
          </VBtn>
          <VBtn
            size="small" :variant="isPrivateNote ? 'flat' : 'tonal'" :color="isPrivateNote ? 'warning' : undefined"
            @click="isPrivateNote = true"
          >
            Private note
          </VBtn>
        </div>
        <VTextField
          v-if="selected.channel === 'email'" v-model="ccDraft" label="Cc" placeholder="comma-separated emails" density="compact"
          class="mb-2" @blur="saveCc"
        />
        <div class="position-relative">
          <VMenu v-model="cannedMenuOpen" :close-on-content-click="true" activator="parent" location="top">
            <VList v-if="cannedMatches.length" density="compact">
              <VListItem v-for="canned in cannedMatches" :key="canned.id" @click="pickCanned(canned)">
                <VListItemTitle>/{{ canned.shortcut }}</VListItemTitle>
                <VListItemSubtitle>{{ canned.body }}</VListItemSubtitle>
              </VListItem>
            </VList>
          </VMenu>
          <VTextarea
            v-model="replyBody" rows="2" auto-grow
            :placeholder="selected.channel === 'email' ? 'Write a reply...' : (isPrivateNote ? 'Leave a note for your team...' : 'Type a reply, or / for a canned response')"
          />
        </div>
        <div class="d-flex justify-end ga-3 mt-2">
          <VBtn :loading="replySending" :disabled="!replyBody.trim()" @click="sendReply">
            {{ isPrivateNote ? 'Add note' : 'Send' }}
          </VBtn>
        </div>
      </VCardText>
    </VCard>

    <VCard style="min-inline-size: 320px; max-inline-size: 320px;">
      <VCardText>
        <VAvatar color="primary" variant="tonal" size="48" class="mb-2">
          <span class="text-h6">{{ contactLabel(selected.contact).slice(0, 1).toUpperCase() }}</span>
        </VAvatar>
        <p class="text-subtitle-1 mb-0">
          {{ contactLabel(selected.contact) }}
        </p>
        <p class="text-caption text-medium-emphasis mb-1">
          {{ selected.contact.wa_id || '—' }}
        </p>
        <p v-if="selected.contact.email" class="text-caption text-medium-emphasis mb-1">
          {{ selected.contact.email }}
        </p>
        <RouterLink :to="`/waba-customers/${selected.contact.id}`" class="text-caption d-inline-block mb-2">
          View full customer profile →
        </RouterLink>

        <VChip v-if="selected.contact.opted_out" size="small" color="error" variant="tonal" class="mb-2 d-block" style="width: fit-content;">
          Opted out
        </VChip>

        <div v-if="customerCompany" class="mb-2">
          <p class="text-caption text-medium-emphasis mb-0">
            Company
          </p>
          <RouterLink :to="`/crm-companies/${customerCompany.id}`" class="text-body-2">
            {{ customerCompany.name }}
          </RouterLink>
        </div>

        <div v-if="selected.contact.labels.length" class="mb-3">
          <p class="text-caption text-medium-emphasis mb-1">
            Customer labels
          </p>
          <div class="d-flex flex-wrap ga-1">
            <VChip v-for="label in selected.contact.labels" :key="label.id" size="x-small" :color="label.color" variant="tonal">
              {{ label.name }}
            </VChip>
          </div>
        </div>

        <div v-if="Object.keys(selected.contact.custom_attributes).length" class="mb-3">
          <p class="text-caption text-medium-emphasis mb-1">
            Custom fields
          </p>
          <div v-for="(value, key) in selected.contact.custom_attributes" :key="key" class="text-body-2">
            <span class="text-medium-emphasis">{{ key }}:</span> {{ value }}
          </div>
        </div>

        <p class="text-caption text-medium-emphasis mb-4">
          Customer since {{ formatTime(selected.contact.created_at) }}
        </p>

        <VDivider class="mb-3" />
        <h3 class="text-subtitle-2 mb-2">
          Ticket properties
        </h3>
        <VSelect
          :model-value="selected.priority" :items="['low', 'medium', 'high', 'urgent']" label="Priority"
          density="compact" class="mb-3 text-capitalize" @update:model-value="updatePriority"
        />
        <VSelect
          :model-value="selected.category" :items="['question', 'incident', 'problem', 'task']" label="Category"
          density="compact" class="mb-3 text-capitalize" @update:model-value="updateCategory"
        />
        <VSelect
          :model-value="selected.group_id" label="Group" density="compact" class="mb-3" clearable
          :items="[{ title: 'No group', value: null }, ...ticketGroups.map(g => ({ title: g.name, value: g.id }))]"
          @update:model-value="updateGroup"
        />
        <VSelect
          :model-value="selected.assigned_user_id" label="Agent" density="compact" clearable
          :items="assignableUsers.map(u => ({ title: u.full_name, value: u.id }))"
          @update:model-value="updateAssignee"
        />
        <template v-if="customFields.length">
          <VDivider class="mb-3" />
          <VSelect
            v-for="field in customFields.filter(f => f.field_type === 'dropdown')" :key="field.id"
            :model-value="selected.ticket_custom_fields[field.name]" :label="field.name" :items="field.options"
            density="compact" class="mb-3" clearable
            @update:model-value="(v: string) => updateTicketCustomField(field.name, v)"
          />
          <VTextField
            v-for="field in customFields.filter(f => f.field_type !== 'dropdown')" :key="field.id"
            :model-value="selected.ticket_custom_fields[field.name]" :label="field.name"
            :type="field.field_type === 'number' ? 'number' : field.field_type === 'date' ? 'date' : 'text'"
            density="compact" class="mb-3"
            @update:model-value="(v: string) => updateTicketCustomField(field.name, v)"
          />
        </template>
      </VCardText>
    </VCard>
    </div>
  </div>
  <VCard v-else class="d-flex align-center justify-center" style="min-height: 72vh;">
    <p class="text-medium-emphasis">
      Loading ticket…
    </p>
  </VCard>
</template>
