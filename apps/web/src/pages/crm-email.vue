<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    layoutWrapperClasses: 'layout-content-width-fluid',
    channel: 'crm',
  },
})

import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type EmailAccountInfo = { connected: boolean, signature_html?: string | null }
type EmailAttachment = { filename: string, stored_path: string, content_type: string, size: number }
type EmailMessage = {
  id: string
  direction: 'inbound' | 'outbound'
  body: string | null
  payload: { subject?: string, is_html?: boolean, attachments?: EmailAttachment[] } | null
  created_at: string
}
type EmailThread = {
  id: string
  contact: Contact
  status: string
  unread: boolean
  last_message_preview: string | null
  last_message_direction: 'inbound' | 'outbound' | null
  last_message_at: string | null
  created_at: string
  is_ticket: boolean
  ticket_number: string | null
}
type EmailThreadDetail = EmailThread & { messages: EmailMessage[] }

const threads = ref<EmailThread[]>([])
const loading = ref(false)
const loadError = ref('')
const search = ref('')

function contactLabel(c: Contact) {
  return c.name || c.email || 'Unknown'
}

function subjectFor(thread: EmailThread) {
  return thread.last_message_preview || '(no subject)'
}

async function loadThreads() {
  loading.value = true
  loadError.value = ''
  try {
    const params: Record<string, string | number> = { channel: 'email', limit: 100 }
    if (search.value.trim())
      params.search = search.value.trim()
    threads.value = await $api<EmailThread[]>('/v1/waba/conversations', { params })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your inbox.')
  }
  finally {
    loading.value = false
  }
}

let searchDebounce: ReturnType<typeof setTimeout> | undefined
watch(search, () => {
  clearTimeout(searchDebounce)
  searchDebounce = setTimeout(loadThreads, 350)
})

// --- Selected thread -----------------------------------------------------------------------

const selected = ref<EmailThreadDetail | null>(null)
const threadLoading = ref(false)
const threadError = ref('')

function latestSubject(thread: EmailThreadDetail) {
  const withSubject = [...thread.messages].reverse().find(m => m.payload?.subject)
  return withSubject?.payload?.subject || '(no subject)'
}

// Real per-message flag, set by the backend at write time -- a message's direction alone doesn't
// determine this: a Microsoft Graph inbound message is HTML by default, and a plain-text-only
// sender's inbound message isn't, so this can't be inferred from direction. Messages stored
// before this flag existed have no payload.is_html at all (not false -- absent) -- for those,
// sniff the body itself: a real HTML document starts with a tag, not plain prose, so this is a
// safe, one-time fallback for old data rather than something new messages ever need to rely on.
function looksLikeHtml(body: string | null) {
  return !!body && /^\s*<(!doctype|html|body|table|div|p|span|h[1-6])[\s>]/i.test(body)
}

function isHtml(m: EmailMessage) {
  if (m.payload?.is_html !== undefined)
    return m.payload.is_html
  return m.direction === 'outbound' || looksLikeHtml(m.body)
}

