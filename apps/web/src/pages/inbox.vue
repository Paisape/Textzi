<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

definePage({
  meta: {
    layout: 'default',
    // The app's default "boxed" content width (Settings icon next to the logo) leaves too
    // little room for a real 3-pane inbox next to the vertical nav -- confirmed as the actual
    // cause of a cramped layout that only looked right after manually switching nav type to
    // horizontal (which just freed up space as a side effect). layoutWrapperClasses is the
    // layout system's own per-route override (@layouts/stores/config.ts's _layoutClasses
    // computed reads route.meta.layoutWrapperClasses directly), so it's swapped in and out
    // purely by Vue Router's route match -- no global state to mutate or restore, unlike an
    // onMounted/onBeforeUnmount pair toggling the shared config store (tried first; broke
    // because the store write on unmount landed after the next page had already rendered).
    // This only ADDS a class though -- it doesn't remove the store's own
    // "layout-content-width-boxed" contribution, which is what actually applies the max-width
    // (there's no separate "-fluid" CSS rule to begin with, boxed's absence IS fluid) -- see the
    // <style> block below for the targeted override that actually neutralizes it.
    layoutWrapperClasses: 'layout-content-width-fluid',
    channel: 'waba',
  },
})

type Label = {
  id: string
  scope: 'conversation' | 'contact'
  name: string
  color: string
}

type Contact = {
  id: string
  wa_id: string | null
  email: string | null
  name: string | null
  custom_attributes: Record<string, string>
  opted_out: boolean
  labels: Label[]
  created_at: string
}

type ConversationMessage = {
  id: string
  direction: 'inbound' | 'outbound'
  is_private: boolean
  message_type: string
  body: string | null
  media_url: string | null
  payload: Record<string, any> | null
  status: string | null
  error: string | null
  sent_by_user_id: string | null
  created_at: string
}

type Conversation = {
  id: string
  contact: Contact
  channel: string
  status: string
  assigned_user_id: string | null
  last_message_at: string | null
  last_read_at: string | null
  last_message_preview: string | null
  unread: boolean
  is_ticket: boolean
  ticket_number: string | null
  created_at: string
  labels: Label[]
  first_response_due_at: string | null
  sla_breached: boolean
}

type ConversationCounts = {
  unassigned: number
  assigned_to_me: number
  all: number
}

type ConversationDetail = Conversation & { messages: ConversationMessage[] }

type CannedResponse = {
  id: string
  shortcut: string
  body: string
}

type AssignableUser = {
  id: string
  full_name: string
  email: string
}

type WabaTemplate = {
  name: string
  status: string
  language: string
  category: string
  body: string | null
}

const LIST_LIMIT = 30

const route = useRoute()
// This is WhatsApp's own live-chat inbox only -- Tickets (tickets.vue) and Email (crm-email.vue)
// are both dedicated pages with their own list/detail UI, not this component wearing a prop flag.
// Pinned to channel=whatsapp so a connected Email account's conversations never leak in here.
const channelFilter = 'whatsapp' as const

const statusFilter = ref<'' | 'open' | 'pending' | 'resolved'>('open')
const assignmentFilter = ref<'' | 'unassigned' | 'mine'>('')
const searchQuery = ref('')
const conversations = ref<Conversation[]>([])
const conversationsLoading = ref(false)
const conversationsError = ref('')
const conversationsOffset = ref(0)
const conversationsHasMore = ref(false)
const counts = ref<ConversationCounts>({ unassigned: 0, assigned_to_me: 0, all: 0 })

const activeConversation = ref<ConversationDetail | null>(null)
const threadLoading = ref(false)
const threadError = ref('')

const conversationLabels = computed(() => labels.value.filter(l => l.scope === 'conversation'))
const contactLabels = computed(() => labels.value.filter(l => l.scope === 'contact'))
const labels = ref<Label[]>([])
const cannedResponses = ref<CannedResponse[]>([])
const assignableUsers = ref<AssignableUser[]>([])

// WhatsApp only allows a free-form reply within 24 hours of the customer's own last message --
// outside it Meta rejects the send server-side regardless of what this shows. This is purely a
// proactive heads-up so an agent finds out from the UI, not from a failed send: recomputed on a
// tick so "closes in 12m" counts down live while a conversation is open.
const nowTick = ref(Date.now())
let nowTickInterval: ReturnType<typeof setInterval> | undefined

const messageWindow = computed(() => {
  if (!activeConversation.value)
    return null
  const lastInbound = [...activeConversation.value.messages].reverse().find(m => m.direction === 'inbound')
  if (!lastInbound)
    return { state: 'none' as const, hoursLeft: 0 }
  const elapsedMs = nowTick.value - new Date(lastInbound.created_at).getTime()
  const hoursLeft = 24 - elapsedMs / (1000 * 60 * 60)
  if (hoursLeft <= 0)
    return { state: 'closed' as const, hoursLeft: 0 }
  if (hoursLeft <= 2)
    return { state: 'closing' as const, hoursLeft }
  return { state: 'open' as const, hoursLeft }
})

function formatWindowRemaining(hoursLeft: number): string {
  const totalMinutes = Math.round(hoursLeft * 60)
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

const messageBody = ref('')
const isPrivateNote = ref(false)
const sending = ref(false)
const sendError = ref('')
const cannedMenuOpen = ref(false)
const cannedMatches = computed(() => {
  if (!messageBody.value.startsWith('/'))
    return []
  const query = messageBody.value.slice(1).toLowerCase()
  return cannedResponses.value.filter(c => c.shortcut.toLowerCase().startsWith(query))
})
watch(messageBody, (value) => {
  cannedMenuOpen.value = value.startsWith('/')
})

let searchDebounce: ReturnType<typeof setTimeout> | undefined
watch(searchQuery, () => {
  if (searchDebounce)
    clearTimeout(searchDebounce)
  searchDebounce = setTimeout(loadConversations, 350)
})

function conversationParams(offset: number): Record<string, string | number | boolean> {
  const params: Record<string, string | number | boolean> = { limit: LIST_LIMIT, offset, channel: channelFilter }
  if (statusFilter.value)
    params.status = statusFilter.value
  if (assignmentFilter.value)
    params.assignment = assignmentFilter.value
  if (searchQuery.value.trim())
    params.search = searchQuery.value.trim()
  return params
}

async function loadConversations() {
  conversationsLoading.value = true
  conversationsError.value = ''
  conversationsOffset.value = 0
  try {
    const result = await $api<Conversation[]>('/v1/waba/conversations', { params: conversationParams(0) })
    conversations.value = result
    conversationsHasMore.value = result.length === LIST_LIMIT
  }
  catch (error: any) {
    conversationsError.value = extractErrorMessage(error, 'Could not load conversations.')
  }
  finally {
    conversationsLoading.value = false
  }
  loadCounts()
}

async function loadMoreConversations() {
  conversationsLoading.value = true
  try {
    const result = await $api<Conversation[]>('/v1/waba/conversations', { params: conversationParams(conversations.value.length) })
    conversations.value.push(...result)
    conversationsHasMore.value = result.length === LIST_LIMIT
  }
  catch (error: any) {
    conversationsError.value = extractErrorMessage(error, 'Could not load more conversations.')
  }
  finally {
    conversationsLoading.value = false
  }
}

async function loadCounts() {
  try {
    const params: Record<string, string | boolean> = {}
    if (statusFilter.value)
      params.status = statusFilter.value
    counts.value = await $api<ConversationCounts>('/v1/waba/conversations/counts', { params })
  }
  catch {
    // Non-critical -- the quick-filter chips just won't show counts this session.
  }
}

function setAssignmentFilter(value: '' | 'unassigned' | 'mine') {
  assignmentFilter.value = value
  loadConversations()
}

async function loadLabels() {
  try {
    labels.value = await $api<Label[]>('/v1/waba/labels')
  }
  catch {
    // Non-critical -- the inbox itself still works without labels loaded.
  }
}

async function loadCannedResponses() {
  try {
    cannedResponses.value = await $api<CannedResponse[]>('/v1/waba/canned-responses')
  }
  catch {
    // Non-critical -- composer just won't offer shortcuts this session.
  }
}

async function loadAssignableUsers() {
  try {
    assignableUsers.value = await $api<AssignableUser[]>('/v1/waba/assignable-users')
  }
  catch {
    // Non-critical -- the assignee picker just shows nobody to assign to.
  }
}

const messagesContainer = ref<HTMLElement>()

// Every chat app scrolls to the newest message by default -- without this the thread opens (or
// receives a new message) sitting wherever the scroll happened to be, which reads as the last
// message being cut off mid-bubble at the composer boundary rather than fully in view.
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value)
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  })
}

async function selectConversation(id: string) {
  threadLoading.value = true
  threadError.value = ''
  sendError.value = ''
  crmForm.value = null
  crmFormError.value = ''
  try {
    activeConversation.value = await $api<ConversationDetail>(`/v1/waba/conversations/${id}`)
    scrollToBottom()
    announceViewing(id)
    // Best-effort -- a failure here shouldn't block viewing the conversation itself. Updates the
    // list item locally too, so the unread dot clears immediately instead of waiting for the
    // next full reload.
    $api<Conversation>(`/v1/waba/conversations/${id}/read`, { method: 'POST' })
      .then(() => {
        const item = conversations.value.find(c => c.id === id)
        if (item)
          item.unread = false
      })
      .catch(() => {})
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not load this conversation.')
  }
  finally {
    threadLoading.value = false
  }
}

function pickCanned(canned: CannedResponse) {
  messageBody.value = canned.body
  cannedMenuOpen.value = false
}

