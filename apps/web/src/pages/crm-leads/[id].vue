<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

import { addRecentlyViewed } from '@/composables/useRecentlyViewed'

const route = useRoute('crm-leads-id')
const router = useRouter()

type CrmContact = { id: string, name: string | null, phone: string | null, email: string | null, title: string | null, company_id: string | null }
type Lead = {
  id: string
  contact: CrmContact
  company_name: string | null
  source: string
  status: 'new' | 'contacted' | 'qualified' | 'unqualified' | 'converted'
  owner_user_id: string | null
  notes: string | null
  custom_fields: Record<string, any>
  score: number
  converted_at: string | null
  converted_deal_id: string | null
  created_at: string
}
type Company = { id: string, name: string, industry: string | null, open_deal_value: number, won_deal_value: number, open_deal_count: number }
type Task = { id: string, title: string, type: string, due_at: string | null, done: boolean, priority: string }
type ActivityMessage = { id: string, channel: string, direction: 'inbound' | 'outbound', message_type: string, body: string | null, created_at: string }
type LeadDetail = { lead: Lead, company: Company | null, tasks: Task[], waba_contact_id: string | null, recent_messages: ActivityMessage[] }
type AssignableUser = { id: string, full_name: string }

const detail = ref<LeadDetail | null>(null)
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [detailResult, userResult] = await Promise.all([
      $api<LeadDetail>(`/v1/crm/leads/${route.params.id}`),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    detail.value = detailResult
    users.value = userResult
    addRecentlyViewed({
      type: 'lead', id: detailResult.lead.id,
      label: detailResult.lead.contact.name || detailResult.lead.contact.phone || detailResult.lead.contact.email || 'Unknown',
      sublabel: detailResult.lead.company_name,
    })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this lead.')
  }
  finally {
    loading.value = false
  }
}

function initial() {
  const c = detail.value?.lead.contact
  return (c?.name || c?.phone || c?.email || '?').slice(0, 1).toUpperCase()
}

