<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

const route = useRoute('waba-customers-id')
const router = useRouter()

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null, consent_given_at: string | null, consent_source: string | null }
type Lead = { id: string, stage: string, source: string, owner_user_id: string | null, notes: string | null }
type Customer = { id: string, owner_user_id: string | null, notes: string | null }
type Message = {
  id: string
  direction: 'inbound' | 'outbound'
  is_private: boolean
  message_type: string
  body: string | null
  media_url: string | null
  status: string | null
  error: string | null
  sent_by_user_id: string | null
  created_at: string
}
type Timeline = {
  contact: Contact
  conversation_id: string | null
  lead: Lead | null
  customer: Customer | null
  tickets: { open: number, resolved: number }
  messages: Message[]
}
type AssignableUser = { id: string, full_name: string, email: string }
type CustomerRow = { id: string, contact: Contact }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean, assigned_user_id: string | null, recurrence: string }
type Attachment = { id: string, contact_id: string, filename: string, uploaded_by_user_id: string | null, created_at: string }

const timeline = ref<Timeline | null>(null)
const loading = ref(false)
const loadError = ref('')
const users = ref<AssignableUser[]>([])
const existingCustomers = ref<CustomerRow[]>([])
const tasks = ref<Task[]>([])
const attachments = ref<Attachment[]>([])

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [tl, userResult, settingsResult, taskResult, attachmentResult] = await Promise.all([
      $api<Timeline>(`/v1/waba/contacts/${route.params.id}/timeline`),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<{ pipeline_stages: string[] }>('/v1/crm/settings'),
      $api<Task[]>('/v1/crm/tasks', { params: { contact_id: route.params.id } }),
      $api<Attachment[]>(`/v1/crm/contacts/${route.params.id}/attachments`),
    ])
    timeline.value = tl
    users.value = userResult
    LEAD_STAGES.value = settingsResult.pipeline_stages
    tasks.value = taskResult
    attachments.value = attachmentResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this customer.')
  }
  finally {
    loading.value = false
  }
}

const uploading = ref(false)
const attachmentError = ref('')

async function uploadFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file)
    return
  uploading.value = true
  attachmentError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file)
    const created = await $api<Attachment>(`/v1/crm/contacts/${route.params.id}/attachments`, { method: 'POST', body: formData })
    attachments.value.unshift(created)
  }
  catch (error: any) {
    attachmentError.value = extractErrorMessage(error, 'Could not upload this file.')
  }
  finally {
    uploading.value = false
    ;(event.target as HTMLInputElement).value = ''
  }
}

async function downloadAttachment(attachment: Attachment) {
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/attachments/${attachment.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = attachment.filename
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    attachmentError.value = extractErrorMessage(error, 'Could not download this file.')
  }
}

async function deleteAttachment(attachment: Attachment) {
  try {
    await $api(`/v1/crm/attachments/${attachment.id}`, { method: 'DELETE' })
    attachments.value = attachments.value.filter(a => a.id !== attachment.id)
  }
  catch (error: any) {
    attachmentError.value = extractErrorMessage(error, 'Could not delete this file.')
  }
}

// --- DPDP: consent, data export, right to erasure ---------------------------------------------

const consentDialog = ref(false)
const consentSource = ref('')
const consentSaving = ref(false)
const consentError = ref('')

function openConsentDialog() {
  consentSource.value = ''
  consentError.value = ''
  consentDialog.value = true
}

async function recordConsent() {
  if (!consentSource.value.trim() || !timeline.value)
    return
  consentSaving.value = true
  consentError.value = ''
  try {
    const updated = await $api<Contact>(`/v1/crm/contacts/${route.params.id}/consent`, { method: 'PUT', body: { consent_source: consentSource.value.trim() } })
    timeline.value.contact = updated
    consentDialog.value = false
  }
  catch (error: any) {
    consentError.value = extractErrorMessage(error, 'Could not record consent.')
  }
  finally {
    consentSaving.value = false
  }
}

