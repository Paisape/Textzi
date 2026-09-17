<script setup lang="ts">
// Reusable "Request approval" dialog -- attaches an internal ApprovalRequest to whatever record
// (deal/quote/sales_invoice) the host page passes in, or works standalone if recordType/recordId
// are omitted. Shared by the Deal detail page, the Quotes page, and anywhere else that needs to
// attach an approval without duplicating the create-request form three times.
const props = defineProps<{
  modelValue: boolean
  recordType?: 'deal' | 'quote' | 'sales_invoice' | 'ticket'
  recordId?: string
  defaultTitle?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void, (e: 'created'): void }>()

type AssignableUser = { id: string, full_name: string }
const users = ref<AssignableUser[]>([])

const form = reactive({
  title: '',
  description: '',
  stages: [{ approver_user_ids: [] as string[] }],
})
const saving = ref(false)
const saveError = ref('')

watch(() => props.modelValue, async (open) => {
  if (!open)
    return
  form.title = props.defaultTitle || ''
  form.description = ''
  form.stages = [{ approver_user_ids: [] }]
  saveError.value = ''
  if (!users.value.length) {
    try {
      users.value = await $api<AssignableUser[]>('/v1/waba/assignable-users')
    }
    catch {
      // Approver picker just shows empty if this fails -- not fatal to opening the dialog.
    }
  }
})

function addStage() {
  form.stages.push({ approver_user_ids: [] })
}

function removeStage(index: number) {
  if (form.stages.length > 1)
    form.stages.splice(index, 1)
}

const canSave = computed(() => form.title.trim() && form.stages.every(s => s.approver_user_ids.length))

async function save() {
  if (!canSave.value)
    return
  saving.value = true
  saveError.value = ''
  try {
    await $api('/v1/crm/approvals', {
      method: 'POST',
      body: {
        record_type: props.recordType || null, record_id: props.recordId || null,
        title: form.title.trim(), description: form.description.trim() || null, stages: form.stages,
      },
    })
    emit('created')
    emit('update:modelValue', false)
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not create this approval request.')
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <VDialog :model-value="modelValue" max-width="560" persistent @update:model-value="(v: boolean) => emit('update:modelValue', v)">
    <VCard title="Request approval">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="emit('update:modelValue', false)" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <p class="text-caption text-medium-emphasis mb-0">
          Internal only -- never shown to the customer.
        </p>
        <VTextField v-model="form.title" label="What are you asking for?" density="compact" autofocus />
        <VTextarea v-model="form.description" label="Details (optional)" rows="2" density="compact" />

        <div>
          <div class="d-flex align-center justify-space-between mb-2">
            <span class="text-subtitle-2">Approval stages (in order)</span>
            <VBtn size="small" variant="text" prepend-icon="tabler-plus" @click="addStage">
              Add stage
            </VBtn>
          </div>
          <div v-for="(stage, index) in form.stages" :key="index" class="d-flex ga-2 align-start mb-2">
            <span class="text-caption text-medium-emphasis pt-3">
              {{ index + 1 }}.
            </span>
            <VSelect
              v-model="stage.approver_user_ids" label="Approver(s) — any one can approve this stage"
              multiple chips closable-chips density="compact" style="flex: 1;"
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
            />
            <VBtn icon="tabler-x" size="small" variant="text" :disabled="form.stages.length === 1" @click="removeStage(index)" />
          </div>
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="emit('update:modelValue', false)">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!canSave" @click="save">
          Send for approval
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
