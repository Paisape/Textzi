<script setup lang="ts">
type MacroAction = { type: 'reply' | 'label' | 'status' | 'assign', value: string | null }
type Macro = { id: string, name: string, actions: MacroAction[], created_at: string }
type CannedResponse = { id: string, shortcut: string, body: string }
type Label = { id: string, scope: string, name: string, color: string }
type AssignableUser = { id: string, full_name: string, email: string }

const macros = ref<Macro[]>([])
const cannedResponses = ref<CannedResponse[]>([])
const conversationLabels = ref<Label[]>([])
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [macroResult, cannedResult, labelResult, userResult] = await Promise.all([
      $api<Macro[]>('/v1/waba/macros'),
      $api<CannedResponse[]>('/v1/waba/canned-responses'),
      $api<Label[]>('/v1/waba/labels', { params: { scope: 'conversation' } }),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    macros.value = macroResult
    cannedResponses.value = cannedResult
    conversationLabels.value = labelResult
    users.value = userResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load macros.')
  }
  finally {
    loading.value = false
  }
}

function actionValueLabel(action: MacroAction) {
  if (action.type === 'reply')
    return `/${cannedResponses.value.find(c => c.id === action.value)?.shortcut || action.value}`
  if (action.type === 'label')
    return conversationLabels.value.find(l => l.id === action.value)?.name || action.value
  if (action.type === 'assign')
    return users.value.find(u => u.id === action.value)?.full_name || 'Unassigned'
  return action.value
}

const dialog = ref(false)
const dialogError = ref('')
const saving = ref(false)
const form = ref({ name: '', actions: [] as MacroAction[] })

function openDialog() {
  form.value = { name: '', actions: [] }
  dialogError.value = ''
  dialog.value = true
}

function addAction() {
  form.value.actions.push({ type: 'reply', value: null })
}

function removeAction(i: number) {
  form.value.actions.splice(i, 1)
}

function actionValueItems(type: string) {
  if (type === 'reply')
    return cannedResponses.value.map(c => ({ title: `/${c.shortcut}`, value: c.id }))
  if (type === 'label')
    return conversationLabels.value.map(l => ({ title: l.name, value: l.id }))
  if (type === 'assign')
    return [{ title: 'Unassigned', value: '' }, ...users.value.map(u => ({ title: u.full_name, value: u.id }))]
  return [{ title: 'Open', value: 'open' }, { title: 'Pending', value: 'pending' }, { title: 'Resolved', value: 'resolved' }]
}

async function createMacro() {
  if (!form.value.name.trim() || !form.value.actions.length)
    return
  saving.value = true
  dialogError.value = ''
  try {
    const macro = await $api<Macro>('/v1/waba/macros', { method: 'POST', body: { name: form.value.name.trim(), actions: form.value.actions } })
    macros.value.push(macro)
    dialog.value = false
  }
  catch (error: any) {
    dialogError.value = extractErrorMessage(error, 'Could not create this macro.')
  }
  finally {
    saving.value = false
  }
}

async function deleteMacro(macro: Macro) {
  try {
    await $api(`/v1/waba/macros/${macro.id}`, { method: 'DELETE' })
    macros.value = macros.value.filter(m => m.id !== macro.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this macro.')
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-4">
    <p class="text-body-2 text-medium-emphasis mb-0">
      A bundle of actions an agent runs on a conversation in one click, from the inbox.
    </p>
    <VBtn prepend-icon="tabler-plus" @click="openDialog">
      New macro
    </VBtn>
  </div>
  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>
  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Name</th>
          <th>Actions</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="macro in macros" :key="macro.id">
          <td>{{ macro.name }}</td>
          <td>
            <VChip v-for="(action, i) in macro.actions" :key="i" size="small" class="mr-1 mb-1">
              {{ action.type }}: {{ actionValueLabel(action) }}
            </VChip>
          </td>
          <td>
            <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteMacro(macro)" />
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !macros.length" class="text-medium-emphasis text-center pa-6">
      No macros yet.
    </p>
  </VCard>

  <VDialog v-model="dialog" max-width="520">
    <VCard>
      <VCardTitle>New macro</VCardTitle>
      <VCardText>
        <VAlert v-if="dialogError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ dialogError }}
        </VAlert>
        <AppTextField v-model="form.name" label="Macro name" class="mb-3" />
        <div v-for="(action, i) in form.actions" :key="i" class="d-flex align-center ga-2 mb-2">
          <VSelect
            v-model="action.type"
            :items="[{ title: 'Reply', value: 'reply' }, { title: 'Add label', value: 'label' }, { title: 'Set status', value: 'status' }, { title: 'Assign', value: 'assign' }]"
            density="compact"
            hide-details
            style="max-width: 140px;"
            @update:model-value="action.value = null"
          />
          <VSelect v-model="action.value" :items="actionValueItems(action.type)" density="compact" hide-details />
          <VBtn size="small" variant="text" icon="tabler-trash" @click="removeAction(i)" />
        </div>
        <VBtn size="small" variant="text" prepend-icon="tabler-plus" @click="addAction">
          Add action
        </VBtn>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="saving" @click="createMacro">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