const exportingData = ref(false)

async function exportData() {
  exportingData.value = true
  actionError.value = ''
  try {
    const bundle = await $api(`/v1/crm/contacts/${route.params.id}/data-export`)
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `contact-${route.params.id}-data-export.json`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not export this contact\'s data.')
  }
  finally {
    exportingData.value = false
  }
}

const deleteDialog = ref(false)
const deleting = ref(false)
const deleteError = ref('')

async function confirmDelete() {
  deleting.value = true
  deleteError.value = ''
  try {
    await $api(`/v1/crm/contacts/${route.params.id}`, { method: 'DELETE' })
    router.push({ name: 'waba-customers' })
  }
  catch (error: any) {
    deleteError.value = extractErrorMessage(error, 'Could not delete this contact\'s data.')
    deleting.value = false
  }
}

const newTaskTitle = ref('')
const addingTask = ref(false)

async function addTask() {
  if (!newTaskTitle.value.trim())
    return
  addingTask.value = true
  try {
    const created = await $api<Task>('/v1/crm/tasks', {
      method: 'POST',
      body: { contact_id: route.params.id, title: newTaskTitle.value.trim() },
    })
    tasks.value.unshift(created)
    newTaskTitle.value = ''
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not add this task.')
  }
  finally {
    addingTask.value = false
  }
}

async function toggleTaskDone(task: Task) {
  try {
    const updated = await $api<Task>(`/v1/crm/tasks/${task.id}`, { method: 'PATCH', body: { done: !task.done } })
    Object.assign(task, updated)
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this task.')
  }
}

function senderName(message: Message) {
  if (message.direction === 'inbound')
    return timeline.value?.contact.name || 'Customer'
  return users.value.find(u => u.id === message.sent_by_user_id)?.full_name || 'Agent'
}

function openChat() {
  if (timeline.value?.conversation_id)
    router.push(`/inbox?conversation=${timeline.value.conversation_id}`)
}

const crmUpsellDialog = ref(false)
const actionError = ref('')

function handleActionError(error: any, fallback: string) {
  if (error?.response?.status === 422 && String(error?.data?.detail || '').includes('CRM'))
    crmUpsellDialog.value = true
  else
    actionError.value = extractErrorMessage(error, fallback)
}

// --- Create lead / create customer ---

const crmForm = ref<{ mode: 'lead' | 'customer', stage: string, owner_user_id: string | null, notes: string } | null>(null)
const crmFormSubmitting = ref(false)
const crmFormError = ref('')
const LEAD_STAGES = ref<string[]>(['inquiry'])

function openLeadForm() {
  crmForm.value = { mode: 'lead', stage: LEAD_STAGES.value[0], owner_user_id: null, notes: '' }
  crmFormError.value = ''
}

function openCustomerForm() {
  crmForm.value = { mode: 'customer', stage: '', owner_user_id: null, notes: '' }
  crmFormError.value = ''
}

async function submitCrmForm() {
  if (!crmForm.value)
    return
  crmFormSubmitting.value = true
  crmFormError.value = ''
  try {
    if (crmForm.value.mode === 'lead') {
      await $api(`/v1/crm/contacts/${route.params.id}/convert-to-lead`, {
        method: 'POST',
        body: { stage: crmForm.value.stage, owner_user_id: crmForm.value.owner_user_id, notes: crmForm.value.notes || null },
      })
    }
    else {
      await $api(`/v1/crm/contacts/${route.params.id}/convert-to-customer`, {
        method: 'POST',
        body: { owner_user_id: crmForm.value.owner_user_id, notes: crmForm.value.notes || null },
      })
    }
    crmForm.value = null
    await load()
  }
  catch (error: any) {
    if (error?.response?.status === 422 && String(error?.data?.detail || '').includes('CRM')) {
      crmForm.value = null
      crmUpsellDialog.value = true
    }
    else {
      crmFormError.value = extractErrorMessage(error, `Could not convert this contact to a ${crmForm.value.mode}.`)
    }
  }
  finally {
    crmFormSubmitting.value = false
  }
}

