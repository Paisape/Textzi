<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type DirectoryEntry = {
  contact: Contact
  conversation_id: string | null
  last_message_at: string | null
  last_reply_at: string | null
  is_ticket: boolean
  ticket_number: string | null
  ticket_status: string | null
  lead_id: string | null
  customer_id: string | null
}

const entries = ref<DirectoryEntry[]>([])
const loading = ref(false)
const loadError = ref('')
const search = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    entries.value = await $api<DirectoryEntry[]>('/v1/waba/contacts-directory')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load customers.')
  }
  finally {
    loading.value = false
  }
}

const filtered = computed(() => {
  if (!search.value.trim())
    return entries.value
  const q = search.value.trim().toLowerCase()
  return entries.value.filter(e => (e.contact.name || '').toLowerCase().includes(q) || (e.contact.wa_id || '').includes(q))
})

const openTicketCount = computed(() => entries.value.filter(e => e.is_ticket && e.ticket_status !== 'resolved').length)
const resolvedTicketCount = computed(() => entries.value.filter(e => e.is_ticket && e.ticket_status === 'resolved').length)

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

async function exportCsv() {
  const blob = await $api<Blob>('/v1/waba/contacts/export', { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'contacts.csv'
  link.click()
  URL.revokeObjectURL(url)
}

const importDialog = ref(false)
const importFile = ref<File[]>([])
const importing = ref(false)
const importError = ref('')
const importResult = ref<{ created: number, updated: number, skipped: number } | null>(null)

async function onImportFile() {
  const file = importFile.value[0]
  if (!file)
    return
  importing.value = true
  importError.value = ''
  importResult.value = null
  try {
    const formData = new FormData()
    formData.append('file', file)
    importResult.value = await $api('/v1/waba/contacts/import', { method: 'POST', body: formData })
    await load()
  }
  catch (error: any) {
    importError.value = extractErrorMessage(error, 'Could not import this file.')
  }
  finally {
    importing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <h1 class="text-h4">
      Customers
    </h1>
    <div class="d-flex ga-3">
      <VBtn variant="tonal" prepend-icon="tabler-upload" @click="importDialog = true">
        Import CSV
      </VBtn>
      <VBtn variant="tonal" prepend-icon="tabler-download" @click="exportCsv">
        Export CSV
      </VBtn>
    </div>
  </div>
  <p class="text-medium-emphasis mb-4">
    Everyone who's messaged your WhatsApp number. Open a customer to see their full chat trail,
    start a new chat, or convert them to a lead, customer, or ticket.
  </p>

  <div class="d-flex ga-4 mb-6">
    <VChip prepend-icon="tabler-ticket" color="warning" variant="tonal">
      {{ openTicketCount }} open tickets
    </VChip>
    <VChip prepend-icon="tabler-circle-check" color="success" variant="tonal">
      {{ resolvedTicketCount }} resolved tickets
    </VChip>
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VTextField
    v-model="search"
    placeholder="Search by name or number"
    prepend-inner-icon="tabler-search"
    density="compact"
    variant="outlined"
    class="mb-4"
    style="max-width: 360px;"
  />

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Mobile no</th>
          <th>Last message</th>
          <th>Last reply</th>
          <th>Status</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="entry in filtered" :key="entry.contact.id">
          <td>{{ entry.contact.name || '—' }}</td>
          <td>{{ entry.contact.wa_id || '—' }}</td>
          <td>{{ formatDate(entry.last_message_at) }}</td>
          <td>{{ formatDate(entry.last_reply_at) }}</td>
          <td>
            <VChip v-if="entry.is_ticket" size="small" :color="entry.ticket_status === 'resolved' ? 'success' : 'warning'">
              {{ entry.ticket_number }}
            </VChip>
            <VChip v-if="entry.lead_id" size="small" color="info" class="ml-1">
              Lead
            </VChip>
            <VChip v-if="entry.customer_id" size="small" color="primary" class="ml-1">
              Customer
            </VChip>
          </td>
          <td>
            <RouterLink :to="`/waba-customers/${entry.contact.id}`" class="font-weight-medium">
              View
            </RouterLink>
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !filtered.length" class="text-medium-emphasis text-center pa-6">
      No customers yet.
    </p>
  </VCard>

  <VDialog v-model="importDialog" max-width="480">
    <VCard>
      <VCardTitle>Import contacts</VCardTitle>
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-3">
          A CSV with a <code>wa_id</code> column (required) and optional <code>name</code>/
          <code>email</code> columns. Matches existing contacts by WhatsApp number.
        </p>
        <VAlert v-if="importError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ importError }}
        </VAlert>
        <VAlert v-if="importResult" type="success" variant="tonal" density="compact" class="mb-3">
          {{ importResult.created }} created, {{ importResult.updated }} updated, {{ importResult.skipped }} skipped.
        </VAlert>
        <VFileInput v-model="importFile" accept=".csv" label="CSV file" :loading="importing" @update:model-value="onImportFile" />
      </VCardText>
      <VCardText class="d-flex justify-end pt-0">
        <VBtn variant="text" @click="importDialog = false">
          Close
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
