<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    layoutWrapperClasses: 'layout-content-width-fluid',
  },
})

type Contact = { id: string, name: string | null, email: string | null }
type Message = {
  id: string
  direction: 'inbound' | 'outbound'
  message_type: string
  body: string | null
  media_url: string | null
  created_at: string
}
type Thread = {
  id: string
  contact: Contact
  status: string
  unread: boolean
  last_message_preview: string | null
  last_message_at: string | null
  created_at: string
}
type ThreadDetail = Thread & { messages: Message[] }
type Telemetry = {
  current_url: string | null
  referrer: string | null
  user_agent: string | null
  country: string | null
  city: string | null
  pages_viewed: { url: string, viewed_at: string }[]
  started_at: string
  last_seen_at: string
}

const threads = ref<Thread[]>([])
const loading = ref(false)
const loadError = ref('')

function contactLabel(c: Contact) {
  return c.name || c.email || 'Website visitor'
}

async function loadThreads() {
  loading.value = true
  loadError.value = ''
  try {
    threads.value = await $api<Thread[]>('/v1/waba/conversations', { params: { channel: 'webchat', limit: 100 } })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load website chat conversations.')
  }
  finally {
    loading.value = false
  }
}

const selected = ref<ThreadDetail | null>(null)
const threadLoading = ref(false)
const threadError = ref('')

async function selectThread(id: string) {
  threadLoading.value = true
  threadError.value = ''
  try {
    selected.value = await $api<ThreadDetail>(`/v1/waba/conversations/${id}`)
    loadTelemetry(id)
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

// --- Telemetry panel ---------------------------------------------------------------------------

const telemetry = ref<Telemetry | null>(null)
const telemetryLoading = ref(false)

async function loadTelemetry(conversationId: string) {
  telemetry.value = null
  telemetryLoading.value = true
  try {
    telemetry.value = await $api<Telemetry>(`/v1/webchat/visits/${conversationId}`)
  }
  catch {
    // No telemetry recorded (or the widget was never actually loaded for this contact) --
    // the panel just shows nothing, not an error, since this is a nicety, not a hard dependency.
  }
  finally {
    telemetryLoading.value = false
  }
}

function browserFromUserAgent(ua: string | null) {
  if (!ua)
    return null
  if (ua.includes('Edg/'))
    return 'Edge'
  if (ua.includes('Chrome/'))
    return 'Chrome'
  if (ua.includes('Firefox/'))
    return 'Firefox'
  if (ua.includes('Safari/'))
    return 'Safari'
  return 'Unknown browser'
}

// --- Reply ---------------------------------------------------------------------------------

const replyBody = ref('')
const sending = ref(false)
const sendError = ref('')

watch(selected, () => { replyBody.value = '' })

async function sendReply() {
  if (!selected.value || !replyBody.value.trim())
    return
  sending.value = true
  sendError.value = ''
  const body = replyBody.value.trim()
  try {
    const message = await $api<Message>(`/v1/waba/conversations/${selected.value.id}/messages`, { method: 'POST', body: { body } })
    if (!selected.value.messages.some(m => m.id === message.id))
      selected.value.messages.push(message)
    replyBody.value = ''
    loadThreads()
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send this reply.')
  }
  finally {
    sending.value = false
  }
}

// --- Attachments -----------------------------------------------------------------------------

const fileInput = ref<HTMLInputElement | null>(null)
const uploadingFile = ref(false)

function triggerFilePicker() {
  fileInput.value?.click()
}

async function onFileSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file || !selected.value)
    return
  sendError.value = ''
  uploadingFile.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const message = await $api<Message>(`/v1/waba/conversations/${selected.value.id}/media`, { method: 'POST', body: formData })
    if (!selected.value.messages.some(m => m.id === message.id))
      selected.value.messages.push(message)
    loadThreads()
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send this file.')
  }
  finally {
    uploadingFile.value = false
    if (fileInput.value)
      fileInput.value.value = ''
  }
}

function mediaUrl(messageId: string): string {
  const base = import.meta.env.VITE_API_BASE_URL || window.location.origin
  const token = useCookie('accessToken').value
  return `${base}/v1/waba/media/${messageId}?token=${encodeURIComponent(token || '')}`
}

