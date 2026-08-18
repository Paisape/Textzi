<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type PipelineStage = { name: string, probability: number, forecast_category: 'pipeline' | 'commit' | 'omitted', required_fields: string[], required_approval_user_ids: string[] }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
type AssignableUser = { id: string, full_name: string }

const REQUIRED_FIELD_OPTIONS = [
  { title: 'Deal value', value: 'value' },
  { title: 'Probability', value: 'probability' },
  { title: 'Expected close date', value: 'expected_close_date' },
  { title: 'Owner', value: 'owner_user_id' },
]

const pipelines = ref<Pipeline[]>([])
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [pipelineResult, userResult] = await Promise.all([
      $api<Pipeline[]>('/v1/crm/pipelines'),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    pipelines.value = pipelineResult
    users.value = userResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load pipelines.')
  }
  finally {
    loading.value = false
  }
}

const forecastCategories = ['pipeline', 'commit', 'omitted']

const dialog = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ name: '', stages: [] as PipelineStage[] })
const stageNameInput = ref('')
const saving = ref(false)

function openCreate() {
  editingId.value = null
  form.name = ''
  form.stages = [
    { name: 'inquiry', probability: 10, forecast_category: 'pipeline', required_fields: [], required_approval_user_ids: [] },
    { name: 'kyc', probability: 30, forecast_category: 'pipeline', required_fields: [], required_approval_user_ids: [] },
    { name: 'onboarding', probability: 60, forecast_category: 'commit', required_fields: [], required_approval_user_ids: [] },
    { name: 'live', probability: 100, forecast_category: 'commit', required_fields: [], required_approval_user_ids: [] },
    { name: 'renewal', probability: 80, forecast_category: 'commit', required_fields: [], required_approval_user_ids: [] },
  ]
  stageNameInput.value = ''
  dialog.value = true
}

function openEdit(pipeline: Pipeline) {
  editingId.value = pipeline.id
  form.name = pipeline.name
  form.stages = pipeline.stages.map(s => ({ ...s, required_fields: [...(s.required_fields || [])], required_approval_user_ids: [...(s.required_approval_user_ids || [])] }))
  stageNameInput.value = ''
  dialog.value = true
}

function addStage() {
  const name = stageNameInput.value.trim().toLowerCase()
  if (name && !form.stages.some(s => s.name === name))
    form.stages.push({ name, probability: 50, forecast_category: 'pipeline', required_fields: [], required_approval_user_ids: [] })
  stageNameInput.value = ''
}

function removeStage(name: string) {
  form.stages = form.stages.filter(s => s.name !== name)
}

function moveStage(index: number, direction: -1 | 1) {
  const target = index + direction
  if (target < 0 || target >= form.stages.length)
    return
  const stages = [...form.stages]
  ;[stages[index], stages[target]] = [stages[target], stages[index]]
  form.stages = stages
}

async function save() {
  if (!form.name.trim() || !form.stages.length)
    return
  saving.value = true
  try {
    const body = { name: form.name.trim(), stages: form.stages }
    if (editingId.value) {
      const updated = await $api<Pipeline>(`/v1/crm/pipelines/${editingId.value}`, { method: 'PUT', body })
      const idx = pipelines.value.findIndex(p => p.id === editingId.value)
      if (idx !== -1)
        pipelines.value[idx] = updated
    }
    else {
      pipelines.value.push(await $api<Pipeline>('/v1/crm/pipelines', { method: 'POST', body }))
    }
    dialog.value = false
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save this pipeline.')
  }
  finally {
    saving.value = false
  }
}

async function remove(pipeline: Pipeline) {
  try {
    await $api(`/v1/crm/pipelines/${pipeline.id}`, { method: 'DELETE' })
    pipelines.value = pipelines.value.filter(p => p.id !== pipeline.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this pipeline — it may still have deals assigned to it.')
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Pipelines
      </h1>
      <p class="text-medium-emphasis">
        Named stage lists deals move through — each stage carries its own forecast probability.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New pipeline
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, deals, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VRow v-if="!crmInactive">
    <VCol v-for="pipeline in pipelines" :key="pipeline.id" cols="12" md="6" lg="4">
      <VCard>
        <VCardItem>
          <VCardTitle>{{ pipeline.name }}</VCardTitle>
          <template #append>
            <VBtn icon="tabler-pencil" variant="text" size="small" @click="openEdit(pipeline)" />
            <VBtn icon="tabler-trash" variant="text" size="small" color="error" @click="remove(pipeline)" />
          </template>
        </VCardItem>
        <VCardText>
          <div class="d-flex flex-wrap gap-2">
            <VChip v-for="stage in pipeline.stages" :key="stage.name" size="small">
              <VIcon v-if="stage.required_fields?.length" icon="tabler-lock" size="12" start />
              <VIcon v-if="stage.required_approval_user_ids?.length" icon="tabler-user-check" size="12" start />
              {{ formatLabel(stage.name) }} · {{ stage.probability }}%
            </VChip>
          </div>
        </VCardText>
      </VCard>
    </VCol>
    <VCol v-if="!loading && !pipelines.length" cols="12">
      <p class="text-medium-emphasis text-center pa-6">
        No pipelines yet.
      </p>
    </VCol>
  </VRow>

  <VDialog v-model="dialog" max-width="560" persistent>
    <VCard :title="editingId ? 'Edit pipeline' : 'New pipeline'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="form.name" label="Pipeline name" density="compact" />
        <VTextField
          v-model="stageNameInput" label="Add a stage" density="compact" hide-details
          @keydown.enter.prevent="addStage"
        >
          <template #append-inner>
            <VBtn size="small" variant="text" @click="addStage">
              Add
            </VBtn>
          </template>
        </VTextField>
        <div v-for="(stage, index) in form.stages" :key="stage.name" class="border rounded pa-2">
          <div class="d-flex align-center gap-3">
            <div class="d-flex flex-column">
              <VBtn icon="tabler-chevron-up" variant="text" size="x-small" :disabled="index === 0" @click="moveStage(index, -1)" />
              <VBtn icon="tabler-chevron-down" variant="text" size="x-small" :disabled="index === form.stages.length - 1" @click="moveStage(index, 1)" />
            </div>
            <span class="text-body-2" style="min-width: 100px;">{{ formatLabel(stage.name) }}</span>
            <VTextField
              v-model.number="stage.probability" label="Probability %" type="number" min="0" max="100"
              density="compact" hide-details style="max-width: 130px;"
            />
            <VSelect
              v-model="stage.forecast_category" :items="forecastCategories" label="Forecast"
              density="compact" hide-details style="max-width: 150px;"
            />
            <VBtn icon="tabler-x" variant="text" size="small" @click="removeStage(stage.name)" />
          </div>
          <VSelect
            v-model="stage.required_fields" :items="REQUIRED_FIELD_OPTIONS" label="Required to leave this stage (optional)"
            density="compact" hide-details multiple chips closable-chips class="mt-2"
          />
          <VSelect
            v-model="stage.required_approval_user_ids" :items="users.map(u => ({ title: u.full_name, value: u.id }))"
            label="Needs approval from (optional)" density="compact" hide-details multiple chips closable-chips class="mt-2"
          />
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!form.name.trim() || !form.stages.length" @click="save">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
