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
type ApprovalDocument = {
  id: string
  version_group_id: string
  version_number: number
  filename: string
  content_type: string
  size: number
  uploaded_by_user_id: string | null
  uploaded_by_name: string | null
  created_at: string
}
type ApprovalActivity = { id: string, user_id: string | null, user_name: string | null, kind: string, detail: string, created_at: string }
type ApprovalRequest = {
  id: string
  record_type: 'deal' | 'quote' | 'sales_invoice' | 'ticket' | 'policy' | null
  record_id: string | null
  record_label: string | null
  title: string
  description: string | null
  requested_by_user_id: string
  requested_by_name: string | null
  status: 'pending' | 'approved' | 'rejected' | 'cancelled'
  stages: ApprovalStage[]
  documents: ApprovalDocument[]
  activity: ApprovalActivity[]
  created_at: string
  resolved_at: string | null
}
type AssignableUser = { id: string, full_name: string }

function isPreviewable(contentType: string) {
  return contentType.startsWith('image/') || contentType === 'application/pdf'
}

function formatFileSize(bytes: number) {
  if (bytes < 1024)
    return `${bytes} B`
  if (bytes < 1024 * 1024)
    return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// Groups a request's flat document list into { version_group_id -> versions[] }, newest first
// within each group -- the detail view shows one row per document with its own revision history
// expandable underneath, not a flat pile of every upload ever made.
function documentGroups(request: ApprovalRequest) {
  const groups = new Map<string, ApprovalDocument[]>()
  for (const doc of request.documents) {
    if (!groups.has(doc.version_group_id))
      groups.set(doc.version_group_id, [])
    groups.get(doc.version_group_id)!.push(doc)
  }
  return [...groups.values()].map(versions => versions.slice().sort((a, b) => b.version_number - a.version_number))
}

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
// Tickets have no routable per-record URL (tickets.vue is a single in-page list+detail toggle,
// not addressed by id) -- linking to the list is the honest option rather than faking a deep link
// that doesn't exist.
const TICKET_LIST_ROUTE = '/tickets'

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
  if (request.record_type === 'ticket')
    return TICKET_LIST_ROUTE
  return `${RECORD_ROUTES[request.record_type]}/${request.record_id}`
}

// --- New standalone request --------------------------------------------------------------------

const dialog = ref(false)
const form = reactive({
  title: '',
  description: '',
  stages: [{ approver_user_ids: [] as string[] }],
  files: [] as File[],
})
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  form.title = ''
  form.description = ''
  form.stages = [{ approver_user_ids: [] }]
  form.files = []
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
    for (const file of form.files) {
      try {
        const doc = await uploadDocumentFile(created.id, file)
        created.documents.push(doc)
      }
      catch {
        // The request itself is already created and safe -- a failed attachment here just means
        // one fewer document on it; the detail view (opened next) still lets the user retry.
      }
    }
    if (form.files.length) {
      const refreshed = await $api<ApprovalRequest>(`/v1/crm/approvals/${created.id}`)
      Object.assign(created, refreshed)
    }
    requests.value.unshift(created)
    dialog.value = false
    openDetail(created)
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
    if (detailRequest.value?.id === updated.id)
      detailRequest.value = updated
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
    if (detailRequest.value?.id === updated.id)
      detailRequest.value = updated
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

// --- Detail dialog (documents + full timeline) ------------------------------------------------

const detailDialog = ref(false)
const detailRequest = ref<ApprovalRequest | null>(null)

function openDetail(request: ApprovalRequest) {
  detailRequest.value = request
  detailDialog.value = true
}

const uploadingDocument = ref(false)
const documentError = ref('')

async function uploadDocumentFile(requestId: string, file: File, versionGroupId?: string): Promise<ApprovalDocument> {
  const formData = new FormData()
  formData.append('file', file)
  const params = versionGroupId ? `?version_group_id=${versionGroupId}` : ''
  return $api<ApprovalDocument>(`/v1/crm/approvals/${requestId}/documents${params}`, { method: 'POST', body: formData })
}

async function uploadDocument(event: Event, versionGroupId?: string) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !detailRequest.value)
    return
  uploadingDocument.value = true
  documentError.value = ''
  try {
    const created = await uploadDocumentFile(detailRequest.value.id, file, versionGroupId)
    detailRequest.value.documents.push(created)
    const index = requests.value.findIndex(r => r.id === detailRequest.value!.id)
    if (index !== -1)
      requests.value[index] = detailRequest.value
    // Re-fetch to pick up the new activity-log entry the upload just created server-side.
    const refreshed = await $api<ApprovalRequest>(`/v1/crm/approvals/${detailRequest.value.id}`)
    detailRequest.value = refreshed
    if (index !== -1)
      requests.value[index] = refreshed
  }
  catch (error: any) {
    documentError.value = extractErrorMessage(error, 'Could not upload this document.')
  }
  finally {
    uploadingDocument.value = false
    input.value = ''
  }
}

const downloadingDocument = ref<string | null>(null)

