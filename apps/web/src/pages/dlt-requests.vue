<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)
const stepUp = useStepUpAuth()

type DltDocument = { id: string, filename: string }
type DltRequest = {
  id: string
  status: string
  notes: string | null
  total_amount: number
  created_at: string
  documents: DltDocument[]
  entity_id: string
  entity_name: string
  organization_name: string
}

const loadError = ref('')
const requests = ref<DltRequest[]>([])
const updatingId = ref<string | null>(null)
const updateError = ref('')
const statusFilter = ref('')

const STATUS_FILTERS = [
  { value: '', title: 'All statuses' },
  { value: 'pending_payment', title: 'Pending payment' },
  { value: 'paid', title: 'Paid' },
  { value: 'in_progress', title: 'In progress' },
  { value: 'completed', title: 'Completed' },
  { value: 'rejected', title: 'Rejected' },
]

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    requests.value = await stepUp.withStepUp(() => $api<DltRequest[]>('/v1/admin/dlt-requests', { query: statusFilter.value ? { request_status: statusFilter.value } : {} }))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load DLT registration requests.')
  }
}

watch(statusFilter, load)

async function onUpdateStatus(request: DltRequest, status: string) {
  updateError.value = ''
  updatingId.value = request.id
  try {
    const updated = await stepUp.withStepUp(() => $api<DltRequest>(`/v1/admin/dlt-requests/${request.id}`, { method: 'PATCH', body: { status } }))
    request.status = updated.status
  }
  catch (error: any) {
    updateError.value = extractErrorMessage(error, 'Could not update this request.')
  }
  finally {
    updatingId.value = null
  }
}

const downloadingDocId = ref<string | null>(null)
async function onDownloadDocument(requestId: string, doc: DltDocument) {
  downloadingDocId.value = doc.id
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/admin/dlt-requests/${requestId}/documents/${doc.id}`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = doc.filename
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    updateError.value = extractErrorMessage(error, 'Could not download this document.')
  }
  finally {
    downloadingDocId.value = null
  }
}

function statusColor(status: string): string {
  if (status === 'completed')
    return 'success'
  if (status === 'rejected')
    return 'error'
  if (status === 'pending_payment')
    return 'warning'
  return 'info'
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    DLT Registration Requests
  </h1>
  <p class="text-medium-emphasis mb-6">
    Customers who don't have their own DLT registration and asked Textzi to handle it. Complete the real-world registration out-of-band, then create the PE ID/header via DLT Hierarchy and mark the request completed here.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="isAdmin">
    <VSelect
      v-model="statusFilter"
      :items="STATUS_FILTERS"
      item-title="title"
      item-value="value"
      label="Filter by status"
      density="compact"
      class="mb-4"
      style="max-inline-size: 260px;"
    />

    <VCard>
    <VCardText>
      <VAlert
        v-if="updateError"
        type="error"
        variant="tonal"
        density="compact"
        class="mb-4"
      >
        {{ updateError }}
      </VAlert>
      <VTable>
        <thead>
          <tr>
            <th>Organisation</th>
            <th>Notes</th>
            <th>Documents</th>
            <th>Fee charged</th>
            <th>Submitted</th>
            <th>Status</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="request in requests"
            :key="request.id"
          >
            <td>
              <div class="font-weight-medium">
                {{ request.organization_name }}
              </div>
              <div class="text-body-2 text-medium-emphasis">
                {{ request.entity_name }}
              </div>
            </td>
            <td style="max-inline-size: 240px;">
              {{ request.notes || '—' }}
            </td>
            <td>
              <div
                v-for="doc in request.documents"
                :key="doc.id"
              >
                <VBtn
                  variant="text"
                  size="small"
                  :loading="downloadingDocId === doc.id"
                  @click="onDownloadDocument(request.id, doc)"
                >
                  {{ doc.filename }}
                </VBtn>
              </div>
            </td>
            <td>₹{{ request.total_amount.toLocaleString('en-IN') }}</td>
            <td>{{ new Date(request.created_at).toLocaleString('en-IN') }}</td>
            <td>
              <VChip
                :color="statusColor(request.status)"
                size="small"
                class="text-capitalize"
              >
                {{ request.status.replaceAll('_', ' ') }}
              </VChip>
            </td>
            <td>
              <VSelect
                :model-value="request.status"
                :items="[
                  { value: 'paid', title: 'Paid' },
                  { value: 'in_progress', title: 'In progress' },
                  { value: 'completed', title: 'Completed' },
                  { value: 'rejected', title: 'Rejected' },
                ]"
                density="compact"
                variant="outlined"
                hide-details
                style="min-inline-size: 160px;"
                :loading="updatingId === request.id"
                :disabled="updatingId === request.id || request.status === 'pending_payment'"
                @update:model-value="(value: string) => onUpdateStatus(request, value)"
              />
            </td>
          </tr>
          <tr v-if="!requests.length">
            <td
              colspan="7"
              class="text-center text-medium-emphasis"
            >
              No DLT registration requests yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCardText>
    </VCard>
  </template>

  <StepUpDialog
    v-model="stepUp.dialogOpen.value"
    :code="stepUp.code.value"
    :error="stepUp.error.value"
    :submitting="stepUp.submitting.value"
    @update:code="v => stepUp.code.value = v"
    @submit="stepUp.submit"
    @cancel="stepUp.cancel"
  />
</template>