async function sendMessage(andResolve = false) {
  if (!activeConversation.value || !messageBody.value.trim())
    return
  sendError.value = ''
  sending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/messages`, {
      method: 'POST',
      body: { body: messageBody.value, is_private: isPrivateNote.value },
    })
    activeConversation.value.messages.push(message)
    messageBody.value = ''
    isPrivateNote.value = false
    scrollToBottom()
    if (andResolve)
      await updateStatus('resolved')
    else
      await loadConversations()
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send this message.')
  }
  finally {
    sending.value = false
  }
}

// --- WhatsApp-markdown composer toolbar -- wraps the current textarea selection in the
// markers WhatsApp itself renders as bold/italic/strikethrough, or inserts empty markers with
// the cursor left in between when nothing is selected. Not a rich-text/HTML editor -- WhatsApp
// only ever understands this plain-text markdown, so anything fancier would just show up as
// literal asterisks on the customer's phone.
const composerTextarea = ref<{ $el: HTMLElement } | null>(null)

function wrapSelection(marker: string) {
  const el = composerTextarea.value?.$el?.querySelector('textarea')
  if (!el) {
    messageBody.value += `${marker}${marker}`
    return
  }
  const start = el.selectionStart
  const end = el.selectionEnd
  const selected = messageBody.value.slice(start, end)
  messageBody.value = messageBody.value.slice(0, start) + marker + selected + marker + messageBody.value.slice(end)
  nextTick(() => {
    el.focus()
    const cursor = start + marker.length + selected.length + (selected ? marker.length : 0)
    el.setSelectionRange(cursor, cursor)
  })
}

async function updateStatus(status: string) {
  if (!activeConversation.value)
    return
  try {
    const updated = await $api<Conversation>(`/v1/waba/conversations/${activeConversation.value.id}`, { method: 'PUT', body: { status } })
    activeConversation.value.status = updated.status
    await loadConversations()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update this conversation.')
  }
}

async function assignConversation(assignedUserId: string | null) {
  if (!activeConversation.value)
    return
  try {
    const updated = await $api<Conversation>(`/v1/waba/conversations/${activeConversation.value.id}`, { method: 'PUT', body: { assigned_user_id: assignedUserId } })
    activeConversation.value.assigned_user_id = updated.assigned_user_id
    await loadConversations()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update the assignee.')
  }
}

const router = useRouter()

// All three conversions (ticket/lead/customer) require an active CRM subscription, checked
// server-side -- a 422 here specifically means "not on the CRM plan", distinct from any other
// failure, so it gets its own actionable dialog (pointing at the Channels page to subscribe)
// instead of just a passive error banner nobody would act on.
const crmUpsellDialog = ref(false)

function handleConversionError(error: any, fallback: string) {
  if (error?.response?.status === 422 && String(error?.data?.detail || '').includes('CRM'))
    crmUpsellDialog.value = true
  else
    threadError.value = extractErrorMessage(error, fallback)
}

const convertingToTicket = ref(false)

async function convertToTicket() {
  if (!activeConversation.value)
    return
  convertingToTicket.value = true
  try {
    const updated = await $api<Conversation>(`/v1/waba/conversations/${activeConversation.value.id}/convert-to-ticket`, { method: 'POST' })
    activeConversation.value.is_ticket = updated.is_ticket
    activeConversation.value.ticket_number = updated.ticket_number
    await loadConversations()
  }
  catch (error: any) {
    handleConversionError(error, 'Could not convert this conversation to a ticket.')
  }
  finally {
    convertingToTicket.value = false
  }
}

// Lead/customer conversion opens a form in the contact-details panel instead of converting
// instantly -- both have their own fields (stage/owner/notes for a lead, owner/notes for a
// customer) worth filling in live while the agent is still talking to the customer, rather than
// defaulting them blind the way a one-click ticket conversion can (ticket has no fields of its
// own, so it stays a direct action). Only one of the two can be open at a time.
type PipelineStage = { name: string, probability: number, forecast_category: string }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
const crmForm = ref<{ mode: 'lead' | 'deal' | 'customer', company_name: string, pipeline_id: string | null, stage: string, value: number | null, probability: number | null, owner_user_id: string | null, notes: string } | null>(null)
const crmFormSubmitting = ref(false)
const crmFormError = ref('')
const pipelines = ref<Pipeline[]>([])

async function loadCrmPipelines() {
  try {
    pipelines.value = await $api<Pipeline[]>('/v1/crm/pipelines')
  }
  catch {
    // Not CRM-relevant enough to surface an error banner for -- the deal form just falls back to
    // an empty pipeline list if this fails.
  }
}

type Macro = { id: string, name: string }
const macros = ref<Macro[]>([])
const runningMacro = ref(false)

async function loadMacros() {
  try {
    macros.value = await $api<Macro[]>('/v1/waba/macros')
  }
  catch {
    // Non-critical -- the macro menu just shows empty if this fails.
  }
}

async function runMacro(macroId: string) {
  if (!activeConversation.value)
    return
  runningMacro.value = true
  try {
    const updated = await $api<Conversation>(`/v1/waba/conversations/${activeConversation.value.id}/run-macro/${macroId}`, { method: 'POST' })
    Object.assign(activeConversation.value, updated)
    await loadConversations()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not run this macro.')
  }
  finally {
    runningMacro.value = false
  }
}

function openLeadForm() {
  crmForm.value = { mode: 'lead', company_name: '', pipeline_id: null, stage: '', value: null, probability: null, owner_user_id: null, notes: '' }
  crmFormError.value = ''
}

function openDealForm() {
  const defaultPipeline = pipelines.value[0] || null
  crmForm.value = {
    mode: 'deal', company_name: '', pipeline_id: defaultPipeline?.id || null, stage: defaultPipeline?.stages[0]?.name || 'inquiry',
    value: null, probability: defaultPipeline?.stages[0]?.probability ?? null, owner_user_id: null, notes: '',
  }
  crmFormError.value = ''
}

function openCustomerForm() {
  crmForm.value = { mode: 'customer', company_name: '', pipeline_id: null, stage: '', value: null, probability: null, owner_user_id: null, notes: '' }
  crmFormError.value = ''
}

function closeCrmForm() {
  crmForm.value = null
  crmFormError.value = ''
}

async function submitCrmForm() {
  if (!activeConversation.value || !crmForm.value)
    return
  crmFormSubmitting.value = true
  crmFormError.value = ''
  try {
    if (crmForm.value.mode === 'lead') {
      await $api(`/v1/crm/conversations/${activeConversation.value.id}/convert-to-lead`, {
        method: 'POST',
        body: { company_name: crmForm.value.company_name || null, owner_user_id: crmForm.value.owner_user_id, notes: crmForm.value.notes || null },
      })
    }
    else if (crmForm.value.mode === 'deal') {
      await $api(`/v1/crm/conversations/${activeConversation.value.id}/convert-to-deal`, {
        method: 'POST',
        body: {
          pipeline_id: crmForm.value.pipeline_id, stage: crmForm.value.stage, value: crmForm.value.value,
          probability: crmForm.value.probability, owner_user_id: crmForm.value.owner_user_id, notes: crmForm.value.notes || null,
        },
      })
    }
    else {
      await $api(`/v1/crm/conversations/${activeConversation.value.id}/convert-to-customer`, {
        method: 'POST',
        body: { owner_user_id: crmForm.value.owner_user_id, notes: crmForm.value.notes || null },
      })
    }
    crmForm.value = null
  }
  catch (error: any) {
    if (error?.response?.status === 422 && String(error?.data?.detail || '').includes('CRM')) {
      crmForm.value = null
      crmUpsellDialog.value = true
    }
    else {
      crmFormError.value = extractErrorMessage(error, `Could not convert this conversation to a ${crmForm.value.mode}.`)
    }
  }
  finally {
    crmFormSubmitting.value = false
  }
}

async function toggleConversationLabel(label: Label) {
  if (!activeConversation.value)
    return
  const attached = activeConversation.value.labels.some(l => l.id === label.id)
  const method = attached ? 'DELETE' : 'POST'
  try {
    const updated = await $api<Conversation>(`/v1/waba/conversations/${activeConversation.value.id}/labels/${label.id}`, { method })
    activeConversation.value.labels = updated.labels
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update labels.')
  }
}

async function toggleContactLabel(label: Label) {
  if (!activeConversation.value)
    return
  const contact = activeConversation.value.contact
  const attached = contact.labels.some(l => l.id === label.id)
  const method = attached ? 'DELETE' : 'POST'
  try {
    const updated = await $api<Contact>(`/v1/waba/contacts/${contact.id}/labels/${label.id}`, { method })
    activeConversation.value.contact = updated
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update labels.')
  }
}

async function toggleOptedOut() {
  if (!activeConversation.value)
    return
  const contact = activeConversation.value.contact
  try {
    const updated = await $api<Contact>(`/v1/waba/contacts/${contact.id}`, { method: 'PUT', body: { opted_out: !contact.opted_out } })
    activeConversation.value.contact = updated
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not update this contact.')
  }
}

// --- Contact custom fields --------------------------------------------------------------------

const newFieldKey = ref('')
const newFieldValue = ref('')
const customFieldsError = ref('')

async function saveCustomAttributes(attributes: Record<string, string>) {
  if (!activeConversation.value)
    return
  customFieldsError.value = ''
  try {
    const updated = await $api<Contact>(`/v1/waba/contacts/${activeConversation.value.contact.id}`, { method: 'PUT', body: { custom_attributes: attributes } })
    activeConversation.value.contact = updated
  }
  catch (error: any) {
    customFieldsError.value = extractErrorMessage(error, 'Could not save this field.')
  }
}

function addCustomField() {
  if (!activeConversation.value || !newFieldKey.value.trim())
    return
  const attributes = { ...activeConversation.value.contact.custom_attributes, [newFieldKey.value.trim()]: newFieldValue.value }
  newFieldKey.value = ''
  newFieldValue.value = ''
  saveCustomAttributes(attributes)
}

function removeCustomField(key: string) {
  if (!activeConversation.value)
    return
  const attributes = { ...activeConversation.value.contact.custom_attributes }
  delete attributes[key]
  saveCustomAttributes(attributes)
}

// --- Labels dialog ---------------------------------------------------------------------------

const newLabelDialog = ref(false)
const newLabelScope = ref<'conversation' | 'contact'>('conversation')
const newLabelName = ref('')
const newLabelError = ref('')
const creatingLabel = ref(false)

function openNewLabelDialog(scope: 'conversation' | 'contact') {
  newLabelScope.value = scope
  newLabelName.value = ''
  newLabelError.value = ''
  newLabelDialog.value = true
}

async function createLabel() {
  if (!newLabelName.value.trim())
    return
  creatingLabel.value = true
  try {
    const label = await $api<Label>('/v1/waba/labels', { method: 'POST', body: { scope: newLabelScope.value, name: newLabelName.value.trim() } })
    labels.value.push(label)
    newLabelDialog.value = false
    if (activeConversation.value) {
      if (newLabelScope.value === 'conversation')
        await toggleConversationLabel(label)
      else
        await toggleContactLabel(label)
    }
  }
  catch (error: any) {
    newLabelError.value = extractErrorMessage(error, 'Could not create this label.')
  }
  finally {
    creatingLabel.value = false
  }
}

// --- Emoji picker (small curated set -- no external library/CDN) -----------------------------

const EMOJIS = [
  '😀', '😁', '😂', '🙂', '😊', '😉', '😍', '🤔', '😐', '😢', '😭', '😡', '😱', '👍', '👎',
  '🙏', '👏', '💪', '🤝', '👋', '❤️', '🔥', '🎉', '✅', '❌', '⏰', '📦', '💰', '📍', '⭐',
]
const emojiMenuOpen = ref(false)

function pickEmoji(emoji: string) {
  messageBody.value += emoji
}

// --- Rich media --------------------------------------------------------------------------------

const fileInput = ref<HTMLInputElement>()
const mediaUploading = ref(false)
const mediaError = ref('')

function triggerFilePicker() {
  fileInput.value?.click()
}

async function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !activeConversation.value)
    return
  mediaError.value = ''
  mediaUploading.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    if (messageBody.value.trim())
      formData.append('caption', messageBody.value.trim())
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/media`, { method: 'POST', body: formData })
    activeConversation.value.messages.push(message)
    messageBody.value = ''
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    mediaError.value = extractErrorMessage(error, 'Could not send this file.')
  }
  finally {
    mediaUploading.value = false
    if (fileInput.value)
      fileInput.value.value = ''
  }
}