function formatDate(iso: string | null) {
  if (!iso)
    return ''
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// --- Macros + resolve ------------------------------------------------------------------------

type Macro = { id: string, name: string }

const macros = ref<Macro[]>([])
const runningMacro = ref(false)
const resolving = ref(false)

async function loadMacros() {
  try {
    macros.value = await $api<Macro[]>('/v1/waba/macros')
  }
  catch {
    // Non-critical -- the macro menu just shows empty if this fails.
  }
}

async function runMacro(macroId: string) {
  if (!selected.value)
    return
  runningMacro.value = true
  try {
    await $api(`/v1/waba/conversations/${selected.value.id}/run-macro/${macroId}`, { method: 'POST' })
    await selectThread(selected.value.id)
    await loadThreads()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not run this macro.')
  }
  finally {
    runningMacro.value = false
  }
}

async function markResolved() {
  if (!selected.value)
    return
  resolving.value = true
  try {
    await $api(`/v1/waba/conversations/${selected.value.id}`, { method: 'PUT', body: { status: 'resolved' } })
    selected.value.status = 'resolved'
    await loadThreads()
  }
  catch (error: any) {
    threadError.value = extractErrorMessage(error, 'Could not resolve this conversation.')
  }
  finally {
    resolving.value = false
  }
}

// --- Realtime: same WebSocket + Redis pub/sub feed inbox.vue uses -- a webchat conversation's
// messages are published onto the same per-entity channel, so this reuses the exact connection
// shape, just its own tab/socket instance.
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
        const message = payload.message as Message & { conversation_id: string }
        if (selected.value?.id === message.conversation_id && !selected.value.messages.some(m => m.id === message.id))
          selected.value.messages.push(message)
        loadThreads()
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

onMounted(() => {
  loadThreads()
  loadMacros()
  connectSocket()
})

onBeforeUnmount(() => {
  if (reconnectTimeout)
    clearTimeout(reconnectTimeout)
  socket?.close()
})
</script>

<template>
  <h1 class="text-h4 mb-4">
    Website Chat
  </h1>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <div class="d-flex ga-4" style="min-height: 72vh;">
    <VCard class="d-flex flex-column" style="min-inline-size: 300px; max-inline-size: 300px;">
      <div style="flex: 1; overflow-y: auto;">
        <VList density="compact" lines="two">
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
              {{ thread.last_message_preview || '' }}
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
          No website chat conversations yet.
        </p>
      </div>
    </VCard>

    <VCard v-if="!selected" class="flex-grow-1 d-flex align-center justify-center">
      <p class="text-medium-emphasis">
        Select a conversation to view it.
      </p>
    </VCard>
    <template v-else>
      <VCard class="flex-grow-1 d-flex flex-column overflow-hidden">
        <VCardText class="flex-grow-0 d-flex align-start justify-space-between ga-2">
          <div>
            <h2 class="text-h6 mb-0">
              {{ contactLabel(selected.contact) }}
            </h2>
            <p v-if="selected.contact.email" class="text-body-2 text-medium-emphasis mb-0">
              {{ selected.contact.email }}
            </p>
          </div>
          <div class="d-flex align-center ga-2">
            <VMenu v-if="macros.length">
              <template #activator="{ props: menuProps }">
                <VBtn v-bind="menuProps" size="small" variant="outlined" :loading="runningMacro">
                  Macros
                </VBtn>
              </template>
              <VList density="compact">
                <VListItem v-for="macro in macros" :key="macro.id" @click="runMacro(macro.id)">
                  {{ macro.name }}
                </VListItem>
              </VList>
            </VMenu>
            <VBtn
              v-if="selected.status !== 'resolved'"
              size="small"
              variant="outlined"
              color="success"
              :loading="resolving"
              @click="markResolved"
            >
              Mark resolved
            </VBtn>
            <VChip v-else color="success" size="small" variant="tonal">
              Resolved
            </VChip>
          </div>
        </VCardText>
        <VDivider />

        <VAlert v-if="threadError" type="error" variant="tonal" density="compact" class="ma-3">
          {{ threadError }}
        </VAlert>

        <div class="flex-grow-1 overflow-y-auto pa-4">
          <div v-for="m in selected.messages" :key="m.id" class="d-flex mb-3" :class="m.direction === 'outbound' ? 'justify-end' : 'justify-start'">
            <div
              class="pa-3 rounded-lg"
              :style="{
                maxWidth: '75%',
                padding: m.message_type === 'image' && m.media_url ? '4px' : undefined,
                background: m.direction === 'outbound' ? 'rgb(var(--v-theme-primary))' : 'rgba(var(--v-theme-on-surface), 0.06)',
                color: m.direction === 'outbound' ? '#fff' : 'inherit',
              }"
            >
              <a v-if="m.message_type === 'image' && m.media_url" :href="mediaUrl(m.id)" target="_blank">
                <img :src="mediaUrl(m.id)" style="max-width: 100%; border-radius: 6px; display: block;">
              </a>
              <a
                v-else-if="m.media_url"
                :href="mediaUrl(m.id)"
                target="_blank"
                class="d-flex align-center ga-2 mb-1"
                :class="m.direction === 'outbound' ? 'text-white' : ''"
              >
                <VIcon icon="tabler-file" size="18" />
                Download file
              </a>
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div v-if="m.body" class="mb-1 webchat-rich-body" v-html="m.body" />
              <p class="text-caption mb-0" :class="m.direction === 'outbound' ? 'text-white' : 'text-medium-emphasis'" style="opacity: 0.75;">
                {{ formatDate(m.created_at) }}
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
          <input ref="fileInput" type="file" hidden @change="onFileSelected">
          <div class="d-flex align-end ga-2">
            <VBtn icon="tabler-paperclip" variant="outlined" :loading="uploadingFile" @click="triggerFilePicker" />
            <VCard variant="outlined" class="flex-grow-1">
              <TiptapEditor v-model="replyBody" placeholder="Type a reply..." />
            </VCard>
            <VBtn :loading="sending" :disabled="!replyBody.trim()" @click="sendReply">
              Send
            </VBtn>
          </div>
        </VCardText>
      </VCard>

      <VCard style="min-inline-size: 280px; max-inline-size: 280px;">
        <VCardText>
          <h3 class="text-subtitle-1 mb-3">
            Visitor details
          </h3>
          <VProgressLinear v-if="telemetryLoading" indeterminate color="primary" class="mb-3" />
          <template v-if="telemetry">
            <div class="mb-3">
              <p class="text-caption text-medium-emphasis mb-0">
                Current page
              </p>
              <p class="text-body-2 mb-0" style="word-break: break-all;">
                {{ telemetry.current_url || '—' }}
              </p>
            </div>
            <div class="mb-3">
              <p class="text-caption text-medium-emphasis mb-0">
                Referrer
              </p>
              <p class="text-body-2 mb-0" style="word-break: break-all;">
                {{ telemetry.referrer || 'Direct' }}
              </p>
            </div>
            <div class="mb-3">
              <p class="text-caption text-medium-emphasis mb-0">
                Browser
              </p>
              <p class="text-body-2 mb-0">
                {{ browserFromUserAgent(telemetry.user_agent) || '—' }}
              </p>
            </div>
            <div class="mb-3">
              <p class="text-caption text-medium-emphasis mb-0">
                Location
              </p>
              <p class="text-body-2 mb-0">
                {{ [telemetry.city, telemetry.country].filter(Boolean).join(', ') || 'Unknown' }}
              </p>
            </div>
            <div class="mb-1">
              <p class="text-caption text-medium-emphasis mb-1">
                Pages viewed this visit
              </p>
              <p v-for="(p, i) in telemetry.pages_viewed" :key="i" class="text-caption mb-1" style="word-break: break-all;">
                {{ p.url }}
              </p>
            </div>
          </template>
          <p v-else-if="!telemetryLoading" class="text-body-2 text-medium-emphasis mb-0">
            No telemetry recorded for this visitor.
          </p>
        </VCardText>
      </VCard>
    </template>
  </div>
</template>

<style scoped>
.webchat-rich-body :deep(p) {
  margin-block-end: 0;
}
.webchat-rich-body :deep(a) {
  color: inherit;
  text-decoration: underline;
}
</style>
