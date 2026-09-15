<script lang="ts" setup>
import type { Notification } from '@layouts/types'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

type AdminNotification = { id: string, severity: string, title: string, description: string, link: string | null }

const SEVERITY_ICON: Record<string, string> = {
  info: 'tabler-info-circle',
  warning: 'tabler-alert-triangle',
  error: 'tabler-alert-octagon',
}
const SEVERITY_COLOR: Record<string, string> = {
  info: 'info',
  warning: 'warning',
  error: 'error',
}

type CrmNotification = { id: string, type: string, title: string, body: string, link: string | null, read: boolean, created_at: string }

const notifications = ref<Notification[]>([])
const linkById = new Map<number, string>()
const crmIdById = new Map<number, string>()

async function loadNotifications() {
  try {
    await authStore.load()
    if (authStore.isAdmin) {
      const data = await $api<AdminNotification[]>('/v1/admin/notifications')
      linkById.clear()
      notifications.value = data.map((n, i) => {
        if (n.link)
          linkById.set(i, n.link)
        return {
          id: i,
          icon: SEVERITY_ICON[n.severity] || 'tabler-bell',
          color: SEVERITY_COLOR[n.severity] || 'primary',
          title: n.title,
          subtitle: n.description,
          time: '',
          isSeen: false,
        }
      })
      return
    }
    if (!authStore.crmActive) {
      notifications.value = []
      return
    }
    const data = await $api<CrmNotification[]>('/v1/crm/notifications')
    linkById.clear()
    crmIdById.clear()
    notifications.value = data.map((n, i) => {
      if (n.link)
        linkById.set(i, n.link)
      crmIdById.set(i, n.id)
      return {
        id: i,
        icon: 'tabler-bell',
        color: 'primary',
        title: n.title,
        subtitle: n.body,
        time: '',
        isSeen: n.read,
      }
    })
  }
  catch {
    notifications.value = []
  }
}

// --- Live push: reuses the same per-entity realtime socket the WhatsApp/CRM inbox pages use
// (waba_realtime.py) -- lets the bell update and play a sound immediately when a ticket/lead/deal
// is assigned, a ticket resolves, a new reply lands, or a quote/invoice is generated, rather than
// only refreshing on next page load. Held here (not in inbox.vue) since this component is
// mounted in the dashboard layout on every page, not just the inbox ones.
let socket: WebSocket | null = null
let reconnectTimeout: ReturnType<typeof setTimeout> | undefined

function wsUrl(): string {
  const base = import.meta.env.VITE_API_BASE_URL || window.location.origin
  const token = useCookie('accessToken').value
  return `${base.replace(/^http/, 'ws')}/v1/waba/ws?token=${encodeURIComponent(token || '')}`
}

// A short synthesized beep -- no bundled audio asset needed, and this reliably works everywhere
// without shipping/loading a binary file. Browsers block audio until the user has interacted with
// the page at least once; a failed play() here is silently ignored rather than surfaced as an
// error, since a missed sound on the very first notification of a session is a low-stakes gap.
function playChime() {
  try {
    const AudioCtx = window.AudioContext || (window as any).webkitAudioContext
    const ctx = new AudioCtx()
    const oscillator = ctx.createOscillator()
    const gain = ctx.createGain()
    oscillator.type = 'sine'
    oscillator.frequency.setValueAtTime(880, ctx.currentTime)
    oscillator.frequency.setValueAtTime(660, ctx.currentTime + 0.12)
    gain.gain.setValueAtTime(0.15, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3)
    oscillator.connect(gain)
    gain.connect(ctx.destination)
    oscillator.start()
    oscillator.stop(ctx.currentTime + 0.3)
  }
  catch {
    // Ignore -- browser audio policy or an unsupported environment.
  }
}

function notifyBrowser(title: string, body: string) {
  if (typeof Notification === 'undefined')
    return
  if (Notification.permission === 'granted')
    // eslint-disable-next-line no-new
    new Notification(title, { body, icon: '/favicon.ico' })
}

function connectSocket() {
  // Matches waba_realtime.py's own gate: this socket only serves WhatsApp/CRM notifications, so
  // an admin/staff session or a teammate scoped to a third, unrelated channel (e.g. "sms" only)
  // has nothing to listen for and would just be rejected by the backend anyway.
  if (authStore.isAdmin || (authStore.channelScope && authStore.channelScope !== 'waba' && authStore.channelScope !== 'crm'))
    return
  socket = new WebSocket(wsUrl())
  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'notification' && payload.user_id === authStore.profile?.id) {
        const n = payload.notification as { id: string, type: string, title: string, body: string, link: string | null }
        const localId = notifications.value.reduce((max, x) => Math.max(max, x.id), -1) + 1
        crmIdById.set(localId, n.id)
        if (n.link)
          linkById.set(localId, n.link)
        notifications.value.unshift({
          id: localId,
          icon: 'tabler-bell',
          color: 'primary',
          title: n.title,
          subtitle: n.body,
          time: '',
          isSeen: false,
        })
        playChime()
        notifyBrowser(n.title, n.body)
      }
    }
    catch {
      // Ignore anything that isn't the JSON shape we expect.
    }
  }
  socket.onclose = () => {
    reconnectTimeout = setTimeout(connectSocket, 3000)
  }
}

onMounted(async () => {
  await loadNotifications()
  connectSocket()
  if (typeof Notification !== 'undefined' && Notification.permission === 'default')
    Notification.requestPermission()
})

onBeforeUnmount(() => {
  clearTimeout(reconnectTimeout)
  socket?.close()
})

const removeNotification = (notificationId: number) => {
  notifications.value.forEach((item, index) => {
    if (notificationId === item.id)
      notifications.value.splice(index, 1)
  })
}

async function persistRead(notificationId: number[]) {
  if (authStore.isAdmin)
    return
  await Promise.all(
    notificationId
      .map(id => crmIdById.get(id))
      .filter((id): id is string => !!id)
      .map(id => $api(`/v1/crm/notifications/${id}/read`, { method: 'POST' }).catch(() => {})),
  )
}

const markRead = (notificationId: number[]) => {
  notifications.value.forEach(item => {
    notificationId.forEach(id => {
      if (id === item.id)
        item.isSeen = true
    })
  })
  persistRead(notificationId)
}

const markUnRead = (notificationId: number[]) => {
  notifications.value.forEach(item => {
    notificationId.forEach(id => {
      if (id === item.id)
        item.isSeen = false
    })
  })
}

const handleNotificationClick = (notification: Notification) => {
  if (!notification.isSeen)
    markRead([notification.id])
  const link = linkById.get(notification.id)
  if (link)
    router.push(link)
}
</script>

<template>
  <Notifications
    :notifications="notifications"
    @remove="removeNotification"
    @read="markRead"
    @unread="markUnRead"
    @click:notification="handleNotificationClick"
  />
</template>
