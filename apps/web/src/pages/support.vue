<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
  },
})

// Textzi's own webchat widget key, reused as the in-app support channel -- same "Textzi acting as
// its own first customer" reasoning already established for the landing-page embed (index.vue).
// Not a secret, same as every other widget-key usage in this codebase.
const TEXTZI_SUPPORT_WIDGET_KEY = '35e05759-ac22-4102-acad-3bf4c3eb0c71'

type WebchatMessage = {
  id: string
  direction: 'inbound' | 'outbound'
  message_type: string
  body: string | null
  media_url: string | null
  status: string
  created_at: string
}

const authStore = useAuthStore()
const apiBase = computed(() => {
  const base = import.meta.env.VITE_API_BASE_URL || '/api'
  return base.startsWith('http') ? base : window.location.origin
})

// An opaque, unguessable per-user token -- NOT derived from authStore.profile.id, which is
// visible/derivable elsewhere and would let any other logged-in user read or post into this
// user's support conversation by passing it as visitor_id (webchat_public.py authorizes purely by
// visitor_id, correct for an anonymous website visitor's private client-generated UUID, unsafe for
// a value guessable from this user's own id). Fetched fresh each visit rather than cached, since
// it's cheap and avoids ever persisting it in localStorage/etc.
const visitorId = ref<string | null>(null)
const messages = ref<WebchatMessage[]>([])
const loadError = ref('')
const loading = ref(true)
const draft = ref('')
const sending = ref(false)
const sendError = ref('')
const messageListEl = ref<HTMLElement | null>(null)

function scrollToBottom() {
  nextTick(() => {
    if (messageListEl.value)
      messageListEl.value.scrollTop = messageListEl.value.scrollHeight
  })
}

async function ensureVisitorId() {
  if (visitorId.value)
    return
  const data = await $api<{ visitor_id: string }>('/v1/auth/support-visitor-token')
  visitorId.value = data.visitor_id
}

async function loadHistory() {
  loading.value = true
  loadError.value = ''
  try {
    await ensureVisitorId()
    const data = await $api<{ messages: WebchatMessage[] }>(`${apiBase.value}/v1/public/webchat/${TEXTZI_SUPPORT_WIDGET_KEY}/history`, {
      query: { visitor_id: visitorId.value },
    })
    messages.value = data.messages
    scrollToBottom()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load your support conversation.')
  }
  finally {
    loading.value = false
  }
}

async function onSend() {
  const body = draft.value.trim()
  if (!body || !visitorId.value)
    return
  sending.value = true
  sendError.value = ''
  try {
    await $api(`${apiBase.value}/v1/public/webchat/${TEXTZI_SUPPORT_WIDGET_KEY}/message`, {
      method: 'POST',
      body: {
        visitor_id: visitorId.value,
        body,
        name: authStore.profile?.full_name,
        email: authStore.profile?.email,
      },
    })
    draft.value = ''
    await loadHistory()
  }
  catch (error: any) {
    sendError.value = extractErrorMessage(error, 'Could not send your message.')
  }
  finally {
    sending.value = false
  }
}

let socket: WebSocket | null = null

function connectRealtime() {
  if (!visitorId.value)
    return
  const wsBase = apiBase.value.replace(/^http/, 'ws')
  socket = new WebSocket(`${wsBase}/v1/public/webchat/${TEXTZI_SUPPORT_WIDGET_KEY}/ws?visitor_id=${encodeURIComponent(visitorId.value)}`)
  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'message' && data.message)
        loadHistory()
    }
    catch {
      // ignore malformed frames
    }
  }
}

onMounted(async () => {
  await loadHistory()
  connectRealtime()
})

onUnmounted(() => {
  socket?.close()
})
</script>

<template>
  <div>
    <h1 class="text-h4 mb-1">
      Support
    </h1>
    <p class="text-medium-emphasis mb-6">
      Message the Textzi team directly. We typically reply within a few hours during business hours.
    </p>

    <VCard>
      <VCardText
        ref="messageListEl"
        class="support-thread"
      >
        <VAlert
          v-if="loadError"
          type="error"
          variant="tonal"
          class="mb-4"
        >
          {{ loadError }}
        </VAlert>

        <div
          v-if="!loading && !messages.length && !loadError"
          class="support-empty-state text-center text-medium-emphasis"
        >
          <VIcon
            icon="tabler-headset"
            size="40"
            class="mb-2"
          />
          <div>Send us a message to get started.</div>
        </div>

        <div
          v-for="message in messages"
          :key="message.id"
          class="support-message"
          :class="message.direction === 'outbound' ? 'support-message-agent' : 'support-message-you'"
        >
          <div class="support-message-bubble">
            {{ message.body }}
          </div>
          <div class="text-caption text-medium-emphasis mt-1">
            {{ message.direction === 'outbound' ? 'Textzi Support' : 'You' }} &middot; {{ new Date(message.created_at).toLocaleString() }}
          </div>
        </div>
      </VCardText>

      <VDivider />

      <VCardText>
        <VAlert
          v-if="sendError"
          type="error"
          variant="tonal"
          class="mb-3"
        >
          {{ sendError }}
        </VAlert>
        <VForm @submit.prevent="onSend">
          <div class="d-flex gap-3">
            <VTextarea
              v-model="draft"
              placeholder="Type your message..."
              rows="2"
              auto-grow
              hide-details
              @keydown.enter.exact.prevent="onSend"
            />
            <VBtn
              type="submit"
              color="primary"
              :loading="sending"
              :disabled="!draft.trim()"
              icon
            >
              <VIcon icon="tabler-send" />
            </VBtn>
          </div>
        </VForm>
      </VCardText>
    </VCard>
  </div>
</template>

<style scoped lang="scss">
.support-thread {
  block-size: 420px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.support-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}

.support-message {
  display: flex;
  flex-direction: column;
  margin-block-end: 16px;
  max-inline-size: 70%;
}

.support-message-you {
  align-items: flex-end;
  margin-inline-start: auto;
}

.support-message-agent {
  align-items: flex-start;
}

.support-message-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  white-space: pre-wrap;
}

.support-message-you .support-message-bubble {
  background: rgba(var(--v-theme-primary), 0.12);
}

.support-message-agent .support-message-bubble {
  background: rgba(var(--v-theme-on-surface), 0.06);
}
</style>
