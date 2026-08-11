<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Contact = { id: string, wa_id: string | null, email: string | null, name: string | null }
type Task = {
  id: string
  contact_id: string
  title: string
  type: 'call' | 'meeting' | 'follow_up' | 'other'
  due_at: string | null
  done: boolean
  assigned_user_id: string | null
  recurrence: 'none' | 'daily' | 'weekly' | 'monthly'
  created_at: string
}
type AssignableUser = { id: string, full_name: string, email: string }

const tasks = ref<Task[]>([])
const users = ref<AssignableUser[]>([])
const contactCache = ref<Record<string, Contact>>({})
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const showDone = ref(false)

async function loadContacts(ids: string[]) {
  const missing = [...new Set(ids)].filter(id => !contactCache.value[id])
  if (!missing.length)
    return
  const results = await Promise.allSettled(missing.map(id => $api<Contact>(`/v1/waba/contacts/${id}`)))
  results.forEach((r, i) => {
    if (r.status === 'fulfilled')
      contactCache.value[missing[i]] = r.value
  })
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [taskResult, userResult] = await Promise.all([
      $api<Task[]>('/v1/crm/tasks', { params: showDone.value ? {} : { done: false } }),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    tasks.value = taskResult
    users.value = userResult
    await loadContacts(taskResult.map(t => t.contact_id))
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load tasks.')
  }
  finally {
    loading.value = false
  }
}

function contactLabel(contactId: string) {
  const c = contactCache.value[contactId]
  return c ? (c.name || c.wa_id || c.email || 'Unknown') : '…'
}

function assigneeName(task: Task) {
  return users.value.find(u => u.id === task.assigned_user_id)?.full_name || 'Unassigned'
}

const endOfToday = computed(() => {
  const d = new Date()
  d.setHours(23, 59, 59, 999)
  return d
})

const overdueOrToday = computed(() => tasks.value.filter(t => !t.done && t.due_at && new Date(t.due_at) <= endOfToday.value))
const upcoming = computed(() => tasks.value.filter(t => !t.done && (!t.due_at || new Date(t.due_at) > endOfToday.value)))
const doneList = computed(() => tasks.value.filter(t => t.done))

function isOverdue(task: Task) {
  return !task.done && task.due_at && new Date(task.due_at) < new Date(new Date().setHours(0, 0, 0, 0))
}

const typeIcon: Record<string, string> = { call: 'tabler-phone', meeting: 'tabler-users', follow_up: 'tabler-clock', other: 'tabler-note' }

async function toggleDone(task: Task) {
  try {
    const updated = await $api<Task>(`/v1/crm/tasks/${task.id}`, { method: 'PATCH', body: { done: !task.done } })
    Object.assign(task, updated)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this task.')
  }
}

async function removeTask(task: Task) {
  try {
    await $api(`/v1/crm/tasks/${task.id}`, { method: 'DELETE' })
    tasks.value = tasks.value.filter(t => t.id !== task.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this task.')
  }
}

// --- Create dialog -------------------------------------------------------------------------

const dialog = ref(false)
const form = reactive({ contact_id: '', title: '', type: 'follow_up' as Task['type'], due_at: '', assigned_user_id: null as string | null, recurrence: 'none' as Task['recurrence'] })
const saving = ref(false)
const saveError = ref('')

const contactSearch = ref('')
const contactOptions = ref<Contact[]>([])
const contactSearchLoading = ref(false)
let contactSearchTimer: ReturnType<typeof setTimeout> | undefined

async function searchContacts(query: string) {
  contactSearchLoading.value = true
  try {
    contactOptions.value = await $api<Contact[]>('/v1/waba/contacts', { params: { search: query, limit: 20 } })
  }
  catch {
    // best-effort search -- an empty result list is an acceptable failure mode here
  }
  finally {
    contactSearchLoading.value = false
  }
}

watch(contactSearch, (query) => {
  clearTimeout(contactSearchTimer)
  contactSearchTimer = setTimeout(() => searchContacts(query || ''), 300)
})

function openCreate() {
  form.contact_id = ''
  form.title = ''
  form.type = 'follow_up'
  form.due_at = ''
  form.assigned_user_id = null
  form.recurrence = 'none'
  contactSearch.value = ''
  contactOptions.value = []
  saveError.value = ''
  dialog.value = true
}

async function save() {
  if (!form.contact_id || !form.title.trim())
    return
  saving.value = true
  saveError.value = ''
  try {
    const created = await $api<Task>('/v1/crm/tasks', {
      method: 'POST',
      body: {
        contact_id: form.contact_id,
        title: form.title.trim(),
        type: form.type,
        due_at: form.due_at ? new Date(form.due_at).toISOString() : null,
        assigned_user_id: form.assigned_user_id,
        recurrence: form.recurrence,
      },
    })
    tasks.value.unshift(created)
    await loadContacts([created.contact_id])
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not create this task.')
  }
  finally {
    saving.value = false
  }
}

watch(showDone, loadAll)
onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-3">
    <div>
      <h1 class="text-h4 mb-1">
        Tasks
      </h1>
      <p class="text-medium-emphasis">
        Calls, meetings, and follow-ups. Overdue and today's items surface first.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New task
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <VCard class="mb-6">
      <VCardItem>
        <VCardTitle>Today &amp; overdue</VCardTitle>
      </VCardItem>
      <VList v-if="overdueOrToday.length" density="compact">
        <VListItem v-for="task in overdueOrToday" :key="task.id">
          <template #prepend>
            <VCheckbox :model-value="task.done" hide-details @update:model-value="toggleDone(task)" />
          </template>
          <VListItemTitle :class="isOverdue(task) ? 'text-error' : ''">
            <VIcon :icon="typeIcon[task.type]" size="16" class="me-1" />
            {{ task.title }}
          </VListItemTitle>
          <VListItemSubtitle>
            {{ contactLabel(task.contact_id) }} · {{ assigneeName(task) }}
            <span v-if="task.due_at"> · due {{ new Date(task.due_at).toLocaleString('en-IN') }}</span>
            <VChip v-if="task.recurrence !== 'none'" size="x-small" class="ml-2" variant="tonal">
              {{ task.recurrence }}
            </VChip>
          </VListItemSubtitle>
          <template #append>
            <VBtn icon="tabler-trash" variant="text" size="small" @click="removeTask(task)" />
          </template>
        </VListItem>
      </VList>
      <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
        Nothing due today.
      </p>
    </VCard>

    <VCard class="mb-6">
      <VCardItem>
        <VCardTitle>Upcoming</VCardTitle>
      </VCardItem>
      <VList v-if="upcoming.length" density="compact">
        <VListItem v-for="task in upcoming" :key="task.id">
          <template #prepend>
            <VCheckbox :model-value="task.done" hide-details @update:model-value="toggleDone(task)" />
          </template>
          <VListItemTitle>
            <VIcon :icon="typeIcon[task.type]" size="16" class="me-1" />
            {{ task.title }}
          </VListItemTitle>
          <VListItemSubtitle>
            {{ contactLabel(task.contact_id) }} · {{ assigneeName(task) }}
            <span v-if="task.due_at"> · due {{ new Date(task.due_at).toLocaleString('en-IN') }}</span>
            <VChip v-if="task.recurrence !== 'none'" size="x-small" class="ml-2" variant="tonal">
              {{ task.recurrence }}
            </VChip>
          </VListItemSubtitle>
          <template #append>
            <VBtn icon="tabler-trash" variant="text" size="small" @click="removeTask(task)" />
          </template>
        </VListItem>
      </VList>
      <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
        No upcoming tasks.
      </p>
    </VCard>

    <div class="d-flex align-center justify-space-between mb-2">
      <h2 class="text-h6 mb-0">
        Completed
      </h2>
      <VCheckbox v-model="showDone" label="Show completed" density="compact" hide-details />
    </div>
    <VCard v-if="showDone">
      <VList v-if="doneList.length" density="compact">
        <VListItem v-for="task in doneList" :key="task.id">
          <template #prepend>
            <VCheckbox :model-value="task.done" hide-details @update:model-value="toggleDone(task)" />
          </template>
          <VListItemTitle class="text-decoration-line-through text-medium-emphasis">
            {{ task.title }}
          </VListItemTitle>
          <VListItemSubtitle>
            {{ contactLabel(task.contact_id) }} · {{ assigneeName(task) }}
          </VListItemSubtitle>
        </VListItem>
      </VList>
      <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
        No completed tasks yet.
      </p>
    </VCard>
  </template>

  <VDialog v-model="dialog" max-width="480">
    <VCard title="New task">
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VAutocomplete
          v-model="form.contact_id"
          v-model:search="contactSearch"
          :items="contactOptions"
          :item-title="(c: Contact) => c.name || c.wa_id || c.email || 'Unknown'"
          item-value="id"
          label="Contact"
          placeholder="Search by name, phone, or email"
          :loading="contactSearchLoading"
          no-filter
        />
        <VTextField v-model="form.title" label="Title" density="compact" />
        <VSelect
          v-model="form.type" label="Type" density="compact"
          :items="[{ title: 'Call', value: 'call' }, { title: 'Meeting', value: 'meeting' }, { title: 'Follow-up', value: 'follow_up' }, { title: 'Other', value: 'other' }]"
        />
        <VTextField v-model="form.due_at" label="Due" type="datetime-local" density="compact" />
        <VSelect
          v-model="form.assigned_user_id" label="Assign to" density="compact" clearable
          :items="users.map(u => ({ title: u.full_name, value: u.id }))"
        />
        <VSelect
          v-model="form.recurrence" label="Recurrence" density="compact"
          :items="[{ title: 'None', value: 'none' }, { title: 'Daily', value: 'daily' }, { title: 'Weekly', value: 'weekly' }, { title: 'Monthly', value: 'monthly' }]"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!form.contact_id || !form.title.trim()" @click="save">
          Create
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
