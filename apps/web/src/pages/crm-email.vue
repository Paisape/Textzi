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
type EmailMessage = {
  id: string
  direction: 'inbound' | 'outbound'
  body: string | null
  payload: { subject?: string } | null
  created_at: string
}
type EmailThread = {
  id: string
  contact: Contact
  status: string
  unread: boolean
  last_message_preview: string | null
  last_message_at: string | null
  created_at: string
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

// Outbound messages are always HTML (sent from the rich-text editor below); inbound mail is
// always plain text (crm_email.py's _extract_body only ever stores text/plain) -- direction alone
// is enough to know how to render a message, no separate flag needed.
function isHtml(m: EmailMessage) {
  return m.direction === 'outbound'
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

// --- Canned responses + quotes (shared by reply and compose) --------------------------------

type CannedResponse = { id: string, shortcut: string, body: string }
type Quote = { id: string, quote_number: string | null, deal_id: string }

const cannedResponses = ref<CannedResponse[]>([])
const quotes = ref<Quote[]>([])

async function loadPickerData() {
  const [cannedResult, quoteResult] = await Promise.all([
    $api<CannedResponse[]>('/v1/waba/canned-responses').catch(() => []),
    $api<Quote[]>('/v1/crm/quotes').catch(() => []),
  ])
  cannedResponses.value = cannedResult
  quotes.value = quoteResult
}

function resolveCannedBody(canned: CannedResponse, contactName: string | null) {
  return canned.body.replaceAll('{{contact.name}}', contactName || '').replaceAll('{{agent.name}}', authStore.profile?.full_name || '')
}

// --- Reply -------------------------------------------------------------------------------------

const subject = ref('')
const body = ref('')
const replyFiles = ref<File[]>([])
const replyQuoteId = ref<string | null>(null)
const sending = ref(false)
const sendError = ref('')

watch(selected, (thread) => {
  subject.value = thread ? `Re: ${latestSubject(thread)}` : ''
  body.value = ''
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
    if (replyQuoteId.value)
      formData.append('quote_id', replyQuoteId.value)
    for (const file of replyFiles.value)
      formData.append('files', file)
    await $api('/v1/crm/email/send', { method: 'POST', body: formData })
    body.value = ''
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
const composeForm = reactive({ to_email: '', to_name: '', subject: '', body: '' })
const composeFiles = ref<File[]>([])
const composeQuoteId = ref<string | null>(null)
const composeSending = ref(false)
const composeError = ref('')

function openCompose() {
  composeForm.to_email = ''
  composeForm.to_name = ''
  composeForm.subject = ''
  composeForm.body = ''
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
    <VBtn color="primary" prepend-icon="tabler-pencil" @click="openCompose">
      Compose
    </VBtn>
  </div>

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
      <VCardText class="flex-grow-0">
        <h2 class="text-h6 mb-1">
          {{ latestSubject(selected) }}
        </h2>
        <p class="text-body-2 text-medium-emphasis mb-0">
          {{ contactLabel(selected.contact) }} · {{ selected.contact.email }}
        </p>
      </VCardText>
      <VDivider />

      <VAlert v-if="threadError" type="error" variant="tonal" density="compact" class="ma-3">
        {{ threadError }}
      </VAlert>

      <div class="flex-grow-1 overflow-y-auto pa-4">
        <div v-for="m in selected.messages" :key="m.id" class="mb-4 pb-4" style="border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.08);">
          <div class="d-flex align-center ga-2 mb-2">
            <VAvatar size="28" :color="m.direction === 'outbound' ? 'primary' : undefined" variant="tonal">
              <span class="text-caption">{{ (m.direction === 'outbound' ? 'Y' : contactLabel(selected.contact)).slice(0, 1).toUpperCase() }}</span>
            </VAvatar>
            <div>
              <div class="text-body-2 font-weight-medium">
                {{ m.direction === 'outbound' ? 'You' : contactLabel(selected.contact) }}
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
        <VTextField v-model="subject" label="Subject" density="compact" class="mb-2" />
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
        <VTextField v-model="composeForm.subject" label="Subject" density="compact" />
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
.email-html-body :deep(p) {
  margin-block-end: 0.75rem;
}
</style>