// --- Map to existing customer ---

const mapDialog = ref(false)
const mapCustomerId = ref<string | null>(null)
const mapSubmitting = ref(false)
const mapError = ref('')

async function openMapDialog() {
  mapCustomerId.value = null
  mapError.value = ''
  mapDialog.value = true
  if (!existingCustomers.value.length) {
    try {
      existingCustomers.value = await $api<CustomerRow[]>('/v1/crm/customers')
    }
    catch (error: any) {
      mapError.value = extractErrorMessage(error, 'Could not load existing customers.')
    }
  }
}

async function submitMap() {
  if (!mapCustomerId.value)
    return
  mapSubmitting.value = true
  mapError.value = ''
  try {
    await $api(`/v1/crm/contacts/${route.params.id}/map-to-customer`, { method: 'POST', body: { customer_id: mapCustomerId.value } })
    mapDialog.value = false
    await load()
  }
  catch (error: any) {
    mapError.value = extractErrorMessage(error, 'Could not map this contact to that customer.')
  }
  finally {
    mapSubmitting.value = false
  }
}

// --- Create ticket ---

const creatingTicket = ref(false)

async function createTicket() {
  if (!timeline.value?.conversation_id)
    return
  creatingTicket.value = true
  actionError.value = ''
  try {
    await $api(`/v1/waba/conversations/${timeline.value.conversation_id}/convert-to-ticket`, { method: 'POST' })
    await load()
  }
  catch (error: any) {
    handleActionError(error, 'Could not create a ticket for this conversation.')
  }
  finally {
    creatingTicket.value = false
  }
}

onMounted(load)
</script>