function mediaUrl(messageId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL || window.location.origin
  const token = useCookie('accessToken').value
  return `${base}/v1/waba/media/${messageId}?token=${encodeURIComponent(token || '')}`
}

// --- Template messages ---------------------------------------------------------------------

const templates = ref<WabaTemplate[]>([])
const templateDialog = ref(false)
const templateLoading = ref(false)
const templateError = ref('')
const selectedTemplate = ref<WabaTemplate | null>(null)
const templateParamValues = ref<string[]>([])
const templateSending = ref(false)

const templatePlaceholderCount = computed(() => {
  if (!selectedTemplate.value?.body)
    return 0
  const matches = selectedTemplate.value.body.match(/\{\{\d+\}\}/g)
  return matches ? matches.length : 0
})

const templatePreview = computed(() => {
  if (!selectedTemplate.value?.body)
    return ''
  let text = selectedTemplate.value.body
  templateParamValues.value.forEach((value, i) => {
    text = text.replace(`{{${i + 1}}}`, value || `{{${i + 1}}}`)
  })
  return text
})

async function openTemplateDialog() {
  templateDialog.value = true
  templateError.value = ''
  selectedTemplate.value = null
  templateParamValues.value = []
  if (templates.value.length)
    return
  templateLoading.value = true
  try {
    templates.value = await $api<WabaTemplate[]>('/v1/waba/templates')
  }
  catch (error: any) {
    templateError.value = extractErrorMessage(error, 'Could not load templates from Meta.')
  }
  finally {
    templateLoading.value = false
  }
}

function selectTemplate(template: WabaTemplate) {
  selectedTemplate.value = template
  const matches = template.body?.match(/\{\{\d+\}\}/g) || []
  templateParamValues.value = matches.map(() => '')
}

async function sendTemplate() {
  if (!activeConversation.value || !selectedTemplate.value)
    return
  templateError.value = ''
  templateSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/template-message`, {
      method: 'POST',
      body: {
        template_name: selectedTemplate.value.name,
        language_code: selectedTemplate.value.language,
        body_params: templateParamValues.value,
        preview_body: templatePreview.value,
      },
    })
    activeConversation.value.messages.push(message)
    templateDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    templateError.value = extractErrorMessage(error, 'Could not send this template.')
  }
  finally {
    templateSending.value = false
  }
}

// --- New conversation (first-touch send to a number that's never messaged in) --------------

const newConversationDialog = ref(false)
const newConversationForm = ref({ wa_id: '', name: '' })
const newConversationError = ref('')
const newConversationSending = ref(false)
const newConvSelectedTemplate = ref<WabaTemplate | null>(null)
const newConvParamValues = ref<string[]>([])

const newConvPreview = computed(() => {
  if (!newConvSelectedTemplate.value?.body)
    return ''
  let text = newConvSelectedTemplate.value.body
  newConvParamValues.value.forEach((value, i) => {
    text = text.replace(`{{${i + 1}}}`, value || `{{${i + 1}}}`)
  })
  return text
})

async function openNewConversationDialog() {
  newConversationDialog.value = true
  newConversationError.value = ''
  newConversationForm.value = { wa_id: '', name: '' }
  newConvSelectedTemplate.value = null
  newConvParamValues.value = []
  if (templates.value.length)
    return
  templateLoading.value = true
  try {
    templates.value = await $api<WabaTemplate[]>('/v1/waba/templates')
  }
  catch (error: any) {
    newConversationError.value = extractErrorMessage(error, 'Could not load templates from Meta.')
  }
  finally {
    templateLoading.value = false
  }
}

function selectNewConvTemplate(template: WabaTemplate) {
  newConvSelectedTemplate.value = template
  const matches = template.body?.match(/\{\{\d+\}\}/g) || []
  newConvParamValues.value = matches.map(() => '')
}

async function sendNewConversation() {
  if (!newConversationForm.value.wa_id.trim() || !newConvSelectedTemplate.value)
    return
  newConversationError.value = ''
  newConversationSending.value = true
  try {
    const conversation = await $api<Conversation>('/v1/waba/conversations/start', {
      method: 'POST',
      body: {
        wa_id: newConversationForm.value.wa_id.trim(),
        name: newConversationForm.value.name.trim() || null,
        template_name: newConvSelectedTemplate.value.name,
        language_code: newConvSelectedTemplate.value.language,
        body_params: newConvParamValues.value,
        preview_body: newConvPreview.value,
      },
    })
    newConversationDialog.value = false
    await loadConversations()
    await selectConversation(conversation.id)
  }
  catch (error: any) {
    newConversationError.value = extractErrorMessage(error, 'Could not start this conversation.')
  }
  finally {
    newConversationSending.value = false
  }
}

// --- Location, contact card, interactive buttons/list, reactions ---------------------------

const locationDialog = ref(false)
const locationForm = ref({ latitude: '', longitude: '', name: '', address: '' })
const locationError = ref('')
const locationSending = ref(false)

function openLocationDialog() {
  locationForm.value = { latitude: '', longitude: '', name: '', address: '' }
  locationError.value = ''
  locationDialog.value = true
}

async function sendLocation() {
  if (!activeConversation.value)
    return
  const latitude = Number(locationForm.value.latitude)
  const longitude = Number(locationForm.value.longitude)
  if (Number.isNaN(latitude) || Number.isNaN(longitude)) {
    locationError.value = 'Enter valid latitude and longitude.'
    return
  }
  locationError.value = ''
  locationSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/location-message`, {
      method: 'POST',
      body: { latitude, longitude, name: locationForm.value.name || null, address: locationForm.value.address || null },
    })
    activeConversation.value.messages.push(message)
    locationDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    locationError.value = extractErrorMessage(error, 'Could not send this location.')
  }
  finally {
    locationSending.value = false
  }
}

const contactDialog = ref(false)
const contactForm = ref({ formatted_name: '', phone: '' })
const contactError = ref('')
const contactSending = ref(false)

function openContactDialog() {
  contactForm.value = { formatted_name: '', phone: '' }
  contactError.value = ''
  contactDialog.value = true
}