function formatActivityTime(iso: string) {
  return new Date(iso).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

function ownerName(ownerUserId: string | null) {
  return users.value.find(u => u.id === ownerUserId)?.full_name || 'Unassigned'
}

async function updateNotes(notes: string) {
  if (!detail.value)
    return
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${detail.value.lead.id}`, { method: 'PATCH', body: { notes } })
    detail.value.lead = updated
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not save notes.')
  }
}

async function updateOwner(ownerUserId: string | null) {
  if (!detail.value)
    return
  try {
    const updated = await $api<Lead>(`/v1/crm/leads/${detail.value.lead.id}`, { method: 'PATCH', body: { owner_user_id: ownerUserId } })
    detail.value.lead = updated
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reassign this lead.')
  }
}

// --- Convert to deal (same shape as the list page's dialog) --------------------------------

type PipelineStage = { name: string, probability: number, forecast_category: string }
type Pipeline = { id: string, name: string, stages: PipelineStage[] }
const pipelines = ref<Pipeline[]>([])
const convertDialog = ref(false)
const convertForm = reactive({ deal_name: '', pipeline_id: null as string | null, stage: 'inquiry', value: null as number | null, probability: null as number | null, expected_close_date: '' })
const converting = ref(false)

async function openConvertDialog() {
  if (!pipelines.value.length)
    pipelines.value = await $api<Pipeline[]>('/v1/crm/pipelines')
  const defaultPipeline = pipelines.value[0] || null
  convertForm.deal_name = ''
  convertForm.pipeline_id = defaultPipeline?.id || null
  convertForm.stage = defaultPipeline?.stages[0]?.name || 'inquiry'
  convertForm.value = null
  convertForm.probability = defaultPipeline?.stages[0]?.probability ?? null
  convertForm.expected_close_date = ''
  convertDialog.value = true
}

async function confirmConvert() {
  if (!detail.value)
    return
  converting.value = true
  try {
    const deal = await $api<{ id: string }>(`/v1/crm/leads/${detail.value.lead.id}/convert`, {
      method: 'POST',
      body: {
        deal_name: convertForm.deal_name.trim() || null,
        pipeline_id: convertForm.pipeline_id,
        stage: convertForm.stage,
        value: convertForm.value,
        probability: convertForm.probability,
        expected_close_date: convertForm.expected_close_date || null,
      },
    })
    convertDialog.value = false
    router.push(`/crm-deals/${deal.id}`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not convert this lead to a deal.')
  }
  finally {
    converting.value = false
  }
}

// --- Delete ----------------------------------------------------------------------------------

const deleting = ref(false)

async function deleteLead() {
  if (!detail.value)
    return
  deleting.value = true
  try {
    await $api(`/v1/crm/leads/${detail.value.lead.id}`, { method: 'DELETE' })
    router.push({ name: 'crm-leads' })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this lead.')
  }
  finally {
    deleting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="d-flex align-center gap-3 mb-4">
    <VBtn icon="tabler-arrow-left" variant="text" :to="{ name: 'crm-leads' }" />
    <h1 class="text-h5 mb-0">
      Lead
    </h1>
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate class="mb-4" />

  <VRow v-if="detail">
    <VCol cols="12" md="8">
      <VCard class="mb-4">
        <VCardText class="d-flex align-center gap-4">
          <VAvatar color="primary" variant="tonal" size="56">
            <span class="text-h6">{{ initial() }}</span>
          </VAvatar>
          <div class="flex-grow-1">
            <p class="text-h6 mb-0">
              {{ detail.lead.contact.name || detail.lead.contact.phone || detail.lead.contact.email || 'Unknown' }}
            </p>
            <p v-if="detail.lead.contact.title" class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.lead.contact.title }}
            </p>
            <p class="text-body-2 text-medium-emphasis mb-0">
              {{ detail.lead.contact.phone || detail.lead.contact.email || '—' }}
            </p>
          </div>
          <VChip v-if="detail.lead.status === 'converted'" color="primary" size="small">
            converted
          </VChip>
          <VChip v-else size="small">
            {{ detail.lead.status }}
          </VChip>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex flex-wrap gap-3">
          <RouterLink v-if="detail.company" :to="`/crm-companies/${detail.company.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-building" size="16" />
            {{ detail.company.name }}
          </RouterLink>
          <RouterLink :to="`/crm-contacts/${detail.lead.contact.id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-user" size="16" />
            View contact
          </RouterLink>
          <RouterLink v-if="detail.waba_contact_id" :to="`/waba-customers/${detail.waba_contact_id}`" class="d-flex align-center gap-2 text-body-2">
            <VIcon icon="tabler-brand-whatsapp" size="16" />
            View WhatsApp conversation
          </RouterLink>
          <span class="d-flex align-center gap-2 text-body-2 text-medium-emphasis">
            <VIcon icon="tabler-target-arrow" size="16" />
            Score {{ detail.lead.score }}
          </span>
        </VCardText>
      </VCard>

      <VCard class="mb-4" title="Activity">
        <VList v-if="detail.recent_messages.length" density="compact">
          <VListItem v-for="m in detail.recent_messages" :key="m.id">
            <template #prepend>
              <VIcon :icon="m.channel === 'email' ? 'tabler-mail' : 'tabler-brand-whatsapp'" size="16" :color="m.channel === 'email' ? undefined : 'success'" />
            </template>
            <VListItemTitle class="text-wrap">
              {{ m.body || `[${m.message_type}]` }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ m.direction === 'outbound' ? 'Sent' : 'Received' }} · {{ formatActivityTime(m.created_at) }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No WhatsApp or email activity yet.
        </p>
      </VCard>

      <VCard class="mb-4" title="Notes">
        <VCardText>
          <VTextarea
            :model-value="detail.lead.notes || ''" rows="3" density="compact" placeholder="Add notes about this lead..."
            @blur="(e: FocusEvent) => updateNotes((e.target as HTMLTextAreaElement).value)"
          />
        </VCardText>
      </VCard>

      <VCard title="Tasks">
        <VList v-if="detail.tasks.length" density="compact">
          <VListItem v-for="task in detail.tasks" :key="task.id">
            <VListItemTitle :class="task.done ? 'text-decoration-line-through text-medium-emphasis' : ''">
              {{ task.title }}
            </VListItemTitle>
            <VListItemSubtitle>
              {{ task.type }} · {{ task.due_at ? new Date(task.due_at).toLocaleDateString() : 'no due date' }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6">
          No tasks yet.
        </p>
      </VCard>
    </VCol>

    <VCol cols="12" md="4">
      <VCard class="mb-4" title="Details">
        <VCardText class="d-flex flex-column gap-4">
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Company
            </p>
            <p class="mb-0">
              {{ detail.lead.company_name || '—' }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Source
            </p>
            <p class="mb-0">
              {{ formatLabel(detail.lead.source) }}
            </p>
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Owner
            </p>
            <VSelect
              :model-value="detail.lead.owner_user_id"
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
              placeholder="Unassigned" density="compact" hide-details clearable
              @update:model-value="updateOwner"
            />
          </div>
          <div>
            <p class="text-caption text-medium-emphasis mb-1">
              Created
            </p>
            <p class="mb-0">
              {{ new Date(detail.lead.created_at).toLocaleDateString() }}
            </p>
          </div>
        </VCardText>
      </VCard>

      <VCard title="Actions">
        <VCardText class="d-flex flex-column gap-3">
          <VBtn v-if="detail.lead.status !== 'converted'" color="primary" block @click="openConvertDialog">
            Convert to deal
          </VBtn>
          <VBtn v-else block variant="tonal" :to="`/crm-deals/${detail.lead.converted_deal_id}`">
            View deal
          </VBtn>
          <VBtn
            v-if="detail.lead.status !== 'converted'" color="error" variant="tonal" block :loading="deleting"
            @click="deleteLead"
          >
            Delete lead
          </VBtn>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>

  <VDialog v-model="convertDialog" max-width="420" persistent>
    <VCard title="Convert to deal">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="convertDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VTextField v-model="convertForm.deal_name" label="Deal name (optional -- defaults to contact name)" density="compact" />
        <VSelect
          v-model="convertForm.pipeline_id"
          :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
          label="Pipeline" density="compact"
        />
        <VSelect
          v-model="convertForm.stage"
          :items="(pipelines.find(p => p.id === convertForm.pipeline_id)?.stages || []).map(s => ({ title: formatLabel(s.name), value: s.name }))"
          label="Stage" density="compact"
        />
        <VTextField v-model.number="convertForm.value" label="Deal value (INR)" type="number" min="0" density="compact" />
        <VTextField v-model.number="convertForm.probability" label="Probability (%)" type="number" min="0" max="100" density="compact" />
        <VTextField v-model="convertForm.expected_close_date" label="Expected close date" type="date" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="convertDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="converting" @click="confirmConvert">
          Convert
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