async function downloadDocument(doc: ApprovalDocument) {
  if (!detailRequest.value)
    return
  downloadingDocument.value = doc.id
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/approvals/${detailRequest.value.id}/documents/${doc.id}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = doc.filename
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    documentError.value = extractErrorMessage(error, 'Could not download this document.')
  }
  finally {
    downloadingDocument.value = null
  }
}

const previewDialog = ref(false)
const previewUrl = ref('')
const previewType = ref<'image' | 'pdf'>('image')
const previewFilename = ref('')

async function previewDocument(doc: ApprovalDocument) {
  if (!detailRequest.value)
    return
  downloadingDocument.value = doc.id
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/crm/approvals/${detailRequest.value.id}/documents/${doc.id}/download`, { responseType: 'blob' })
    if (previewUrl.value)
      URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = URL.createObjectURL(blob)
    previewType.value = doc.content_type === 'application/pdf' ? 'pdf' : 'image'
    previewFilename.value = doc.filename
    previewDialog.value = true
  }
  catch (error: any) {
    documentError.value = extractErrorMessage(error, 'Could not open this document.')
  }
  finally {
    downloadingDocument.value = null
  }
}

async function removeDocument(doc: ApprovalDocument) {
  if (!detailRequest.value)
    return
  downloadingDocument.value = doc.id
  try {
    await $api(`/v1/crm/approvals/${detailRequest.value.id}/documents/${doc.id}`, { method: 'DELETE' })
    const refreshed = await $api<ApprovalRequest>(`/v1/crm/approvals/${detailRequest.value.id}`)
    detailRequest.value = refreshed
    const index = requests.value.findIndex(r => r.id === refreshed.id)
    if (index !== -1)
      requests.value[index] = refreshed
  }
  catch (error: any) {
    documentError.value = extractErrorMessage(error, 'Could not remove this document.')
  }
  finally {
    downloadingDocument.value = null
  }
}

const ACTIVITY_ICON: Record<string, string> = {
  created: 'tabler-plus',
  document_attached: 'tabler-paperclip',
  document_revised: 'tabler-history',
  document_removed: 'tabler-trash',
  stage_approved: 'tabler-circle-check',
  stage_rejected: 'tabler-circle-x',
  cancelled: 'tabler-ban',
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

        <div class="d-flex align-center justify-space-between flex-wrap ga-2">
          <span v-if="request.documents.length" class="d-flex align-center ga-1 text-caption text-medium-emphasis">
            <VIcon icon="tabler-paperclip" size="14" />
            {{ documentGroups(request).length }} document{{ documentGroups(request).length === 1 ? '' : 's' }}
          </span>
          <span v-else />
          <div class="d-flex ga-2">
            <VBtn size="small" variant="text" @click="openDetail(request)">
              View details
            </VBtn>
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
        <VFileInput
          v-model="form.files" label="Attach documents (optional)" density="compact" multiple chips closable-chips
          accept=".pdf,.jpg,.jpeg,.png" prepend-icon="tabler-paperclip"
        />

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

  <VDialog v-model="detailDialog" max-width="720">
    <VCard v-if="detailRequest" :title="detailRequest.title">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="detailDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="documentError" type="error" variant="tonal" density="compact" closable @click:close="documentError = ''">
          {{ documentError }}
        </VAlert>

        <div class="d-flex align-center justify-space-between flex-wrap gap-2">
          <p class="text-caption text-medium-emphasis mb-0">
            Requested by {{ detailRequest.requested_by_name || 'Unknown' }} · {{ new Date(detailRequest.created_at).toLocaleString() }}
            <template v-if="detailRequest.record_label">
              · <RouterLink v-if="recordLink(detailRequest)" :to="recordLink(detailRequest)!">
                {{ detailRequest.record_label }}
              </RouterLink>
              <span v-else>{{ detailRequest.record_label }}</span>
            </template>
          </p>
          <VChip size="small" :color="STATUS_COLORS[detailRequest.status]" variant="tonal">
            {{ detailRequest.status }}
          </VChip>
        </div>
        <p v-if="detailRequest.description" class="text-body-2 mb-0">
          {{ detailRequest.description }}
        </p>

        <div>
          <p class="text-subtitle-2 mb-2">
            Approval stages
          </p>
          <div class="d-flex flex-column ga-2">
            <div v-for="stage in detailRequest.stages" :key="stage.id" class="d-flex align-center ga-2">
              <VChip
                size="small" variant="tonal"
                :color="stage.status === 'approved' ? 'success' : stage.status === 'rejected' ? 'error' : stage.status === 'pending' ? 'warning' : undefined"
              >
                Stage {{ stage.position + 1 }}: {{ stage.approver_names.join(', ') || 'Unassigned' }}
              </VChip>
              <span v-if="stage.status !== 'waiting' && stage.status !== 'pending'" class="text-caption text-medium-emphasis">
                {{ stage.status }} by {{ stage.approved_by_name }} on {{ new Date(stage.approved_at!).toLocaleString() }}
                <template v-if="stage.comment">
                  — "{{ stage.comment }}"
                </template>
              </span>
            </div>
          </div>
        </div>

        <div>
          <div class="d-flex align-center justify-space-between mb-2">
            <p class="text-subtitle-2 mb-0">
              Documents
            </p>
            <VBtn size="small" variant="text" prepend-icon="tabler-upload" :loading="uploadingDocument">
              Attach
              <input type="file" accept=".pdf,.jpg,.jpeg,.png" style="position: absolute; inset: 0; opacity: 0; cursor: pointer;" @change="uploadDocument($event)">
            </VBtn>
          </div>
          <VCard v-for="group in documentGroups(detailRequest)" :key="group[0].version_group_id" variant="outlined" class="mb-2">
            <VCardText class="d-flex align-center justify-space-between flex-wrap ga-2 py-2">
              <div class="d-flex align-center ga-2">
                <VIcon icon="tabler-file" size="18" />
                <div>
                  <p class="text-body-2 mb-0">
                    {{ group[0].filename }}
                    <VChip v-if="group.length > 1" size="x-small" variant="tonal" class="ml-1">
                      v{{ group[0].version_number }}
                    </VChip>
                  </p>
                  <p class="text-caption text-medium-emphasis mb-0">
                    {{ formatFileSize(group[0].size) }} · {{ group[0].uploaded_by_name || 'Unknown' }} · {{ new Date(group[0].created_at).toLocaleString() }}
                  </p>
                </div>
              </div>
              <div class="d-flex align-center ga-1">
                <VBtn
                  v-if="isPreviewable(group[0].content_type)" icon="tabler-eye" size="small" variant="text"
                  :loading="downloadingDocument === group[0].id" title="Preview" @click="previewDocument(group[0])"
                />
                <VBtn icon="tabler-download" size="small" variant="text" :loading="downloadingDocument === group[0].id" title="Download" @click="downloadDocument(group[0])" />
                <VBtn size="small" variant="text" style="position: relative;" title="Upload a new revision">
                  <VIcon icon="tabler-history" />
                  <input
                    type="file" accept=".pdf,.jpg,.jpeg,.png" style="position: absolute; inset: 0; opacity: 0; cursor: pointer;"
                    @change="uploadDocument($event, group[0].version_group_id)"
                  >
                </VBtn>
                <VBtn icon="tabler-trash" size="small" variant="text" :loading="downloadingDocument === group[0].id" title="Remove" @click="removeDocument(group[0])" />
              </div>
            </VCardText>
            <template v-if="group.length > 1">
              <VDivider />
              <VCardText class="py-2">
                <p class="text-caption text-medium-emphasis mb-1">
                  Earlier revisions
                </p>
                <div v-for="doc in group.slice(1)" :key="doc.id" class="d-flex align-center justify-space-between">
                  <span class="text-caption">v{{ doc.version_number }} — {{ doc.uploaded_by_name }} · {{ new Date(doc.created_at).toLocaleString() }}</span>
                  <div class="d-flex ga-1">
                    <VBtn v-if="isPreviewable(doc.content_type)" icon="tabler-eye" size="x-small" variant="text" @click="previewDocument(doc)" />
                    <VBtn icon="tabler-download" size="x-small" variant="text" @click="downloadDocument(doc)" />
                  </div>
                </div>
              </VCardText>
            </template>
          </VCard>
          <p v-if="!detailRequest.documents.length" class="text-caption text-medium-emphasis mb-0">
            No documents attached yet.
          </p>
        </div>

        <div>
          <p class="text-subtitle-2 mb-2">
            Full timeline
          </p>
          <VTimeline density="compact" side="end" truncate-line="both" line-inset="8">
            <VTimelineItem v-for="entry in detailRequest.activity" :key="entry.id" size="x-small" dot-color="primary" :icon="ACTIVITY_ICON[entry.kind]">
              <p class="text-body-2 mb-0">
                {{ entry.detail }}
              </p>
              <p class="text-caption text-medium-emphasis mb-0">
                {{ new Date(entry.created_at).toLocaleString() }}
              </p>
            </VTimelineItem>
          </VTimeline>
          <p v-if="!detailRequest.activity.length" class="text-caption text-medium-emphasis mb-0">
            No activity recorded yet.
          </p>
        </div>
      </VCardText>
      <VCardActions>
        <VBtn
          v-if="detailRequest.requested_by_user_id === authStore.profile?.id && detailRequest.status === 'pending'"
          variant="text" :loading="busy === detailRequest.id" @click="cancelRequest(detailRequest)"
        >
          Cancel request
        </VBtn>
        <VSpacer />
        <template v-if="iCanAct(detailRequest, authStore.profile?.id)">
          <VBtn variant="tonal" color="error" @click="openAction(detailRequest, 'reject')">
            Reject
          </VBtn>
          <VBtn variant="tonal" color="success" @click="openAction(detailRequest, 'approve')">
            Approve
          </VBtn>
        </template>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="previewDialog" max-width="800">
    <VCard :title="previewFilename">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="previewDialog = false" />
      </template>
      <VCardText>
        <img v-if="previewType === 'image'" :src="previewUrl" style="max-width: 100%; max-height: 70vh; display: block; margin: 0 auto;">
        <iframe v-else :src="previewUrl" style="width: 100%; height: 70vh; border: none;" />
      </VCardText>
    </VCard>
  </VDialog>
</template>
