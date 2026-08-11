<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type Pipeline = { id: string, name: string, stages: string[] }

const pipelines = ref<Pipeline[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    pipelines.value = await $api<Pipeline[]>('/v1/crm/pipelines')
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

const dialog = ref(false)
const editingId = ref<string | null>(null)
const form = reactive({ name: '', stages: [] as string[] })
const stageInput = ref('')
const saving = ref(false)

function openCreate() {
  editingId.value = null
  form.name = ''
  form.stages = ['inquiry', 'kyc', 'onboarding', 'live', 'renewal']
  stageInput.value = ''
  dialog.value = true
}

function openEdit(pipeline: Pipeline) {
  editingId.value = pipeline.id
  form.name = pipeline.name
  form.stages = [...pipeline.stages]
  stageInput.value = ''
  dialog.value = true
}

function addStage() {
  const stage = stageInput.value.trim().toLowerCase()
  if (stage && !form.stages.includes(stage))
    form.stages.push(stage)
  stageInput.value = ''
}

function removeStage(stage: string) {
  form.stages = form.stages.filter(s => s !== stage)
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
    loadError.value = extractErrorMessage(error, 'Could not delete this pipeline — it may still have leads assigned to it.')
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
        Named stage lists leads move through — e.g. separate pipelines for new business vs renewals.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New pipeline
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
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
            <VChip v-for="stage in pipeline.stages" :key="stage" size="small" class="text-capitalize">
              {{ stage }}
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

  <VDialog v-model="dialog" max-width="480">
    <VCard :title="editingId ? 'Edit pipeline' : 'New pipeline'">
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="form.name" label="Pipeline name" density="compact" />
        <div>
          <VTextField
            v-model="stageInput" label="Add a stage" density="compact" hide-details
            @keydown.enter.prevent="addStage"
          >
            <template #append-inner>
              <VBtn size="small" variant="text" @click="addStage">
                Add
              </VBtn>
            </template>
          </VTextField>
          <div class="d-flex flex-wrap gap-2 mt-3">
            <VChip v-for="stage in form.stages" :key="stage" size="small" closable class="text-capitalize" @click:close="removeStage(stage)">
              {{ stage }}
            </VChip>
          </div>
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