async function sendContactCard() {
  if (!activeConversation.value || !contactForm.value.formatted_name.trim() || !contactForm.value.phone.trim())
    return
  contactError.value = ''
  contactSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/contact-message`, {
      method: 'POST',
      body: { contacts: [{ formatted_name: contactForm.value.formatted_name.trim(), phone: contactForm.value.phone.trim() }] },
    })
    activeConversation.value.messages.push(message)
    contactDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    contactError.value = extractErrorMessage(error, 'Could not send this contact.')
  }
  finally {
    contactSending.value = false
  }
}

type CatalogItem = {
  id: string
  product_retailer_id: string
  name: string
  image_url: string | null
  price: string | null
  currency: string | null
  availability: string | null
}

const catalogItems = ref<CatalogItem[]>([])
const catalogSearch = ref('')
const catalogLoading = ref(false)
let catalogSearchTimer: ReturnType<typeof setTimeout> | undefined

async function loadCatalogItems() {
  catalogLoading.value = true
  try {
    catalogItems.value = await $api<CatalogItem[]>('/v1/waba/catalog', { params: catalogSearch.value ? { q: catalogSearch.value } : {} })
  }
  catch {
    catalogItems.value = []
  }
  finally {
    catalogLoading.value = false
  }
}

watch(catalogSearch, () => {
  clearTimeout(catalogSearchTimer)
  catalogSearchTimer = setTimeout(loadCatalogItems, 300)
})

const productDialog = ref(false)
const productForm = ref({ product_retailer_id: '', body_text: '' })
const productError = ref('')
const productSending = ref(false)

function openProductDialog() {
  productForm.value = { product_retailer_id: '', body_text: '' }
  productError.value = ''
  catalogSearch.value = ''
  productDialog.value = true
  loadCatalogItems()
}

function pickProduct(item: CatalogItem) {
  productForm.value.product_retailer_id = item.product_retailer_id
}

async function sendProduct() {
  if (!activeConversation.value)
    return
  if (!productForm.value.product_retailer_id.trim()) {
    productError.value = 'Pick a product, or enter its ID from your Meta catalog.'
    return
  }
  productError.value = ''
  productSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/product`, {
      method: 'POST',
      body: { product_retailer_id: productForm.value.product_retailer_id.trim(), body_text: productForm.value.body_text.trim() || null },
    })
    activeConversation.value.messages.push(message)
    productDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    productError.value = extractErrorMessage(error, 'Could not send this product.')
  }
  finally {
    productSending.value = false
  }
}

const productListDialog = ref(false)
const productListForm = ref({ header_text: '', body_text: '' })
const productListSelection = ref<CatalogItem[]>([])
const productListError = ref('')
const productListSending = ref(false)

function openProductListDialog() {
  productListForm.value = { header_text: '', body_text: '' }
  productListSelection.value = []
  productListError.value = ''
  catalogSearch.value = ''
  productListDialog.value = true
  loadCatalogItems()
}

function toggleProductListItem(item: CatalogItem) {
  const index = productListSelection.value.findIndex(p => p.product_retailer_id === item.product_retailer_id)
  if (index === -1)
    productListSelection.value.push(item)
  else
    productListSelection.value.splice(index, 1)
}

async function sendProductList() {
  if (!activeConversation.value)
    return
  if (!productListForm.value.header_text.trim() || !productListForm.value.body_text.trim()) {
    productListError.value = 'Header and message are both required.'
    return
  }
  if (!productListSelection.value.length) {
    productListError.value = 'Select at least one product.'
    return
  }
  productListError.value = ''
  productListSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/product-list`, {
      method: 'POST',
      body: {
        header_text: productListForm.value.header_text.trim(),
        body_text: productListForm.value.body_text.trim(),
        sections: [{ title: 'Products', product_items: productListSelection.value.map(p => ({ product_retailer_id: p.product_retailer_id })) }],
      },
    })
    activeConversation.value.messages.push(message)
    productListDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    productListError.value = extractErrorMessage(error, 'Could not send this product list.')
  }
  finally {
    productListSending.value = false
  }
}

const buttonsDialog = ref(false)
const buttonsForm = ref({ body_text: '', button_labels: [''] })
const buttonsError = ref('')
const buttonsSending = ref(false)

function openButtonsDialog() {
  buttonsForm.value = { body_text: '', button_labels: [''] }
  buttonsError.value = ''
  buttonsDialog.value = true
}

async function sendInteractiveButtons() {
  if (!activeConversation.value)
    return
  const labels = buttonsForm.value.button_labels.map(l => l.trim()).filter(Boolean)
  if (!buttonsForm.value.body_text.trim() || !labels.length) {
    buttonsError.value = 'Enter a message and at least one button.'
    return
  }
  buttonsError.value = ''
  buttonsSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/interactive-buttons`, {
      method: 'POST',
      body: { body_text: buttonsForm.value.body_text.trim(), button_labels: labels },
    })
    activeConversation.value.messages.push(message)
    buttonsDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    buttonsError.value = extractErrorMessage(error, 'Could not send these buttons.')
  }
  finally {
    buttonsSending.value = false
  }
}

const listDialog = ref(false)
const listForm = ref({ body_text: '', button_label: '', rows: [{ title: '', description: '' }] })
const listError = ref('')
const listSending = ref(false)

function openListDialog() {
  listForm.value = { body_text: '', button_label: '', rows: [{ title: '', description: '' }] }
  listError.value = ''
  listDialog.value = true
}

async function sendInteractiveList() {
  if (!activeConversation.value)
    return
  const rows = listForm.value.rows.filter(r => r.title.trim()).map(r => ({ title: r.title.trim(), description: r.description.trim() || null }))
  if (!listForm.value.body_text.trim() || !listForm.value.button_label.trim() || !rows.length) {
    listError.value = 'Enter a message, a button label, and at least one option.'
    return
  }
  listError.value = ''
  listSending.value = true
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/interactive-list`, {
      method: 'POST',
      body: { body_text: listForm.value.body_text.trim(), button_label: listForm.value.button_label.trim(), rows },
    })
    activeConversation.value.messages.push(message)
    listDialog.value = false
    scrollToBottom()
    await loadConversations()
  }
  catch (error: any) {
    listError.value = extractErrorMessage(error, 'Could not send this list.')
  }
  finally {
    listSending.value = false
  }
}

const REACTION_EMOJIS = ['👍', '❤️', '😂', '😮', '😢', '🙏']
const reactingToMessageId = ref<string | null>(null)

async function sendReaction(messageId: string, emoji: string) {
  if (!activeConversation.value)
    return
  reactingToMessageId.value = null
  try {
    const message = await $api<ConversationMessage>(`/v1/waba/conversations/${activeConversation.value.id}/react`, {
      method: 'POST',
      body: { message_id: messageId, emoji },
    })
    activeConversation.value.messages.push(message)
    scrollToBottom()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not send this reaction.')
  }
}

function mapsUrl(latitude: number, longitude: number): string {
  return `https://www.google.com/maps?q=${latitude},${longitude}`
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : ''
}

// The conversation list's append column has very little room -- a full "09 Aug, 07:50 pm" there
// crowds out the contact name it's supposed to sit beside. Time-only is enough for "at a glance"
// in a list you're scanning; the full date+time is still shown once you open the thread.
function formatShortTime(value: string | null) {
  return value ? new Date(value).toLocaleString('en-IN', { hour: '2-digit', minute: '2-digit' }) : ''
}

// --- Realtime: one WebSocket per browser tab, fed by the API's Redis pub/sub (waba_realtime.py).
// A missed event just means a manual refresh is needed -- the REST endpoints above stay the
// source of truth, so this connection is treated as best-effort throughout.
let socket: WebSocket | null = null
let reconnectTimeout: ReturnType<typeof setTimeout> | undefined

function wsUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL || window.location.origin
  const token = useCookie('accessToken').value
  return `${base.replace(/^http/, 'ws')}/v1/waba/ws?token=${encodeURIComponent(token || '')}`
}

function connectSocket() {
  socket = new WebSocket(wsUrl())
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'message') {
        const message = payload.message as ConversationMessage
        // The tab that just sent a message already appended it optimistically below (sendMessage)
        // -- the WebSocket echoes every send back through the same channel, so without this check
        // the sender's own message would render twice.
        if (activeConversation.value?.id === message.conversation_id && !activeConversation.value.messages.some(m => m.id === message.id)) {
          activeConversation.value.messages.push(message)
          scrollToBottom()
        }
        loadConversations()
      }
      else if (payload.type === 'message_status') {
        if (activeConversation.value?.id === payload.conversation_id) {
          const target = activeConversation.value.messages.find(m => m.id === payload.message_id)
          if (target)
            target.status = payload.status
        }
      }
      else if (payload.type === 'presence') {
        // Collision detection -- another agent (including this same user's own other tab, hence
        // the id check) opened the conversation currently being viewed. Cleared after a short
        // window so a viewer who's since navigated away doesn't linger in the banner forever.
        if (payload.conversation_id === activeConversation.value?.id && payload.user_id !== authStore.profile?.id) {
          otherViewer.value = payload.user_name
          if (otherViewerTimeout)
            clearTimeout(otherViewerTimeout)
          otherViewerTimeout = setTimeout(() => { otherViewer.value = null }, 30000)
        }
      }
    }
    catch {
      // Ignore anything that isn't the JSON shape we expect.
    }
  }
  socket.onclose = () => {
    socket = null
    reconnectTimeout = setTimeout(connectSocket, 5000)
  }
}

const otherViewer = ref<string | null>(null)
let otherViewerTimeout: ReturnType<typeof setTimeout> | undefined

function announceViewing(conversationId: string) {
  otherViewer.value = null
  if (socket && socket.readyState === WebSocket.OPEN)
    socket.send(JSON.stringify({ type: 'viewing', conversation_id: conversationId }))
}

// The 3-pane layout's column height was previously a flat "78vh" guess -- it only ever looked
// right at the one window size it was tuned against. At a shorter window (smaller screen,
// browser zoom back to 100%, a non-maximized window) 78% of a smaller number left less room
// than the composer's own fixed-height content (toolbar + tabs + textarea + buttons) actually
// needs, and since the card clips overflow, the tabs/composer got cut off -- confirmed live, not
// guessed. Measuring the row's real distance from the bottom of the viewport and recomputing on
// resize/orientation-change is the only way this stays correct across actual screen sizes rather
// than the one viewport it happened to be eyeballed against.
const panelRow = ref<{ $el: HTMLElement } | null>(null)
const panelHeight = ref(600)

