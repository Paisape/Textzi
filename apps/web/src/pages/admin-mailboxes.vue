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

type MailboxRow = {
  id: string
  organization_name: string | null
  entity_name: string
  address: string
  status: string
  last_synced_at: string | null
  created_at: string
}

const mailboxes = ref<MailboxRow[]>([])
const loadError = ref('')
const search = ref('')
let searchTimer: ReturnType<typeof setTimeout> | undefined

async function loadMailboxes() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const query: Record<string, any> = { limit: 200 }
    if (search.value)
      query.search = search.value
    mailboxes.value = await $api<MailboxRow[]>('/v1/admin/stalwart/mailboxes', { query })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load mailboxes.')
  }
}

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(loadMailboxes, 300)
})

const actionError = ref('')
const actingId = ref('')

async function toggleSuspend(mailbox: MailboxRow) {
  actionError.value = ''
  actingId.value = mailbox.id
  const nextStatus = mailbox.status === 'suspended' ? 'connected' : 'suspended'
  try {
    const updated = await $api<MailboxRow>(`/v1/admin/stalwart/mailboxes/${mailbox.id}/status`, {
      method: 'PATCH',
      body: { status: nextStatus },
    })
    mailbox.status = updated.status
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this mailbox.')
  }
  finally {
    actingId.value = ''
  }
}

const deleteDialog = ref(false)
const deleteTarget = ref<MailboxRow | null>(null)
const deleting = ref(false)

function openDeleteDialog(mailbox: MailboxRow) {
  deleteTarget.value = mailbox
  deleteDialog.value = true
}

async function confirmDelete() {
  if (!deleteTarget.value)
    return
  deleting.value = true
  actionError.value = ''
  try {
    await $api(`/v1/admin/stalwart/mailboxes/${deleteTarget.value.id}`, { method: 'DELETE' })
    mailboxes.value = mailboxes.value.filter(m => m.id !== deleteTarget.value?.id)
    deleteDialog.value = false
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not delete this mailbox.')
  }
  finally {
    deleting.value = false
  }
}

onMounted(loadMailboxes)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <h1 class="text-h4 mb-0">
      Textzi Mailboxes
    </h1>
  </div>
  <p class="text-medium-emphasis mb-6">
    Every mailbox provisioned on Textzi's own Stalwart mail server, across every tenant. Suspend
    stops a mailbox from sending or receiving without deleting it; delete removes Textzi's record
    of the connection only -- the mailbox itself stays on Stalwart. See also
    <RouterLink :to="{ name: 'admin-mail-log' }">
      Mail Log
    </RouterLink>
    for message-level content.
  </p>

  <VAlert v-if="isAdmin === false" type="warning" variant="tonal">
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <template v-else-if="isAdmin">
    <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
      {{ loadError }}
    </VAlert>
    <VAlert v-if="actionError" type="error" variant="tonal" class="mb-4" closable @click:close="actionError = ''">
      {{ actionError }}
    </VAlert>

    <VCard>
      <VCardText>
        <VTextField v-model="search" placeholder="Search by mailbox address" density="compact" prepend-inner-icon="tabler-search" hide-details clearable style="max-inline-size: 360px;" />
      </VCardText>
      <VTable>
        <thead>
          <tr>
            <th>Mailbox</th>
            <th>Organization</th>
            <th>Status</th>
            <th>Created</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="mailbox in mailboxes" :key="mailbox.id">
            <td>{{ mailbox.address }}</td>
            <td>
              <div>{{ mailbox.organization_name || '—' }}</div>
              <div class="text-body-2 text-medium-emphasis">
                {{ mailbox.entity_name }}
              </div>
            </td>
            <td>
              <VChip size="small" :color="mailbox.status === 'connected' ? 'success' : mailbox.status === 'suspended' ? 'warning' : 'error'">
                {{ mailbox.status }}
              </VChip>
            </td>
            <td>{{ new Date(mailbox.created_at).toLocaleDateString('en-IN') }}</td>
            <td>
              <div class="d-flex align-center gap-3">
                <a href="#" @click.prevent="toggleSuspend(mailbox)">
                  {{ actingId === mailbox.id ? '...' : (mailbox.status === 'suspended' ? 'Resume' : 'Suspend') }}
                </a>
                <a href="#" class="text-error" @click.prevent="openDeleteDialog(mailbox)">
                  Delete
                </a>
              </div>
            </td>
          </tr>
          <tr v-if="!mailboxes.length">
            <td colspan="5" class="text-center text-medium-emphasis">
              No Textzi-hosted mailboxes yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>

  <VDialog v-model="deleteDialog" max-width="420">
    <VCard title="Delete mailbox">
      <VCardText>
        Delete Textzi's record of <strong>{{ deleteTarget?.address }}</strong>? The mailbox itself
        stays provisioned on Stalwart; the tenant will see it as disconnected and can connect a
        different mailbox.
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="deleteDialog = false">
          Cancel
        </VBtn>
        <VBtn color="error" :loading="deleting" @click="confirmDelete">
          Delete
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
