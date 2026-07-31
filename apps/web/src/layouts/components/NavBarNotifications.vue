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

const notifications = ref<Notification[]>([])
const linkById = new Map<number, string>()

async function loadNotifications() {
  try {
    await authStore.load()
    if (!authStore.isAdmin) {
      notifications.value = []
      return
    }
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
  }
  catch {
    notifications.value = []
  }
}

onMounted(loadNotifications)

const removeNotification = (notificationId: number) => {
  notifications.value.forEach((item, index) => {
    if (notificationId === item.id)
      notifications.value.splice(index, 1)
  })
}

const markRead = (notificationId: number[]) => {
  notifications.value.forEach(item => {
    notificationId.forEach(id => {
      if (id === item.id)
        item.isSeen = true
    })
  })
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