function updatePanelHeight() {
  const el = panelRow.value?.$el
  if (!el)
    return
  const top = el.getBoundingClientRect().top
  panelHeight.value = Math.max(360, Math.floor(window.innerHeight - top - 24))
}

onMounted(() => {
  loadConversations()
  loadLabels()
  loadCannedResponses()
  loadAssignableUsers()
  loadCrmPipelines()
  loadMacros()
  connectSocket()
  updatePanelHeight()
  window.addEventListener('resize', updatePanelHeight)
  nowTickInterval = setInterval(() => { nowTick.value = Date.now() }, 60000)
  // Deep link from the WhatsApp contacts directory's "Open chat" action.
  if (typeof route.query.conversation === 'string')
    selectConversation(route.query.conversation)
})
onBeforeUnmount(() => {
  if (reconnectTimeout)
    clearTimeout(reconnectTimeout)
  socket?.close()
  window.removeEventListener('resize', updatePanelHeight)
  if (nowTickInterval)
    clearInterval(nowTickInterval)
})

watch(statusFilter, loadConversations)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-4">
    <h1 class="text-h4 mb-0">
      Inbox
    </h1>
    <VBtn size="small" prepend-icon="tabler-plus" @click="openNewConversationDialog">
      New Conversation
    </VBtn>
  </div>

  <VRow ref="panelRow" :style="{ minHeight: `${panelHeight}px` }">
    <VCol cols="12" md="4" lg="3" class="d-flex flex-column" :style="{ maxHeight: `${panelHeight}px` }">
      <VCard class="flex-grow-1 d-flex flex-column overflow-hidden">
        <VCardText class="pb-2 flex-grow-0 flex-shrink-0">
          <VTextField
            v-model="searchQuery"
            placeholder="Search conversations"
            prepend-inner-icon="tabler-search"
            density="compact"
            variant="outlined"
            hide-details
            clearable
            class="mb-2"
          />
          <VSelect
            v-model="statusFilter"
            :items="[{ title: 'Open', value: 'open' }, { title: 'Pending', value: 'pending' }, { title: 'Resolved', value: 'resolved' }, { title: 'All', value: '' }]"
            density="compact"
            variant="outlined"
            hide-details
            class="mb-2"
          />
          <!-- Plain wrapping chips, not VChipGroup -- VChipGroup is a VSlideGroup underneath,
          designed to scroll (with "<"/">" arrows) rather than wrap, which kept fighting narrow
          sidebars: chips squeezed to near-zero width or overflowed instead of just dropping to a
          second line the way normal flex-wrap content does. -->
          <div class="d-flex flex-wrap ga-1">
            <VChip
              size="x-small"
              style="font-size: 11px;"
              :variant="assignmentFilter === '' ? 'flat' : 'outlined'"
              @click="setAssignmentFilter('')"
            >
              All {{ counts.all }}
            </VChip>
            <VChip
              size="x-small"
              style="font-size: 11px;"
              :variant="assignmentFilter === 'unassigned' ? 'flat' : 'outlined'"
              @click="setAssignmentFilter('unassigned')"
            >
              Unassigned {{ counts.unassigned }}
            </VChip>
            <VChip
              size="x-small"
              style="font-size: 11px;"
              :variant="assignmentFilter === 'mine' ? 'flat' : 'outlined'"
              @click="setAssignmentFilter('mine')"
            >
              Mine {{ counts.assigned_to_me }}
            </VChip>
          </div>
        </VCardText>
        <VDivider />
        <VAlert v-if="conversationsError" type="error" variant="tonal" density="compact" class="ma-3">
          {{ conversationsError }}
        </VAlert>
        <div class="overflow-y-auto flex-grow-1" style="min-height: 0;">
          <VList v-if="conversations.length" density="compact" nav>
            <VListItem
              v-for="conversation in conversations"
              :key="conversation.id"
              :active="activeConversation?.id === conversation.id"
              @click="selectConversation(conversation.id)"
            >
              <template #prepend>
                <VAvatar color="primary" variant="tonal" size="36">
                  {{ (conversation.contact.name || conversation.contact.wa_id || conversation.contact.email || '?').slice(0, 1).toUpperCase() }}
                </VAvatar>
              </template>
              <VListItemTitle :class="conversation.unread ? 'font-weight-bold' : ''" class="d-flex align-center ga-1">
                <VIcon v-if="conversation.is_ticket" icon="tabler-ticket" size="14" color="info" />
                <span class="text-truncate">{{ conversation.contact.name || conversation.contact.wa_id || conversation.contact.email || 'Unknown contact' }}</span>
              </VListItemTitle>
              <VListItemSubtitle :class="conversation.unread ? 'font-weight-medium text-high-emphasis' : ''">
                {{ conversation.last_message_preview || conversation.contact.wa_id || conversation.contact.email }}
              </VListItemSubtitle>
              <template #append>
                <div class="d-flex flex-column align-end ga-1" style="min-width: 46px;">
                  <span class="text-caption text-medium-emphasis" style="white-space: nowrap;">{{ formatShortTime(conversation.last_message_at) }}</span>
                  <div class="d-flex align-center ga-1">
                    <VIcon v-if="conversation.unread" icon="tabler-circle-filled" color="primary" size="8" />
                    <VIcon
                      icon="tabler-circle-filled"
                      size="10"
                      :color="conversation.status === 'open' ? 'success' : conversation.status === 'pending' ? 'warning' : 'grey'"
                    />
                  </div>
                </div>
              </template>
            </VListItem>
          </VList>
          <p v-else-if="!conversationsLoading" class="text-medium-emphasis text-center pa-6">
            No conversations here.
          </p>
          <div v-if="conversationsHasMore" class="text-center pa-3">
            <VBtn size="small" variant="text" :loading="conversationsLoading" @click="loadMoreConversations">
              Load more
            </VBtn>
          </div>
        </div>
      </VCard>
    </VCol>

    <VCol cols="12" md="8" lg="6" class="d-flex flex-column" :style="{ maxHeight: `${panelHeight}px` }">
      <VCard v-if="!activeConversation" class="flex-grow-1 d-flex align-center justify-center">
        <p class="text-medium-emphasis">
          Select a conversation to view messages.
        </p>
      </VCard>

      <VCard v-else class="flex-grow-1 d-flex flex-column overflow-hidden">
        <VCardText class="d-flex align-center flex-wrap ga-3 pb-3 flex-grow-0 flex-shrink-0">
          <strong>{{ activeConversation.contact.name || activeConversation.contact.wa_id || activeConversation.contact.email }}</strong>
          <VChip v-if="activeConversation.is_ticket" size="small" color="info" prepend-icon="tabler-ticket">
            {{ activeConversation.ticket_number }}
          </VChip>
          <VChip
            v-if="messageWindow && messageWindow.state !== 'none'"
            size="small"
            variant="outlined"
            :color="messageWindow.state === 'closed' ? 'error' : messageWindow.state === 'closing' ? 'warning' : 'success'"
            prepend-icon="tabler-clock"
          >
            {{ messageWindow.state === 'closed' ? '24h window closed' : `${formatWindowRemaining(messageWindow.hoursLeft)} left` }}
          </VChip>
          <VChip v-if="activeConversation.sla_breached" size="small" color="error" prepend-icon="tabler-alert-triangle">
            SLA breached
          </VChip>
          <VChip v-if="otherViewer" size="small" color="info" variant="outlined" prepend-icon="tabler-eye">
            {{ otherViewer }} is also viewing this
          </VChip>
          <VSpacer />
          <VMenu v-if="macros.length">
            <template #activator="{ props: menuProps }">
              <VBtn size="small" variant="tonal" prepend-icon="tabler-bolt" :loading="runningMacro" v-bind="menuProps">
                Macros
              </VBtn>
            </template>
            <VList>
              <VListItem v-for="macro in macros" :key="macro.id" :title="macro.name" @click="runMacro(macro.id)" />
            </VList>
          </VMenu>
          <VMenu>
            <template #activator="{ props: menuProps }">
              <VBtn
                size="small"
                variant="tonal"
                prepend-icon="tabler-user-plus"
                :loading="convertingToTicket"
                v-bind="menuProps"
              >
                Convert to CRM
              </VBtn>
            </template>
            <VList>
              <VListItem prepend-icon="tabler-target-arrow" title="Create lead" @click="openLeadForm" />
              <VListItem prepend-icon="tabler-briefcase" title="Create deal" @click="openDealForm" />
              <VListItem prepend-icon="tabler-user-check" title="Create customer" @click="openCustomerForm" />
              <VListItem v-if="!activeConversation.is_ticket" prepend-icon="tabler-ticket" title="Create ticket" @click="convertToTicket" />
            </VList>
          </VMenu>
          <VSelect
            :model-value="activeConversation.assigned_user_id"
            :items="[{ title: 'Unassigned', value: null }, ...assignableUsers.map(u => ({ title: u.full_name, value: u.id }))]"
            density="compact"
            variant="outlined"
            hide-details
            style="max-width: 180px;"
            @update:model-value="assignConversation"
          />
          <VSelect
            :model-value="activeConversation.status"
            :items="['open', 'pending', 'resolved']"
            density="compact"
            variant="outlined"
            hide-details
            style="max-width: 160px;"
            @update:model-value="updateStatus"
          />
        </VCardText>
        <VDivider />

        <VAlert v-if="threadError" type="error" variant="tonal" density="compact" class="ma-3">
          {{ threadError }}
        </VAlert>

        <div ref="messagesContainer" class="flex-grow-1 overflow-y-auto pa-4" style="min-height: 0;">
          <div
            v-for="message in activeConversation.messages"
            :key="message.id"
            class="d-flex mb-3 message-row"
            :class="message.direction === 'outbound' ? 'justify-end' : 'justify-start'"
          >
            <VBtn
              v-if="!message.is_private && message.message_type !== 'reaction'"
              size="x-small"
              variant="text"
              icon
              class="message-react-btn align-self-center"
            >
              <VIcon icon="tabler-mood-smile" size="16" />
              <VMenu :model-value="reactingToMessageId === message.id" activator="parent" :close-on-content-click="false" location="top" @update:model-value="v => (reactingToMessageId = v ? message.id : null)">
                <VCard>
                  <VCardText class="d-flex ga-1 pa-2">
                    <VBtn v-for="emoji in REACTION_EMOJIS" :key="emoji" variant="text" size="small" @click="sendReaction(message.id, emoji)">
                      <span style="font-size: 16px;">{{ emoji }}</span>
                    </VBtn>
                  </VCardText>
                </VCard>
              </VMenu>
            </VBtn>
            <div
              class="pa-3 rounded-lg"
              :style="{
                maxWidth: '75%',
                backgroundColor: message.is_private ? 'rgb(var(--v-theme-warning), 0.16)' : message.direction === 'outbound' ? 'rgb(var(--v-theme-primary), 0.14)' : 'rgb(var(--v-theme-on-surface), 0.06)',
              }"
            >
              <p v-if="message.is_private" class="text-caption text-warning mb-1">
                Private note
              </p>

              <img
                v-if="(message.message_type === 'image' || message.message_type === 'sticker') && message.media_url"
                :src="mediaUrl(message.id)"
                class="rounded mb-1"
                :style="message.message_type === 'sticker' ? 'width: 96px; height: 96px; display: block;' : 'max-width: 100%; max-height: 300px; display: block;'"
              >
              <video
                v-else-if="message.message_type === 'video' && message.media_url"
                :src="mediaUrl(message.id)"
                controls
                class="rounded mb-1"
                style="max-width: 100%; max-height: 300px;"
              />
              <audio
                v-else-if="message.message_type === 'audio' && message.media_url"
                :src="mediaUrl(message.id)"
                controls
                class="mb-1"
              />
              <a
                v-else-if="message.message_type === 'document' && message.media_url"
                :href="mediaUrl(message.id)"
                target="_blank"
                rel="noopener"
                class="d-flex align-center ga-1 mb-1"
              >
                <VIcon icon="tabler-file" size="18" />
                Download document
              </a>

              <a
                v-else-if="message.message_type === 'location' && message.payload"
                :href="mapsUrl(message.payload.latitude, message.payload.longitude)"
                target="_blank"
                rel="noopener"
                class="d-flex align-center ga-1 mb-1"
              >
                <VIcon icon="tabler-map-pin" size="18" />
                Open location on map
              </a>

              <div v-else-if="message.message_type === 'contacts' && message.payload">
                <div v-for="(c, i) in message.payload.contacts" :key="i" class="d-flex align-center ga-2 mb-1">
                  <VIcon icon="tabler-address-book" size="18" />
                  <span>{{ c.name?.formatted_name }} -- {{ c.phones?.[0]?.phone }}</span>
                </div>
              </div>

              <div v-else-if="message.message_type === 'interactive_button' && message.payload">
                <div class="d-flex flex-wrap ga-2 mt-2">
                  <VChip v-for="b in message.payload.buttons" :key="b.id" size="small" variant="outlined">
                    {{ b.title }}
                  </VChip>
                </div>
              </div>

              <div v-else-if="message.message_type === 'interactive_list' && message.payload">
                <div class="d-flex flex-column ga-1 mt-2">
                  <VChip v-for="row in message.payload.sections?.[0]?.rows || []" :key="row.id" size="small" variant="outlined" class="align-self-start">
                    {{ row.title }}
                  </VChip>
                </div>
              </div>

              <VChip v-else-if="message.message_type === 'interactive' && message.payload" size="small" color="primary" variant="tonal" prepend-icon="tabler-corner-down-right">
                {{ message.payload.title }}
              </VChip>

              <VChip v-else-if="message.message_type === 'product' && message.payload" size="small" variant="outlined" prepend-icon="tabler-shopping-bag" class="mt-2">
                {{ message.payload.product_retailer_id }}
              </VChip>

              <div v-else-if="message.message_type === 'product_list' && message.payload">
                <div class="d-flex flex-column ga-1 mt-2">
                  <VChip
                    v-for="item in (message.payload.sections || []).flatMap((s: any) => s.product_items || [])" :key="item.product_retailer_id"
                    size="small" variant="outlined" prepend-icon="tabler-shopping-bag" class="align-self-start"
                  >
                    {{ item.product_retailer_id }}
                  </VChip>
                </div>
              </div>

              <div v-else-if="message.message_type === 'order' && message.payload">
                <div class="d-flex flex-column ga-1 mt-2">
                  <VChip
                    v-for="(item, idx) in message.payload.product_items || []" :key="idx"
                    size="small" color="success" variant="tonal" prepend-icon="tabler-shopping-cart" class="align-self-start"
                  >
                    {{ item.product_retailer_id }} × {{ item.quantity }}
                  </VChip>
                </div>
              </div>

              <p v-if="message.message_type === 'reaction'" class="mb-1" style="font-size: 20px;">
                {{ message.payload?.emoji || message.body }}
              </p>
              <p v-else-if="message.body" class="mb-1" style="white-space: pre-wrap;">
                {{ message.body }}
              </p>
              <p v-if="message.error" class="text-caption text-error mb-0">
                {{ message.error }}
              </p>
              <p class="text-caption text-medium-emphasis mb-0">
                {{ formatTime(message.created_at) }}
                <span v-if="message.direction === 'outbound' && !message.is_private && message.status"> · {{ message.status }}</span>
              </p>
            </div>
          </div>
        </div>

        <VDivider />
        <VTabs
          :model-value="isPrivateNote ? 'note' : 'reply'"
          density="compact"
          class="flex-shrink-0"
          @update:model-value="v => (isPrivateNote = v === 'note')"
        >
          <VTab value="reply">
            Reply
          </VTab>
          <VTab value="note">
            Private Note
          </VTab>
        </VTabs>
        <VDivider />
        <VCardText :style="isPrivateNote ? { backgroundColor: 'rgb(var(--v-theme-warning), 0.06)' } : {}">
          <VAlert
            v-if="!isPrivateNote && messageWindow?.state === 'closed'"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-3"
          >
            WhatsApp's 24-hour reply window has closed for this contact. Send a template message instead.
          </VAlert>
          <VAlert
            v-else-if="!isPrivateNote && messageWindow?.state === 'closing'"
            type="warning"
            variant="tonal"
            density="compact"
            class="mb-3"
          >
            Reply window closes in {{ formatWindowRemaining(messageWindow.hoursLeft) }} -- after that, only a template message will go through.
          </VAlert>
          <VAlert v-if="sendError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ sendError }}
          </VAlert>
          <VAlert v-if="mediaError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ mediaError }}
          </VAlert>
          <div class="d-flex align-center ga-1 mb-1">
            <VBtn size="x-small" variant="text" icon="tabler-bold" @click="wrapSelection('*')" />
            <VBtn size="x-small" variant="text" icon="tabler-italic" @click="wrapSelection('_')" />
            <VBtn size="x-small" variant="text" icon="tabler-strikethrough" @click="wrapSelection('~')" />
          </div>
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
              ref="composerTextarea"
              v-model="messageBody"
              rows="2"
              auto-grow
              :placeholder="isPrivateNote ? 'Leave a note for your team...' : 'Type a message, or / for a canned response'"
              @keydown.enter.exact.prevent="sendMessage()"
            />
          </div>
          <div class="d-flex align-center ga-1 mt-2">
            <VBtn size="small" variant="text" icon>
              <VIcon icon="tabler-mood-smile" />
              <VMenu v-model="emojiMenuOpen" activator="parent" :close-on-content-click="false" location="top">
                <VCard max-width="260">
                  <VCardText class="d-flex flex-wrap ga-1">
                    <VBtn
                      v-for="emoji in EMOJIS"
                      :key="emoji"
                      variant="text"
                      size="small"
                      @click="pickEmoji(emoji)"
                    >
                      <span style="font-size: 18px;">{{ emoji }}</span>
                    </VBtn>
                  </VCardText>
                </VCard>
              </VMenu>
            </VBtn>
            <VBtn size="small" variant="text" icon="tabler-paperclip" :loading="mediaUploading" @click="triggerFilePicker" />
            <input ref="fileInput" type="file" class="d-none" @change="onFileSelected">
            <VBtn size="small" variant="text" icon @click="openTemplateDialog">
              <VIcon icon="tabler-file-text" />
              <VTooltip activator="parent" location="top">
                Send a template message
              </VTooltip>
            </VBtn>
            <VBtn size="small" variant="text" icon>
              <VIcon icon="tabler-dots" />
              <VTooltip activator="parent" location="top">
                More
              </VTooltip>
              <VMenu activator="parent" location="top">
                <VList density="compact">
                  <VListItem prepend-icon="tabler-map-pin" title="Location" @click="openLocationDialog" />
                  <VListItem prepend-icon="tabler-address-book" title="Contact card" @click="openContactDialog" />
                  <VListItem prepend-icon="tabler-list-details" title="Quick-reply buttons" @click="openButtonsDialog" />
                  <VListItem prepend-icon="tabler-list" title="List message" @click="openListDialog" />
                  <VListItem prepend-icon="tabler-shopping-bag" title="Product" @click="openProductDialog" />
                  <VListItem prepend-icon="tabler-shopping-cart" title="Product list" @click="openProductListDialog" />
                </VList>
              </VMenu>
            </VBtn>
          </div>
          <div class="d-flex align-center ga-3 mt-2">
            <VSpacer />
            <VBtn v-if="!isPrivateNote" variant="tonal" :loading="sending" :disabled="!messageBody.trim()" @click="sendMessage(true)">
              Send &amp; Resolve
            </VBtn>
            <VBtn :loading="sending" :disabled="!messageBody.trim()" @click="sendMessage()">
              {{ isPrivateNote ? 'Add note' : 'Send' }}
            </VBtn>
          </div>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" lg="3" class="d-flex flex-column" :style="{ maxHeight: `${panelHeight}px` }">
      <VCard v-if="activeConversation" class="flex-grow-1 overflow-y-auto">
        <VCardText class="text-center pb-2">
          <VAvatar color="primary" variant="tonal" size="56" class="mb-2">
            <span class="text-h6">{{ (activeConversation.contact.name || activeConversation.contact.wa_id || activeConversation.contact.email || '?').slice(0, 1).toUpperCase() }}</span>
          </VAvatar>
          <p class="text-h6 mb-0">
            {{ activeConversation.contact.name || '—' }}
          </p>
          <p class="text-body-2 text-medium-emphasis mb-0">
            {{ activeConversation.contact.wa_id || activeConversation.contact.email || '—' }}
          </p>
        </VCardText>
        <VDivider />

        <VCardText v-if="crmForm">
          <h3 class="text-subtitle-1 mb-3">
            {{ crmForm.mode === 'lead' ? 'Create lead' : crmForm.mode === 'deal' ? 'Create deal' : 'Create customer' }}
          </h3>
          <VAlert v-if="crmFormError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ crmFormError }}
          </VAlert>
          <VTextField
            v-if="crmForm.mode === 'lead'"
            v-model="crmForm.company_name"
            label="Company (optional)"
            density="compact"
            class="mb-3"
          />
          <template v-if="crmForm.mode === 'deal'">
            <VSelect
              v-model="crmForm.pipeline_id"
              :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
              label="Pipeline"
              density="compact"
              class="mb-3"
            />
            <VSelect
              v-model="crmForm.stage"
              :items="(pipelines.find(p => p.id === crmForm!.pipeline_id)?.stages || []).map(s => ({ title: formatLabel(s.name), value: s.name }))"
              label="Stage"
              density="compact"
              class="mb-3"
            />
            <VTextField v-model.number="crmForm.value" label="Deal value (INR)" type="number" min="0" density="compact" class="mb-3" />
            <VTextField v-model.number="crmForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" class="mb-3" />
          </template>
          <VSelect
            v-model="crmForm.owner_user_id"
            :items="[{ title: 'Unassigned', value: null }, ...assignableUsers.map(u => ({ title: u.full_name, value: u.id }))]"
            label="Owner"
            density="compact"
            class="mb-3"
          />
          <VTextarea
            v-model="crmForm.notes"
            label="Notes"
            placeholder="Anything worth capturing from this conversation"
            rows="3"
            density="compact"
            class="mb-3"
          />
          <div class="d-flex justify-end ga-3">
            <VBtn variant="text" @click="closeCrmForm">
              Cancel
            </VBtn>
            <VBtn :loading="crmFormSubmitting" @click="submitCrmForm">
              Create {{ crmForm.mode }}
            </VBtn>
          </div>
        </VCardText>

        <VExpansionPanels v-else variant="accordion" multiple :model-value="['details']">
          <VExpansionPanel value="details" title="Contact details">
            <template #text>
              <p class="text-caption text-medium-emphasis mb-0">
                Since
              </p>
              <p class="mb-3" style="word-break: break-word;">
                {{ formatTime(activeConversation.contact.created_at) }}
              </p>
              <VSwitch
                :model-value="activeConversation.contact.opted_out"
                label="Opted out of WhatsApp"
                color="error"
                density="compact"
                hide-details
                @update:model-value="toggleOptedOut"
              />
            </template>
          </VExpansionPanel>

          <VExpansionPanel value="labels" title="Labels">
            <template #text>
              <div class="d-flex align-center justify-space-between mb-2">
                <span class="text-body-2 text-medium-emphasis">Conversation</span>
                <VBtn size="x-small" variant="text" icon="tabler-plus" @click="openNewLabelDialog('conversation')" />
              </div>
              <div class="d-flex flex-wrap ga-2 mb-4">
                <VChip
                  v-for="label in conversationLabels"
                  :key="label.id"
                  size="small"
                  :color="label.color"
                  :variant="activeConversation.labels.some(l => l.id === label.id) ? 'flat' : 'outlined'"
                  @click="toggleConversationLabel(label)"
                >
                  {{ label.name }}
                </VChip>
              </div>
              <div class="d-flex align-center justify-space-between mb-2">
                <span class="text-body-2 text-medium-emphasis">Contact</span>
                <VBtn size="x-small" variant="text" icon="tabler-plus" @click="openNewLabelDialog('contact')" />
              </div>
              <div class="d-flex flex-wrap ga-2">
                <VChip
                  v-for="label in contactLabels"
                  :key="label.id"
                  size="small"
                  :color="label.color"
                  :variant="activeConversation.contact.labels.some(l => l.id === label.id) ? 'flat' : 'outlined'"
                  @click="toggleContactLabel(label)"
                >
                  {{ label.name }}
                </VChip>
              </div>
            </template>
          </VExpansionPanel>

          <VExpansionPanel value="custom-fields" title="Custom fields">
            <template #text>
              <VAlert v-if="customFieldsError" type="error" variant="tonal" density="compact" class="mb-2">
                {{ customFieldsError }}
              </VAlert>
              <VTable density="compact" class="mb-2">
                <tbody>
                  <tr v-for="(value, key) in activeConversation.contact.custom_attributes" :key="key">
                    <td class="text-medium-emphasis" style="word-break: break-word;">
                      {{ key }}
                    </td>
                    <td style="word-break: break-word;">
                      {{ value }}
                    </td>
                    <td>
                      <VBtn size="x-small" variant="text" icon="tabler-trash" @click="removeCustomField(String(key))" />
                    </td>
                  </tr>
                </tbody>
              </VTable>
              <div class="d-flex ga-2">
                <VTextField v-model="newFieldKey" placeholder="Field" density="compact" variant="outlined" hide-details />
                <VTextField v-model="newFieldValue" placeholder="Value" density="compact" variant="outlined" hide-details @keydown.enter="addCustomField" />
                <VBtn size="small" icon="tabler-plus" @click="addCustomField" />
              </div>
            </template>
          </VExpansionPanel>
        </VExpansionPanels>
      </VCard>
    </VCol>
  </VRow>

  <VDialog v-model="newLabelDialog" max-width="420">
    <VCard>
      <VCardTitle>New {{ newLabelScope }} label</VCardTitle>
      <VCardText>
        <VAlert v-if="newLabelError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ newLabelError }}
        </VAlert>
        <AppTextField v-model="newLabelName" label="Label name" @keydown.enter="createLabel" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" :disabled="creatingLabel" @click="newLabelDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="creatingLabel" :disabled="creatingLabel" @click="createLabel">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="templateDialog" max-width="560">
    <VCard>
      <VCardTitle>Send a template message</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Required once Meta's 24-hour free-form messaging window has closed for this contact.
        </p>
        <VAlert v-if="templateError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ templateError }}
        </VAlert>
        <VProgressLinear v-if="templateLoading" indeterminate class="mb-3" />

        <template v-if="!selectedTemplate">
          <p v-if="!templateLoading && !templates.length" class="text-medium-emphasis">
            No templates found on this WhatsApp account.
          </p>
          <VList density="compact">
            <VListItem
              v-for="template in templates"
              :key="template.name + template.language"
              :disabled="template.status !== 'APPROVED'"
              @click="selectTemplate(template)"
            >
              <VListItemTitle>
                {{ template.name }}
                <VChip size="x-small" :color="template.status === 'APPROVED' ? 'success' : 'warning'" class="ml-2">
                  {{ template.status }}
                </VChip>
              </VListItemTitle>
              <VListItemSubtitle>{{ template.body }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </template>

        <template v-else>
          <VBtn size="small" variant="text" prepend-icon="tabler-arrow-left" class="mb-3" @click="selectedTemplate = null">
            Back
          </VBtn>
          <VTextField
            v-for="(_, i) in templateParamValues"
            :key="i"
            v-model="templateParamValues[i]"
            :label="`Variable {{${i + 1}}}`"
            density="compact"
            variant="outlined"
            class="mb-2"
          />
          <p class="text-caption text-medium-emphasis mb-1">
            Preview
          </p>
          <p class="mb-4" style="white-space: pre-wrap;">
            {{ templatePreview }}
          </p>
          <VBtn :loading="templateSending" @click="sendTemplate">
            Send template
          </VBtn>
        </template>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="newConversationDialog" max-width="560">
    <VCard>
      <VCardTitle>New conversation</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Starting a conversation with someone who's never messaged in requires an approved
          template -- WhatsApp doesn't allow a free-form first message.
        </p>
        <VAlert v-if="newConversationError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ newConversationError }}
        </VAlert>
        <VTextField v-model="newConversationForm.wa_id" label="WhatsApp number" placeholder="91XXXXXXXXXX" density="compact" variant="outlined" class="mb-2" />
        <VTextField v-model="newConversationForm.name" label="Contact name (optional)" density="compact" variant="outlined" class="mb-4" />

        <VProgressLinear v-if="templateLoading" indeterminate class="mb-3" />

        <template v-if="!newConvSelectedTemplate">
          <p v-if="!templateLoading && !templates.length" class="text-medium-emphasis">
            No templates found on this WhatsApp account.
          </p>
          <VList density="compact">
            <VListItem
              v-for="template in templates"
              :key="template.name + template.language"
              :disabled="template.status !== 'APPROVED'"
              @click="selectNewConvTemplate(template)"
            >
              <VListItemTitle>
                {{ template.name }}
                <VChip size="x-small" :color="template.status === 'APPROVED' ? 'success' : 'warning'" class="ml-2">
                  {{ template.status }}
                </VChip>
              </VListItemTitle>
              <VListItemSubtitle>{{ template.body }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </template>

        <template v-else>
          <VBtn size="small" variant="text" prepend-icon="tabler-arrow-left" class="mb-3" @click="newConvSelectedTemplate = null">
            Back
          </VBtn>
          <VTextField
            v-for="(_, i) in newConvParamValues"
            :key="i"
            v-model="newConvParamValues[i]"
            :label="`Variable {{${i + 1}}}`"
            density="compact"
            variant="outlined"
            class="mb-2"
          />
          <p class="text-caption text-medium-emphasis mb-1">
            Preview
          </p>
          <p class="mb-4" style="white-space: pre-wrap;">
            {{ newConvPreview }}
          </p>
          <VBtn :loading="newConversationSending" :disabled="!newConversationForm.wa_id.trim()" @click="sendNewConversation">
            Start conversation
          </VBtn>
        </template>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="locationDialog" max-width="420">
    <VCard>
      <VCardTitle>Send a location</VCardTitle>
      <VCardText>
        <VAlert v-if="locationError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ locationError }}
        </VAlert>
        <VRow>
          <VCol cols="6">
            <AppTextField v-model="locationForm.latitude" label="Latitude" placeholder="12.9716" />
          </VCol>
          <VCol cols="6">
            <AppTextField v-model="locationForm.longitude" label="Longitude" placeholder="77.5946" />
          </VCol>
        </VRow>
        <AppTextField v-model="locationForm.name" label="Place name (optional)" class="mb-3" />
        <AppTextField v-model="locationForm.address" label="Address (optional)" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="locationDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="locationSending" @click="sendLocation">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="productDialog" max-width="460">
    <VCard>
      <VCardTitle>Send a product</VCardTitle>
      <VCardText>
        <VAlert v-if="productError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ productError }}
        </VAlert>
        <AppTextField v-model="catalogSearch" label="Search your catalog" prepend-inner-icon="tabler-search" class="mb-2" />
        <VProgressLinear v-if="catalogLoading" indeterminate color="primary" class="mb-2" />
        <VList v-else density="compact" class="mb-3" style="max-height: 220px; overflow-y: auto;">
          <VListItem
            v-for="item in catalogItems" :key="item.id" :active="productForm.product_retailer_id === item.product_retailer_id"
            @click="pickProduct(item)"
          >
            <template #prepend>
              <VAvatar v-if="item.image_url" :image="item.image_url" size="32" rounded />
              <VAvatar v-else size="32" rounded color="secondary" variant="tonal">
                <VIcon icon="tabler-shopping-bag" size="16" />
              </VAvatar>
            </template>
            <VListItemTitle>{{ item.name }}</VListItemTitle>
            <VListItemSubtitle>{{ item.product_retailer_id }}<span v-if="item.price"> &middot; {{ item.price }} {{ item.currency }}</span></VListItemSubtitle>
          </VListItem>
          <VListItem v-if="!catalogItems.length" title="No products found -- sync your catalog in Manage WhatsApp, or enter an ID below." />
        </VList>
        <AppTextField v-model="productForm.product_retailer_id" label="Product ID" class="mb-3" />
        <AppTextField v-model="productForm.body_text" label="Message (optional)" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="productDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="productSending" @click="sendProduct">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="productListDialog" max-width="500">
    <VCard>
      <VCardTitle>Send a product list</VCardTitle>
      <VCardText>
        <VAlert v-if="productListError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ productListError }}
        </VAlert>
        <AppTextField v-model="productListForm.header_text" label="Header" class="mb-3" />
        <AppTextField v-model="productListForm.body_text" label="Message" class="mb-3" />
        <AppTextField v-model="catalogSearch" label="Search your catalog" prepend-inner-icon="tabler-search" class="mb-2" />
        <VProgressLinear v-if="catalogLoading" indeterminate color="primary" class="mb-2" />
        <VList v-else density="compact" class="mb-2" style="max-height: 220px; overflow-y: auto;">
          <VListItem
            v-for="item in catalogItems" :key="item.id"
            :active="productListSelection.some(p => p.product_retailer_id === item.product_retailer_id)"
            @click="toggleProductListItem(item)"
          >
            <template #prepend>
              <VCheckboxBtn :model-value="productListSelection.some(p => p.product_retailer_id === item.product_retailer_id)" readonly />
            </template>
            <VListItemTitle>{{ item.name }}</VListItemTitle>
            <VListItemSubtitle>{{ item.product_retailer_id }}<span v-if="item.price"> &middot; {{ item.price }} {{ item.currency }}</span></VListItemSubtitle>
          </VListItem>
          <VListItem v-if="!catalogItems.length" title="No products found -- sync your catalog in Manage WhatsApp." />
        </VList>
        <p class="text-caption text-medium-emphasis mb-0">
          {{ productListSelection.length }} selected (up to 30)
        </p>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="productListDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="productListSending" @click="sendProductList">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="contactDialog" max-width="420">
    <VCard>
      <VCardTitle>Send a contact card</VCardTitle>
      <VCardText>
        <VAlert v-if="contactError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ contactError }}
        </VAlert>
        <AppTextField v-model="contactForm.formatted_name" label="Name" class="mb-3" />
        <AppTextField v-model="contactForm.phone" label="Phone (with country code)" placeholder="919999999999" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="contactDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="contactSending" @click="sendContactCard">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="buttonsDialog" max-width="480">
    <VCard>
      <VCardTitle>Quick-reply buttons</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Up to 3 buttons the customer can tap to reply.
        </p>
        <VAlert v-if="buttonsError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ buttonsError }}
        </VAlert>
        <VTextarea v-model="buttonsForm.body_text" label="Message" rows="2" class="mb-3" />
        <div v-for="(_, i) in buttonsForm.button_labels" :key="i" class="d-flex align-center ga-2 mb-2">
          <AppTextField v-model="buttonsForm.button_labels[i]" :label="`Button ${i + 1}`" :maxlength="20" />
          <VBtn v-if="buttonsForm.button_labels.length > 1" size="small" variant="text" icon="tabler-trash" @click="buttonsForm.button_labels.splice(i, 1)" />
        </div>
        <VBtn v-if="buttonsForm.button_labels.length < 3" size="small" variant="text" prepend-icon="tabler-plus" @click="buttonsForm.button_labels.push('')">
          Add button
        </VBtn>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="buttonsDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="buttonsSending" @click="sendInteractiveButtons">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="listDialog" max-width="480">
    <VCard>
      <VCardTitle>List message</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Up to 10 options the customer picks from a menu.
        </p>
        <VAlert v-if="listError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ listError }}
        </VAlert>
        <VTextarea v-model="listForm.body_text" label="Message" rows="2" class="mb-3" />
        <AppTextField v-model="listForm.button_label" label="Menu button label" :maxlength="20" class="mb-3" />
        <div v-for="(row, i) in listForm.rows" :key="i" class="d-flex align-center ga-2 mb-2">
          <AppTextField v-model="row.title" :label="`Option ${i + 1}`" :maxlength="24" />
          <AppTextField v-model="row.description" label="Description (optional)" :maxlength="72" />
          <VBtn v-if="listForm.rows.length > 1" size="small" variant="text" icon="tabler-trash" @click="listForm.rows.splice(i, 1)" />
        </div>
        <VBtn v-if="listForm.rows.length < 10" size="small" variant="text" prepend-icon="tabler-plus" @click="listForm.rows.push({ title: '', description: '' })">
          Add option
        </VBtn>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="listDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="listSending" @click="sendInteractiveList">
          Send
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="crmUpsellDialog" max-width="420">
    <VCard>
      <VCardTitle>Upgrade to CRM</VCardTitle>
      <VCardText>
        Converting conversations to tickets, leads, and customers requires the CRM channel.
        Subscribe to it from the Channels page to unlock this.
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="crmUpsellDialog = false">
          Not now
        </VBtn>
        <VBtn @click="crmUpsellDialog = false; router.push('/channels')">
          Go to Channels
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>

<style>
/* Neutralizes the global "boxed" max-width specifically on this page -- see the comment on
   layoutWrapperClasses above. Not scoped: .layout-page-content lives in the shared layout shell,
   outside this component's own DOM tree, so a scoped style could never reach it. */
.layout-content-width-fluid.layout-content-width-boxed .layout-page-content {
  max-inline-size: none !important;
  /* The 1.5rem side padding here is unconditional in the shared layout (applied in both boxed
     and fluid mode -- see @layouts/styles/_placeholders.scss's %boxed-content-spacing), so even
     with the max-width removed above, ~24px per side was still going unused on an already
     space-constrained 3-pane view. Confirmed live: reported as visible dead space on both edges
     at a real 13" laptop width. 12px exactly matches VRow's own default -12px gutter margin --
     going any lower makes the row bleed out past this container's edge, underneath the nav
     sidebar (confirmed live: 8px caused a visible 4px overlap). */
  padding-inline: 12px !important;
}
</style>

<style scoped>
.message-react-btn {
  opacity: 0;
  transition: opacity 0.15s;
}
.message-row:hover .message-react-btn {
  opacity: 1;
}
</style>