<template>
  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <template v-if="timeline">
    <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-2">
      <div>
        <h1 class="text-h4 mb-0">
          {{ timeline.contact.name || timeline.contact.wa_id || 'Customer' }}
        </h1>
        <p class="text-medium-emphasis mb-0">
          {{ timeline.contact.wa_id || '—' }}
        </p>
      </div>
      <div class="d-flex ga-2">
        <VChip v-if="timeline.lead" size="small" color="info">
          Lead: {{ timeline.lead.stage }}
        </VChip>
        <VChip v-if="timeline.customer" size="small" color="primary">
          Customer
        </VChip>
        <VChip size="small" color="warning" variant="tonal">
          {{ timeline.tickets.open }} open ticket{{ timeline.tickets.open === 1 ? '' : 's' }}
        </VChip>
        <VChip size="small" color="success" variant="tonal">
          {{ timeline.tickets.resolved }} resolved
        </VChip>
      </div>
    </div>

    <VAlert v-if="actionError" type="error" variant="tonal" density="compact" class="my-4">
      {{ actionError }}
    </VAlert>

    <div class="d-flex flex-wrap ga-3 my-4">
      <VBtn prepend-icon="tabler-messages" :disabled="!timeline.conversation_id" @click="openChat">
        Open chat
      </VBtn>
      <VBtn v-if="!timeline.lead" variant="tonal" prepend-icon="tabler-target-arrow" @click="openLeadForm">
        Create lead
      </VBtn>
      <VBtn v-if="!timeline.customer" variant="tonal" prepend-icon="tabler-user-check" @click="openCustomerForm">
        Create customer
      </VBtn>
      <VBtn v-if="!timeline.customer" variant="tonal" prepend-icon="tabler-link" @click="openMapDialog">
        Map to existing customer
      </VBtn>
      <VBtn
        v-if="timeline.conversation_id && !timeline.tickets.open && !timeline.tickets.resolved"
        variant="tonal"
        prepend-icon="tabler-ticket"
        :loading="creatingTicket"
        @click="createTicket"
      >
        Create ticket
      </VBtn>
    </div>

    <VCard v-if="crmForm" max-width="480" class="mb-6">
      <VCardText>
        <h3 class="text-subtitle-1 mb-3">
          {{ crmForm.mode === 'lead' ? 'Create lead' : 'Create customer' }}
        </h3>
        <VAlert v-if="crmFormError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ crmFormError }}
        </VAlert>
        <VSelect v-if="crmForm.mode === 'lead'" v-model="crmForm.stage" :items="LEAD_STAGES" label="Stage" density="compact" class="mb-3" />
        <VSelect
          v-model="crmForm.owner_user_id"
          :items="[{ title: 'Unassigned', value: null }, ...users.map(u => ({ title: u.full_name, value: u.id }))]"
          label="Owner"
          density="compact"
          class="mb-3"
        />
        <VTextarea v-model="crmForm.notes" label="Notes" rows="3" density="compact" class="mb-3" />
        <div class="d-flex justify-end ga-3">
          <VBtn variant="text" @click="crmForm = null">
            Cancel
          </VBtn>
          <VBtn :loading="crmFormSubmitting" @click="submitCrmForm">
            Create {{ crmForm.mode }}
          </VBtn>
        </div>
      </VCardText>
    </VCard>

    <h2 class="text-h6 mb-3">
      Tasks
    </h2>
    <VCard class="mb-6">
      <VCardText>
        <div class="d-flex ga-2 mb-3">
          <VTextField
            v-model="newTaskTitle" placeholder="Add a follow-up…" density="compact" hide-details
            @keydown.enter="addTask"
          />
          <VBtn :loading="addingTask" :disabled="!newTaskTitle.trim()" @click="addTask">
            Add
          </VBtn>
        </div>
        <VList v-if="tasks.length" density="compact">
          <VListItem v-for="task in tasks" :key="task.id">
            <template #prepend>
              <VCheckbox :model-value="task.done" hide-details @update:model-value="toggleTaskDone(task)" />
            </template>
            <VListItemTitle :class="task.done ? 'text-decoration-line-through text-medium-emphasis' : ''">
              {{ task.title }}
            </VListItemTitle>
            <VListItemSubtitle v-if="task.due_at">
              Due {{ new Date(task.due_at).toLocaleString('en-IN') }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis mb-0">
          No tasks for this contact yet.
        </p>
      </VCardText>
    </VCard>

    <h2 class="text-h6 mb-3">
      Attachments
    </h2>
    <VCard class="mb-6">
      <VCardText>
        <VAlert v-if="attachmentError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ attachmentError }}
        </VAlert>
        <VBtn size="small" variant="tonal" prepend-icon="tabler-upload" :loading="uploading" class="mb-3" style="position: relative;">
          Upload file
          <input type="file" class="file-input-overlay" @change="uploadFile">
        </VBtn>
        <VList v-if="attachments.length" density="compact">
          <VListItem v-for="attachment in attachments" :key="attachment.id">
            <VListItemTitle>{{ attachment.filename }}</VListItemTitle>
            <VListItemSubtitle>{{ new Date(attachment.created_at).toLocaleDateString('en-IN') }}</VListItemSubtitle>
            <template #append>
              <VBtn icon="tabler-download" size="small" variant="text" @click="downloadAttachment(attachment)" />
              <VBtn icon="tabler-trash" size="small" variant="text" @click="deleteAttachment(attachment)" />
            </template>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis mb-0">
          No files attached to this contact yet.
        </p>
      </VCardText>
    </VCard>

    <h2 class="text-h6 mb-3">
      Privacy
    </h2>
    <VCard class="mb-6">
      <VCardText>
        <p class="text-body-2 text-medium-emphasis mb-3">
          DPDP Act tools — record how this contact consented to be contacted, export everything
          Textzi holds on them, or permanently delete their data.
        </p>
        <p class="text-body-2 mb-4">
          Consent:
          <strong v-if="timeline.contact.consent_given_at">
            given {{ new Date(timeline.contact.consent_given_at).toLocaleDateString('en-IN') }} ({{ timeline.contact.consent_source }})
          </strong>
          <span v-else class="text-medium-emphasis">not recorded</span>
        </p>
        <div class="d-flex flex-wrap ga-3">
          <VBtn size="small" variant="tonal" prepend-icon="tabler-shield-check" @click="openConsentDialog">
            Record consent
          </VBtn>
          <VBtn size="small" variant="tonal" prepend-icon="tabler-download" :loading="exportingData" @click="exportData">
            Export data
          </VBtn>
          <VBtn size="small" variant="tonal" color="error" prepend-icon="tabler-trash" @click="deleteDialog = true">
            Delete all data
          </VBtn>
        </div>
      </VCardText>
    </VCard>

    <h2 class="text-h6 mb-3">
      Chat history
    </h2>
    <VCard>
      <VCardText style="max-height: 600px; overflow-y: auto;">
        <div v-for="message in timeline.messages" :key="message.id" class="mb-4">
          <div class="d-flex align-center ga-2 mb-1">
            <strong>{{ senderName(message) }}</strong>
            <span class="text-caption text-medium-emphasis">{{ new Date(message.created_at).toLocaleString('en-IN') }}</span>
            <VChip v-if="message.is_private" size="x-small" color="warning">
              Note
            </VChip>
            <VChip v-if="message.message_type !== 'text'" size="x-small" variant="outlined">
              {{ message.message_type }}
            </VChip>
          </div>
          <p v-if="message.body" class="mb-0" style="white-space: pre-wrap;">
            {{ message.body }}
          </p>
          <a v-if="message.media_url" :href="message.media_url" target="_blank" rel="noopener">
            View attachment
          </a>
          <p v-if="message.error" class="text-error text-caption mb-0">
            {{ message.error }}
          </p>
        </div>
        <p v-if="!timeline.messages.length" class="text-medium-emphasis text-center pa-6">
          No messages yet.
        </p>
      </VCardText>
    </VCard>
  </template>

  <VDialog v-model="mapDialog" max-width="420">
    <VCard>
      <VCardTitle>Map to existing customer</VCardTitle>
      <VCardText>
        <VAlert v-if="mapError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ mapError }}
        </VAlert>
        <VSelect
          v-model="mapCustomerId"
          :items="existingCustomers.map(c => ({ title: c.contact.name || c.contact.wa_id || c.id, value: c.id }))"
          label="Existing customer"
        />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="mapDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="mapSubmitting" :disabled="!mapCustomerId" @click="submitMap">
          Map
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="crmUpsellDialog" max-width="420">
    <VCard>
      <VCardTitle>Upgrade to CRM</VCardTitle>
      <VCardText>
        Converting contacts to leads, customers, and tickets requires the CRM channel. Subscribe
        to it from the Channels page to unlock this.
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

  <VDialog v-model="consentDialog" max-width="420">
    <VCard title="Record consent">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="consentError" type="error" variant="tonal" density="compact">
          {{ consentError }}
        </VAlert>
        <VTextField v-model="consentSource" label="Consent source" placeholder="e.g. WhatsApp opt-in, web form, verbal on call" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="consentDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="consentSaving" :disabled="!consentSource.trim()" @click="recordConsent">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="deleteDialog" max-width="440">
    <VCard title="Delete all data for this contact">
      <VCardText>
        <VAlert v-if="deleteError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ deleteError }}
        </VAlert>
        <p class="mb-0">
          This permanently deletes this contact, their lead/customer record, and their entire
          chat history. This can't be undone.
        </p>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="deleteDialog = false">
          Cancel
        </VBtn>
        <VBtn color="error" :loading="deleting" @click="confirmDelete">
          Delete permanently
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>

<style scoped>
.file-input-overlay {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}
</style>
