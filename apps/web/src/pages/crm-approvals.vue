<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type ApprovalStage = {
  id: string
  position: number
  approver_user_ids: string[]
  approver_names: string[]
  status: 'waiting' | 'pending' | 'approved' | 'rejected'
  approved_by_user_id: string | null
  approved_by_name: string | null
  approved_at: string | null
  comment: string | null
}
type ApprovalRequest = {
  id: string
  record_type: 'deal' | 'quote' | 'sales_invoice' | null
  record_id: string | null
  record_label: string | null
  title: string
  description: string | null
  requested_by_user_id: string
  requested_by_name: string | null
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  stages: ApprovalStage[]
  created_at: string
  resolved_at: string | null
}
type AssignableUser = { id: string, full_name: string }

const authStore = useAuthStore()
const requests = ref<ApprovalRequest[]>([])
const users = ref<AssignableUser[]>([])
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const actionError = ref('')
const busy = ref<string | null>(null)
const pendingMyActionOnly = ref(true)

const STATUS_COLORS: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'error', cancelled: 'default' }
const RECORD_ROUTES: Record<string, string> = { deal: '/crm-deals', quote: '/crm-quotes', sales_invoice: '/crm-quotes' }

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [requestResult, userResult] = await Promise.all([
      $api<ApprovalRequest[]>('/v1/crm/approvals', { params: pendingMyActionOnly.value ? { pending_my_action: true } : {} }),
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
    ])
    requests.value = requestResult
    users.value = userResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load approval requests.')
  }
  finally {
    loading.value = false
  }
}

watch(pendingMyActionOnly, loadAll)

function recordLink(request: ApprovalRequest) {
  if (!request.record_type || !request.record_id)
    return null
  return `${RECORD_ROUTES[request.record_type]}/${request.record_id}`
}

// --- New standalone request --------------------------------------------------------------------

const dialog = ref(false)
const form = reactive({
  title: '',
  description: '',
  stages: [{ approver_user_ids: [] as string[] }],
})
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  form.title = ''
  form.description = ''
  form.stages = [{ approver_user_ids: [] }]
  saveError.value = ''
  dialog.value = true
}

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
    const created = await $api<ApprovalRequest>('/v1/crm/approvals', {
      method: 'POST',
      body: { title: form.title.trim(), description: form.description.trim() || null, stages: form.stages },
    })
    requests.value.unshift(created)
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not create this approval request.')
  }
  finally {
    saving.value = false
  }
}

// --- Actions -------------------------------------------------------------------------------

const actionDialog = ref(false)
const actionTarget = ref<ApprovalRequest | null>(null)
const actionKind = ref<'approve' | 'reject'>('approve')
const actionComment = ref('')

function openAction(request: ApprovalRequest, kind: 'approve' | 'reject') {
  actionTarget.value = request
  actionKind.value = kind
  actionComment.value = ''
  actionDialog.value = true
}

async function confirmAction() {
  if (!actionTarget.value)
    return
  busy.value = actionTarget.value.id
  actionError.value = ''
  try {
    const updated = await $api<ApprovalRequest>(`/v1/crm/approvals/${actionTarget.value.id}/${actionKind.value}`, {
      method: 'POST',
      body: { comment: actionComment.value.trim() || null },
    })
    const index = requests.value.findIndex(r => r.id === updated.id)
    if (index !== -1) {
      if (pendingMyActionOnly.value && !updated.stages.some(s => s.status === 'pending'))
        requests.value.splice(index, 1)
      else
        requests.value[index] = updated
    }
    actionDialog.value = false
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, `Could not ${actionKind.value} this request.`)
  }
  finally {
    busy.value = null
  }
}

async function cancelRequest(request: ApprovalRequest) {
  busy.value = request.id
  actionError.value = ''
  try {
    const updated = await $api<ApprovalRequest>(`/v1/crm/approvals/${request.id}/cancel`, { method: 'POST' })
    const index = requests.value.findIndex(r => r.id === updated.id)
    if (index !== -1)
      requests.value[index] = updated
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not cancel this request.')
  }
  finally {
    busy.value = null
  }
}

