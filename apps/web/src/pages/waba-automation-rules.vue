<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Rule = {
  id: string
  name: string
  trigger_type: 'keyword' | 'new_contact'
  trigger_value: string | null
  action_type: 'assign' | 'reply' | 'label'
  action_value: string
  active: boolean
  priority: number
}

type AssignableUser = { id: string, full_name: string, email: string }
type CannedResponse = { id: string, shortcut: string, body: string }
type Label = { id: string, scope: string, name: string, color: string }

const rules = ref<Rule[]>([])
const users = ref<AssignableUser[]>([])
const cannedResponses = ref<CannedResponse[]>([])
const conversationLabels = ref<Label[]>([])

const loading = ref(false)
const loadError = ref('')

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [ruleResult, userResult, cannedResult, labelResult] = await Promise.all([
      $api<Rule[]>('/v1/waba/automation-rules'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<CannedResponse[]>('/v1/waba/canned-responses'),
      $api<Label[]>('/v1/waba/labels', { params: { scope: 'conversation' } }),
    ])
    rules.value = ruleResult
    users.value = userResult
    cannedResponses.value = cannedResult
    conversationLabels.value = labelResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load automation rules.')
  }
  finally {
    loading.value = false
  }
}

function actionValueLabel(rule: Rule): string {
  if (rule.action_type === 'assign')
    return users.value.find(u => u.id === rule.action_value)?.full_name || rule.action_value
  if (rule.action_type === 'reply')
    return `/${cannedResponses.value.find(c => c.id === rule.action_value)?.shortcut || rule.action_value}`
  return conversationLabels.value.find(l => l.id === rule.action_value)?.name || rule.action_value
}

async function toggleActive(rule: Rule) {
  try {
    const updated = await $api<Rule>(`/v1/waba/automation-rules/${rule.id}`, {
      method: 'PUT',
      body: { name: rule.name, trigger_type: rule.trigger_type, trigger_value: rule.trigger_value, action_type: rule.action_type, action_value: rule.action_value, active: !rule.active, priority: rule.priority },
    })
    rule.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this rule.')
  }
}

async function deleteRule(rule: Rule) {
  try {
    await $api(`/v1/waba/automation-rules/${rule.id}`, { method: 'DELETE' })
    rules.value = rules.value.filter(r => r.id !== rule.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this rule.')
  }
}

// --- Create dialog ---

const createDialog = ref(false)
const createError = ref('')
const creating = ref(false)
const form = ref({
  name: '',
  trigger_type: 'keyword' as 'keyword' | 'new_contact',
  trigger_value: '',
  action_type: 'reply' as 'assign' | 'reply' | 'label',
  action_value: '',
  priority: 0,
})

const actionValueItems = computed(() => {
  if (form.value.action_type === 'assign')
    return users.value.map(u => ({ title: u.full_name, value: u.id }))
  if (form.value.action_type === 'reply')
    return cannedResponses.value.map(c => ({ title: `/${c.shortcut}`, value: c.id }))
  return conversationLabels.value.map(l => ({ title: l.name, value: l.id }))
})

function openCreateDialog() {
  form.value = { name: '', trigger_type: 'keyword', trigger_value: '', action_type: 'reply', action_value: '', priority: 0 }
  createError.value = ''
  createDialog.value = true
}

async function createRule() {
  if (!form.value.name.trim() || !form.value.action_value)
    return
  creating.value = true
  createError.value = ''
  try {
    const rule = await $api<Rule>('/v1/waba/automation-rules', {
      method: 'POST',
      body: {
        name: form.value.name.trim(),
        trigger_type: form.value.trigger_type,
        trigger_value: form.value.trigger_type === 'keyword' ? form.value.trigger_value.trim() : null,
        action_type: form.value.action_type,
        action_value: form.value.action_value,
        active: true,
        priority: form.value.priority,
      },
    })
    rules.value.push(rule)
    createDialog.value = false
  }
  catch (error: any) {
    createError.value = extractErrorMessage(error, 'Could not create this rule.')
  }
  finally {
    creating.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <h1 class="text-h4">
      Automation Rules
    </h1>
    <VBtn prepend-icon="tabler-plus" @click="openCreateDialog">
      New rule
    </VBtn>
  </div>
  <p class="text-medium-emphasis mb-6">
    Runs against every inbound WhatsApp message, in priority order (lowest first). A keyword
    trigger matches anywhere in the message text; a new-contact trigger fires once, the first
    time a number messages you.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Trigger</th>
          <th>Action</th>
          <th>Priority</th>
          <th>Active</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="rule in rules" :key="rule.id">
          <td>{{ rule.name }}</td>
          <td>{{ rule.trigger_type === 'keyword' ? `keyword: "${rule.trigger_value}"` : 'new contact' }}</td>
          <td>{{ rule.action_type }}: {{ actionValueLabel(rule) }}</td>
          <td>{{ rule.priority }}</td>
          <td>
            <VSwitch :model-value="rule.active" density="compact" hide-details @update:model-value="toggleActive(rule)" />
          </td>
          <td>
            <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteRule(rule)" />
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !rules.length" class="text-medium-emphasis text-center pa-6">
      No automation rules yet.
    </p>
  </VCard>

  <VDialog v-model="createDialog" max-width="480">
    <VCard>
      <VCardTitle>New automation rule</VCardTitle>
      <VCardText>
        <VAlert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ createError }}
        </VAlert>
        <AppTextField v-model="form.name" label="Rule name" class="mb-3" />
        <VSelect
          v-model="form.trigger_type"
          label="Trigger"
          :items="[{ title: 'Keyword in message', value: 'keyword' }, { title: 'New contact', value: 'new_contact' }]"
          class="mb-3"
        />
        <AppTextField v-if="form.trigger_type === 'keyword'" v-model="form.trigger_value" label="Keyword to match" class="mb-3" />
        <VSelect
          v-model="form.action_type"
          label="Action"
          :items="[{ title: 'Auto-reply with canned response', value: 'reply' }, { title: 'Assign to teammate', value: 'assign' }, { title: 'Add label', value: 'label' }]"
          class="mb-3"
          @update:model-value="form.action_value = ''"
        />
        <VSelect v-model="form.action_value" label="Value" :items="actionValueItems" class="mb-3" />
        <VTextField v-model.number="form.priority" type="number" label="Priority (lower runs first)" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="createDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="creating" @click="createRule">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
