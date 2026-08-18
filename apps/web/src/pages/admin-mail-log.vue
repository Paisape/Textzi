<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

type MailLogRow = {
  id: string
  organization_name: string | null
  entity_name: string
  mailbox_address: string
  direction: 'inbound' | 'outbound'
  contact_address: string | null
  subject: string | null
  body: string | null
  created_at: string
}

const messages = ref<MailLogRow[]>([])
const loadError = ref('')
const directionFilter = ref<'' | 'inbound' | 'outbound'>('')

async function loadMessages() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const query: Record<string, any> = { limit: 200 }
    if (directionFilter.value)
      query.direction = directionFilter.value
    messages.value = await $api<MailLogRow[]>('/v1/admin/stalwart/messages', { query })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the mail log.')
  }
}

watch(directionFilter, loadMessages)

const selected = ref<MailLogRow | null>(null)

onMounted(loadMessages)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Mail Log
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every email sent or received through any Textzi-hosted mailbox, across every tenant -- full
    content, not masked, since Textzi operates this mail server directly. See also
    <RouterLink :to="{ name: 'admin-mailboxes' }">
      Textzi Mailboxes
    </RouterLink>
    to manage the mailboxes themselves.
  </p>

  <VAlert v-if="isAdmin === false" type="warning" variant="tonal">
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
      {{ loadError }}
    </VAlert>

    <div class="d-flex ga-4" style="min-height: 70vh;">
      <VCard class="d-flex flex-column" style="min-inline-size: 380px; max-inline-size: 380px;">
        <VCardText class="pb-2 flex-grow-0">
          <VSelect
            v-model="directionFilter" density="compact" hide-details label="Direction"
            :items="[{ title: 'All', value: '' }, { title: 'Inbound', value: 'inbound' }, { title: 'Outbound', value: 'outbound' }]"
          />
        </VCardText>
        <VDivider />
        <div style="flex: 1; overflow-y: auto;">
          <VList density="compact" lines="three">
            <VListItem
              v-for="m in messages" :key="m.id"
              :active="selected?.id === m.id"
              @click="selected = m"
            >
              <template #prepend>
                <VIcon :icon="m.direction === 'outbound' ? 'tabler-arrow-up-right' : 'tabler-arrow-down-left'" size="18" />
              </template>
              <VListItemTitle>
                {{ m.mailbox_address }}
              </VListItemTitle>
              <VListItemSubtitle>
                {{ m.direction === 'outbound' ? 'to' : 'from' }} {{ m.contact_address || 'unknown' }}
              </VListItemSubtitle>
              <VListItemSubtitle>
                {{ m.subject || '(no subject)' }}
              </VListItemSubtitle>
              <template #append>
                <span class="text-caption text-medium-emphasis">
                  {{ new Date(m.created_at).toLocaleDateString('en-IN') }}
                </span>
              </template>
            </VListItem>
          </VList>
          <p v-if="!messages.length" class="text-medium-emphasis text-center pa-6 mb-0">
            No mail yet.
          </p>
        </div>
      </VCard>

      <VCard v-if="!selected" class="flex-grow-1 d-flex align-center justify-center">
        <p class="text-medium-emphasis">
          Select a message to read it.
        </p>
      </VCard>
      <VCard v-else class="flex-grow-1 d-flex flex-column overflow-hidden">
        <VCardText class="flex-grow-0">
          <h2 class="text-h6 mb-1">
            {{ selected.subject || '(no subject)' }}
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-0">
            {{ selected.organization_name }} · {{ selected.entity_name }} · {{ selected.mailbox_address }}
          </p>
          <p class="text-body-2 text-medium-emphasis mb-0">
            {{ selected.direction === 'outbound' ? 'To' : 'From' }} {{ selected.contact_address || 'unknown' }}
            · {{ new Date(selected.created_at).toLocaleString('en-IN') }}
          </p>
        </VCardText>
        <VDivider />
        <div class="flex-grow-1 overflow-y-auto pa-4">
          <!-- eslint-disable-next-line vue/no-v-html -->
          <div v-if="selected.direction === 'outbound'" v-html="selected.body" />
          <p v-else class="mb-0" style="white-space: pre-wrap;">
            {{ selected.body }}
          </p>
        </div>
      </VCard>
    </div>
  </template>
</template>