function iCanAct(request: ApprovalRequest, userId: string | undefined) {
  if (request.status !== 'pending' || !userId)
    return false
  return request.stages.some(s => s.status === 'pending' && s.approver_user_ids.includes(userId))
}

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between flex-wrap gap-4 mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Approvals
      </h1>
      <p class="text-medium-emphasis">
        Internal sign-off requests — attach one to a Deal, Quote, or Invoice, or raise a
        standalone request. Never shown to the customer.
      </p>
    </div>
    <div class="d-flex align-center gap-4">
      <VCheckbox v-model="pendingMyActionOnly" label="Awaiting my action" density="compact" hide-details />
      <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
        New request
      </VBtn>
    </div>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use internal approvals.
    <RouterLink to="/channels-crm?tab=billing" class="font-weight-medium">
      View plans
    </RouterLink>
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>
  <VAlert v-if="actionError" type="error" variant="tonal" class="mb-4" closable @click:close="actionError = ''">
    {{ actionError }}
  </VAlert>

  <template v-if="!crmInactive">
    <VCard v-for="request in requests" :key="request.id" class="mb-4">
      <VCardText>
        <div class="d-flex align-center justify-space-between flex-wrap gap-2 mb-2">
          <div>
            <p class="text-subtitle-1 mb-0">
              {{ request.title }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              Requested by {{ request.requested_by_name || 'Unknown' }} · {{ new Date(request.created_at).toLocaleDateString() }}
              <template v-if="request.record_label">
                · <RouterLink v-if="recordLink(request)" :to="recordLink(request)!">
                  {{ request.record_label }}
                </RouterLink>
                <span v-else>{{ request.record_label }}</span>
              </template>
            </p>
          </div>
          <VChip size="small" :color="STATUS_COLORS[request.status]" variant="tonal">
            {{ request.status }}
          </VChip>
        </div>
        <p v-if="request.description" class="text-body-2 mb-3">
          {{ request.description }}
        </p>

        <div class="d-flex flex-wrap ga-2 mb-3">
          <VChip
            v-for="stage in request.stages" :key="stage.id" size="small" variant="tonal"
            :color="stage.status === 'approved' ? 'success' : stage.status === 'rejected' ? 'error' : stage.status === 'pending' ? 'warning' : undefined"
          >
            Stage {{ stage.position + 1 }}: {{ stage.approver_names.join(', ') || 'Unassigned' }}
            <span v-if="stage.status !== 'waiting' && stage.status !== 'pending'">
              — {{ stage.status }}{{ stage.approved_by_name ? ` by ${stage.approved_by_name}` : '' }}
            </span>
          </VChip>
        </div>
        <p v-for="stage in request.stages.filter(s => s.comment)" :key="`c-${stage.id}`" class="text-caption text-medium-emphasis mb-1">
          "{{ stage.comment }}" — {{ stage.approved_by_name }}
        </p>

        <div class="d-flex ga-2 justify-end">
          <VBtn
            v-if="request.requested_by_user_id === authStore.profile?.id && request.status === 'pending'"
            size="small" variant="text" :loading="busy === request.id" @click="cancelRequest(request)"
          >
            Cancel
          </VBtn>
          <template v-if="iCanAct(request, authStore.profile?.id)">
            <VBtn size="small" variant="tonal" color="error" @click="openAction(request, 'reject')">
              Reject
            </VBtn>
            <VBtn size="small" variant="tonal" color="success" @click="openAction(request, 'approve')">
              Approve
            </VBtn>
          </template>
        </div>
      </VCardText>
    </VCard>
    <p v-if="!loading && !requests.length" class="text-medium-emphasis text-center pa-6">
      {{ pendingMyActionOnly ? 'Nothing waiting on your approval.' : 'No approval requests yet.' }}
    </p>
  </template>

  <VDialog v-model="dialog" max-width="560" persistent>
    <VCard title="New approval request">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
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
          <p class="text-caption text-medium-emphasis mb-0">
            Stage 2 only opens once stage 1 is approved. Add one stage for a single-step approval,
            more for a chain (e.g. Manager, then Finance, then Board).
          </p>
        </div>
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!canSave" @click="save">
          Send for approval
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="actionDialog" max-width="420" persistent>
    <VCard :title="actionKind === 'approve' ? 'Approve this request' : 'Reject this request'">
      <VCardText class="d-flex flex-column gap-4">
        <p v-if="actionTarget" class="text-body-2 mb-0">
          {{ actionTarget.title }}
        </p>
        <VTextarea v-model="actionComment" label="Comment (optional)" rows="2" density="compact" />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="actionDialog = false">
          Cancel
        </VBtn>
        <VBtn :color="actionKind === 'approve' ? 'success' : 'error'" :loading="!!busy" @click="confirmAction">
          {{ actionKind === 'approve' ? 'Approve' : 'Reject' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