function formatFileSize(bytes: number) {
  if (bytes < 1024)
    return `${bytes} B`
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const downloadingAttachment = ref<string | null>(null)

async function downloadAttachment(messageId: string, index: number, filename: string) {
  const key = `${messageId}:${index}`
  downloadingAttachment.value = key
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/email/messages/${messageId}/attachments/${index}`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  }
  catch {
    // A failed download isn't worth a dedicated error banner here -- the chip stops spinning,
    // the user can just click again.
  }
  finally {
    downloadingAttachment.value = null
  }
}

async function selectThread(id: string) {
  threadLoading.value = true
  threadError.value = ''
  try {
    selected.value = await $api<EmailThreadDetail>(`/v1/waba/conversations/${id}`)
    $api(`/v1/waba/conversations/${id}/read`, { method: 'POST' })
      .then(() => {
        const item = threads.value.find(t => t.id === id)
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

const convertingToTicket = ref(false)

async function convertToTicket() {
  if (!selected.value)
    return
  convertingToTicket.value = true
  try {
    const updated = await $api<EmailThread>(`/v1/waba/conversations/${selected.value.id}/convert-to-ticket`, { method: 'POST' })
    selected.value.is_ticket = updated.is_ticket
    selected.value.ticket_number = updated.ticket_number
    const item = threads.value.find(t => t.id === selected.value!.id)
    if (item) {
      item.is_ticket = updated.is_ticket
      item.ticket_number = updated.ticket_number
    }
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not convert this email to a ticket.')
  }
  finally {
    convertingToTicket.value = false
  }
}

// --- Canned responses + quotes (shared by reply and compose) --------------------------------

type CannedResponse = { id: string, shortcut: string, body: string }
type Quote = { id: string, quote_number: string | null, deal_id: string }

const cannedResponses = ref<CannedResponse[]>([])
const quotes = ref<Quote[]>([])

const signatureHtml = ref('')

async function loadPickerData() {
  const [cannedResult, quoteResult, accountResult, mySignatureResult] = await Promise.all([
    $api<CannedResponse[]>('/v1/waba/canned-responses').catch(() => []),
    $api<Quote[]>('/v1/crm/quotes').catch(() => []),
    $api<EmailAccountInfo>('/v1/crm/email/account').catch(() => null),
    $api<{ signature_html: string | null }>('/v1/crm/email/my-signature').catch(() => null),
  ])
  cannedResponses.value = cannedResult
  quotes.value = quoteResult
  // Your own personal signature always wins over the shared mailbox's team-default one -- this
  // mailbox is used by the whole team, so each person's messages should carry their own name.
  signatureHtml.value = mySignatureResult?.signature_html || accountResult?.signature_html || ''
}

function withSignature(html: string) {
  if (!signatureHtml.value)
    return html
  return html ? `${html}<p></p>${signatureHtml.value}` : signatureHtml.value
}

function resolveCannedBody(canned: CannedResponse, contactName: string | null) {
  return canned.body.replaceAll('{{contact.name}}', contactName || '').replaceAll('{{agent.name}}', authStore.profile?.full_name || '')
}

// --- Reply -------------------------------------------------------------------------------------

const subject = ref('')
const body = ref('')
const cc = ref('')
const showCc = ref(false)
const replyFiles = ref<File[]>([])
const replyQuoteId = ref<string | null>(null)
const sending = ref(false)
const sendError = ref('')

watch(selected, (thread) => {
  subject.value = thread ? `Re: ${latestSubject(thread)}` : ''
  body.value = thread ? withSignature('') : ''
  cc.value = ''
  showCc.value = false
  replyFiles.value = []
  replyQuoteId.value = null
})

function onReplyFilesSelected(event: Event) {
  const picked = Array.from((event.target as HTMLInputElement).files || [])
  replyFiles.value.push(...picked)
  ;(event.target as HTMLInputElement).value = ''
}

function removeReplyFile(index: number) {
  replyFiles.value.splice(index, 1)
}

function insertCannedIntoReply(canned: CannedResponse) {
  body.value += (body.value ? '<p></p>' : '') + `<p>${resolveCannedBody(canned, selected.value?.contact ? contactLabel(selected.value.contact) : null)}</p>`
}

async function send() {
  if (!selected.value || !body.value.trim())
    return
  sending.value = true
  sendError.value = ''
  try {
    const formData = new FormData()
    formData.append('contact_id', selected.value.contact.id)
    formData.append('subject', subject.value.trim() || '(no subject)')
    formData.append('body', body.value)
    if (cc.value.trim())
      formData.append('cc', cc.value.trim())
    if (replyQuoteId.value)
      formData.append('quote_id', replyQuoteId.value)
    for (const file of replyFiles.value)
      formData.append('files', file)
    await $api('/v1/crm/email/send', { method: 'POST', body: formData })
    body.value = withSignature('')
    cc.value = ''
    showCc.value = false
    replyFiles.value = []
    replyQuoteId.value = null
    await selectThread(selected.value.id)
    await loadThreads()
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send this email.')
  }
  finally {
    sending.value = false
  }
}

// --- Compose (new email, not a reply) -----------------------------------------------------------

const composeDialog = ref(false)
const composeForm = reactive({ to_email: '', to_name: '', subject: '', body: '', cc: '' })
const composeShowCc = ref(false)
const composeFiles = ref<File[]>([])
const composeQuoteId = ref<string | null>(null)
const composeSending = ref(false)
const composeError = ref('')

function openCompose() {
  composeForm.to_email = ''
  composeForm.to_name = ''
  composeForm.subject = ''
  composeForm.body = withSignature('')
  composeForm.cc = ''
  composeShowCc.value = false
  composeFiles.value = []
  composeQuoteId.value = null
  composeError.value = ''
  composeDialog.value = true
}

function onComposeFilesSelected(event: Event) {
  const picked = Array.from((event.target as HTMLInputElement).files || [])
  composeFiles.value.push(...picked)
  ;(event.target as HTMLInputElement).value = ''
}

function removeComposeFile(index: number) {
  composeFiles.value.splice(index, 1)
}

function insertCannedIntoCompose(canned: CannedResponse) {
  composeForm.body += (composeForm.body ? '<p></p>' : '') + `<p>${resolveCannedBody(canned, composeForm.to_name || null)}</p>`
}

async function sendCompose() {
  if (!composeForm.to_email.trim() || !composeForm.subject.trim() || !composeForm.body.trim())
    return
  composeSending.value = true
  composeError.value = ''
  try {
    const formData = new FormData()
    formData.append('to_email', composeForm.to_email.trim())
    if (composeForm.to_name.trim())
      formData.append('to_name', composeForm.to_name.trim())
    formData.append('subject', composeForm.subject.trim())
    formData.append('body', composeForm.body)
    if (composeForm.cc.trim())
      formData.append('cc', composeForm.cc.trim())
    if (composeQuoteId.value)
      formData.append('quote_id', composeQuoteId.value)
    for (const file of composeFiles.value)
      formData.append('files', file)
    const result = await $api<{ sent: boolean, conversation_id: string }>('/v1/crm/email/send', { method: 'POST', body: formData })
    composeDialog.value = false
    await loadThreads()
    await selectThread(result.conversation_id)
  }
  catch (error: any) {
    composeError.value = extractErrorMessage(error, 'Could not send this email.')
  }
  finally {
    composeSending.value = false
  }
}

// --- My signature (also editable here, not just in Manage CRM > Channels, so a teammate
// without settings access can still set their own) ------------------------------------------

const signatureDialog = ref(false)
const signatureDraft = ref('')
const signatureSaving = ref(false)
const signatureError = ref('')

function openSignatureDialog() {
  signatureDraft.value = signatureHtml.value
  signatureError.value = ''
  signatureDialog.value = true
}

async function saveSignature() {
  signatureSaving.value = true
  signatureError.value = ''
  try {
    const result = await $api<{ signature_html: string | null }>('/v1/crm/email/my-signature', { method: 'PUT', body: { signature_html: signatureDraft.value } })
    signatureHtml.value = result.signature_html || ''
    signatureDialog.value = false
  }
  catch (error: any) {
    signatureError.value = extractErrorMessage(error, 'Could not save your signature.')
  }
  finally {
    signatureSaving.value = false
  }
}

function formatDate(iso: string | null) {
  if (!iso)
    return ''
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

onMounted(() => {
  loadThreads()
  loadPickerData()
})
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-4">
    <h1 class="text-h4 mb-0">
      Email
    </h1>
    <div class="d-flex ga-2">
      <VBtn variant="tonal" prepend-icon="tabler-signature" @click="openSignatureDialog">
        My signature
      </VBtn>
      <VBtn color="primary" prepend-icon="tabler-pencil" @click="openCompose">
        Compose
      </VBtn>
    </div>
  </div>

  <VDialog v-model="signatureDialog" max-width="640">
    <VCard title="My signature">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="signatureDialog = false" />
      </template>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-3">
          This mailbox is shared by your team -- this signature is yours alone and is added automatically to replies and messages you compose.
        </p>
        <VAlert v-if="signatureError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ signatureError }}
        </VAlert>
        <VCard variant="outlined">
          <TiptapEditor v-model="signatureDraft" placeholder="e.g. Regards, Your Name, Your Title" allow-image />
        </VCard>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="signatureDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="signatureSaving" @click="saveSignature">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <div class="d-flex ga-4" style="min-height: 72vh;">
    <VCard class="d-flex flex-column" style="min-inline-size: 340px; max-inline-size: 340px;">
      <VCardText class="pb-2 flex-grow-0">
        <VTextField v-model="search" placeholder="Search email" density="compact" prepend-inner-icon="tabler-search" hide-details clearable />
      </VCardText>
      <VDivider />
      <div style="flex: 1; overflow-y: auto;">
        <VList density="compact" lines="three">
          <VListItem
            v-for="thread in threads" :key="thread.id"
            :active="selected?.id === thread.id"
            @click="selectThread(thread.id)"
          >
            <template #prepend>
              <VAvatar color="primary" variant="tonal" size="36">
                <span class="text-caption">{{ contactLabel(thread.contact).slice(0, 1).toUpperCase() }}</span>
              </VAvatar>
            </template>
            <VListItemTitle :class="thread.unread ? 'font-weight-bold' : 'font-weight-medium'">
              {{ contactLabel(thread.contact) }}
            </VListItemTitle>
            <VListItemSubtitle :class="thread.unread ? 'font-weight-medium text-high-emphasis' : ''">
              <VIcon
                v-if="thread.last_message_direction"
                :icon="thread.last_message_direction === 'outbound' ? 'tabler-arrow-up-right' : 'tabler-arrow-down-left'"
                :color="thread.last_message_direction === 'outbound' ? 'primary' : 'success'"
                size="12" class="me-1"
              />
              {{ subjectFor(thread) }}
            </VListItemSubtitle>
            <template #append>
              <div class="d-flex flex-column align-end ga-1">
                <span class="text-caption text-medium-emphasis">{{ formatDate(thread.last_message_at || thread.created_at) }}</span>
                <VIcon v-if="thread.unread" icon="tabler-circle-filled" color="primary" size="8" />
              </div>
            </template>
          </VListItem>
        </VList>
        <p v-if="!loading && !threads.length" class="text-medium-emphasis text-center pa-6 mb-0">
          No email yet. Connect a mailbox from Manage CRM's Channels tab.
        </p>
      </div>
    </VCard>

    <VCard v-if="!selected" class="flex-grow-1 d-flex align-center justify-center">
      <p class="text-medium-emphasis">
        Select an email to read it.
      </p>
    </VCard>
    <VCard v-else class="flex-grow-1 d-flex flex-column overflow-hidden">
      <VCardText class="flex-grow-0 d-flex align-start justify-space-between ga-2">
        <div>
          <h2 class="text-h6 mb-1">
            {{ latestSubject(selected) }}
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-0">
            {{ contactLabel(selected.contact) }} · {{ selected.contact.email }}
          </p>
        </div>
        <VChip v-if="selected.is_ticket" color="primary" variant="tonal" size="small">
          {{ selected.ticket_number }}
        </VChip>
        <VBtn v-else size="small" variant="outlined" prepend-icon="tabler-ticket" :loading="convertingToTicket" @click="convertToTicket">
          Create ticket
        </VBtn>
      </VCardText>
      <VDivider />

      <VAlert v-if="threadError" type="error" variant="tonal" density="compact" class="ma-3">
        {{ threadError }}
      </VAlert>

      <div class="flex-grow-1 overflow-y-auto pa-4">
        <div
          v-for="m in selected.messages" :key="m.id" class="mb-4 pb-4 pa-3 rounded"
          :style="{
            borderBottom: '1px solid rgba(var(--v-theme-on-surface), 0.08)',
            borderInlineStart: `3px solid rgb(var(--v-theme-${m.direction === 'outbound' ? 'primary' : 'success'}))`,
            backgroundColor: m.direction === 'outbound' ? 'rgba(var(--v-theme-primary), 0.04)' : 'transparent',
          }"
        >
          <div class="d-flex align-center ga-2 mb-2">
            <VAvatar size="28" :color="m.direction === 'outbound' ? 'primary' : 'success'" variant="tonal">
              <span class="text-caption">{{ (m.direction === 'outbound' ? 'Y' : contactLabel(selected.contact)).slice(0, 1).toUpperCase() }}</span>
            </VAvatar>
            <div class="flex-grow-1">
              <div class="d-flex align-center ga-2">
                <span class="text-body-2 font-weight-medium">
                  {{ m.direction === 'outbound' ? 'You' : contactLabel(selected.contact) }}
                </span>
                <VChip size="x-small" :color="m.direction === 'outbound' ? 'primary' : 'success'" variant="tonal">
                  <VIcon :icon="m.direction === 'outbound' ? 'tabler-arrow-up-right' : 'tabler-arrow-down-left'" size="12" start />
                  {{ m.direction === 'outbound' ? 'Sent' : 'Received' }}
                </VChip>
              </div>
              <div class="text-caption text-medium-emphasis">
                {{ formatDate(m.created_at) }}
              </div>
            </div>
          </div>
          <div style="margin-inline-start: 36px;">
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div v-if="isHtml(m)" class="email-html-body" v-html="m.body" />
            <p v-else class="mb-0" style="white-space: pre-wrap;">
              {{ m.body }}
            </p>
            <div v-if="m.payload?.attachments?.length" class="d-flex flex-wrap gap-2 mt-3">
              <VChip
                v-for="(att, i) in m.payload.attachments" :key="i"
                variant="tonal" size="small" prepend-icon="tabler-paperclip"
                :disabled="downloadingAttachment === `${m.id}:${i}`"
                @click="downloadAttachment(m.id, i, att.filename)"
              >
                {{ att.filename }} <span class="text-caption text-medium-emphasis ms-1">({{ formatFileSize(att.size) }})</span>
              </VChip>
            </div>
          </div>
        </div>
        <p v-if="!threadLoading && !selected.messages.length" class="text-medium-emphasis text-center pa-6">
          No messages yet.
        </p>
      </div>
      <VDivider />
      <VCardText class="flex-grow-0">
        <VAlert v-if="sendError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ sendError }}
        </VAlert>
        <div class="d-flex align-center ga-2 mb-2">
          <VTextField v-model="subject" label="Subject" density="compact" hide-details class="flex-grow-1" />
          <VBtn v-if="!showCc" size="small" variant="text" @click="showCc = true">
            Cc
          </VBtn>
        </div>
        <VTextField v-if="showCc" v-model="cc" label="Cc" placeholder="comma-separated email addresses" density="compact" class="mb-2" clearable @click:clear="cc = ''" />
        <VCard variant="outlined">
          <TiptapEditor v-model="body" placeholder="Write your reply..." allow-image />
        </VCard>

        <div v-if="replyFiles.length || replyQuoteId" class="d-flex flex-wrap gap-2 mt-2">
          <VChip v-for="(file, i) in replyFiles" :key="i" closable size="small" @click:close="removeReplyFile(i)">
            {{ file.name }}
          </VChip>
          <VChip v-if="replyQuoteId" closable size="small" @click:close="replyQuoteId = null">
            Quote: {{ quotes.find(q => q.id === replyQuoteId)?.quote_number || replyQuoteId }}
          </VChip>
        </div>

        <div class="d-flex align-center justify-space-between mt-3">
          <div class="d-flex align-center ga-1">
            <VBtn icon="tabler-paperclip" variant="text" size="small" @click="($refs.replyFileInput as HTMLInputElement).click()" />
            <input ref="replyFileInput" type="file" multiple class="d-none" @change="onReplyFilesSelected">

            <VMenu v-if="quotes.length">
              <template #activator="{ props: menuProps }">
                <VBtn icon="tabler-file-invoice" variant="text" size="small" v-bind="menuProps" />
              </template>
              <VList density="compact">
                <VListItem v-for="q in quotes" :key="q.id" @click="replyQuoteId = q.id">
                  {{ q.quote_number || 'Draft quote' }}
                </VListItem>
              </VList>
            </VMenu>

            <VMenu v-if="cannedResponses.length">
              <template #activator="{ props: menuProps }">
                <VBtn icon="tabler-message-2-bolt" variant="text" size="small" v-bind="menuProps" />
              </template>
              <VList density="compact">
                <VListItem v-for="c in cannedResponses" :key="c.id" @click="insertCannedIntoReply(c)">
                  /{{ c.shortcut }}
                </VListItem>
              </VList>
            </VMenu>
          </div>
          <VBtn :loading="sending" :disabled="!body.trim()" @click="send">
            Send
          </VBtn>
        </div>
      </VCardText>
    </VCard>
  </div>

  <VDialog v-model="composeDialog" max-width="640" persistent>
    <VCard title="New email">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="composeDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-3">
        <VAlert v-if="composeError" type="error" variant="tonal" density="compact">
          {{ composeError }}
        </VAlert>
        <VTextField v-model="composeForm.to_email" label="To (email)" density="compact" autofocus />
        <VTextField v-model="composeForm.to_name" label="Recipient name (optional)" density="compact" />
        <div class="d-flex align-center ga-2">
          <VTextField v-model="composeForm.subject" label="Subject" density="compact" hide-details class="flex-grow-1" />
          <VBtn v-if="!composeShowCc" size="small" variant="text" @click="composeShowCc = true">
            Cc
          </VBtn>
        </div>
        <VTextField v-if="composeShowCc" v-model="composeForm.cc" label="Cc" placeholder="comma-separated email addresses" density="compact" clearable @click:clear="composeForm.cc = ''" />
        <VCard variant="outlined">
          <TiptapEditor v-model="composeForm.body" placeholder="Write your message..." allow-image />
        </VCard>

        <div v-if="composeFiles.length || composeQuoteId" class="d-flex flex-wrap gap-2">
          <VChip v-for="(file, i) in composeFiles" :key="i" closable size="small" @click:close="removeComposeFile(i)">
            {{ file.name }}
          </VChip>
          <VChip v-if="composeQuoteId" closable size="small" @click:close="composeQuoteId = null">
            Quote: {{ quotes.find(q => q.id === composeQuoteId)?.quote_number || composeQuoteId }}
          </VChip>
        </div>

        <div class="d-flex align-center ga-1">
          <VBtn icon="tabler-paperclip" variant="text" size="small" @click="($refs.composeFileInput as HTMLInputElement).click()" />
          <input ref="composeFileInput" type="file" multiple class="d-none" @change="onComposeFilesSelected">

          <VMenu v-if="quotes.length">
            <template #activator="{ props: menuProps }">
              <VBtn icon="tabler-file-invoice" variant="text" size="small" v-bind="menuProps" />
            </template>
            <VList density="compact">
              <VListItem v-for="q in quotes" :key="q.id" @click="composeQuoteId = q.id">
                {{ q.quote_number || 'Draft quote' }}
              </VListItem>
            </VList>
          </VMenu>

          <VMenu v-if="cannedResponses.length">
            <template #activator="{ props: menuProps }">
              <VBtn icon="tabler-message-2-bolt" variant="text" size="small" v-bind="menuProps" />
            </template>
            <VList density="compact">
              <VListItem v-for="c in cannedResponses" :key="c.id" @click="insertCannedIntoCompose(c)">
                /{{ c.shortcut }}
              </VListItem>
            </VList>
          </VMenu>
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="composeDialog = false">
          Cancel
        </VBtn>
        <VBtn
          color="primary" :loading="composeSending"
          :disabled="!composeForm.to_email.trim() || !composeForm.subject.trim() || !composeForm.body.trim()"
          @click="sendCompose"
        >
          Send
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.email-html-body {
  overflow-x: auto;
  max-inline-size: 100%;
  /* This app's own theme text color always wins, regardless of anything the sanitized HTML
     still carries -- the backend (services.sanitize_email_html) already strips inline
     color/background declarations from a real sender's HTML, this is a second-layer safety net
     so a color that slips through some other way never goes invisible against either theme. */
  color: rgb(var(--v-theme-on-surface));
}

.email-html-body :deep(*) {
  color: inherit !important;
  background-color: transparent !important;
}

.email-html-body :deep(p) {
  margin-block-end: 0.75rem;
}

.email-html-body :deep(img) {
  max-inline-size: 100%;
  block-size: auto;
}

.email-html-body :deep(table) {
  max-inline-size: 100%;
}
</style>
