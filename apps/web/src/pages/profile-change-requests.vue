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

type ChangeRequest = {
  id: string
  status: string
  requested_full_name: string | null
  requested_email: string | null
  requested_mobile: string | null
  requested_company_name: string | null
  requested_gstin: string | null
  requested_pan: string | null
  requested_address: string | null
  requested_state_code: string | null
  customer_note: string | null
  admin_note: string | null
  created_at: string
  reviewed_at: string | null
  user_id: string
  user_email: string
  user_full_name: string
}

const loadError = ref('')
const requests = ref<ChangeRequest[]>([])
const updatingId = ref<string | null>(null)
const updateError = ref('')
const statusFilter = ref('pending')

const STATUS_FILTERS = [
  { value: '', title: 'All statuses' },
  { value: 'pending', title: 'Pending' },
  { value: 'approved', title: 'Approved' },
  { value: 'rejected', title: 'Rejected' },
]

const FIELD_LABELS: Record<string, string> = {
  requested_full_name: 'Full name',
  requested_email: 'Email',
  requested_mobile: 'Mobile',
  requested_company_name: 'Company name',
  requested_gstin: 'GSTIN',
  requested_pan: 'PAN',
  requested_address: 'Address',
  requested_state_code: 'State code',
}

function requestedFields(r: ChangeRequest) {
  return Object.entries(FIELD_LABELS)
    .map(([key, label]) => ({ label, value: (r as unknown as Record<string, string | null>)[key] }))
    .filter(f => f.value)
}

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    requests.value = await stepUp.withStepUp(() => $api<ChangeRequest[]>('/v1/admin/profile-change-requests', { query: statusFilter.value ? { request_status: statusFilter.value } : {} }))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load profile change requests.')
  }
}

watch(statusFilter, load)

async function onUpdateStatus(request: ChangeRequest, status: string) {
  updateError.value = ''
  updatingId.value = request.id
  try {
    const updated = await stepUp.withStepUp(() => $api<ChangeRequest>(`/v1/admin/profile-change-requests/${request.id}`, { method: 'PATCH', body: { status } }))
    request.status = updated.status
  }
  catch (error: any) {
    updateError.value = extractErrorMessage(error, 'Could not update this request.')
  }
  finally {
    updatingId.value = null
  }
}

function statusColor(status: string) {
  if (status === 'approved')
    return 'success'
  if (status === 'rejected')
    return 'error'
  return 'warning'
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Profile Change Requests
  </h1>
  <p class="text-medium-emphasis mb-6">
    Customers can't directly edit their name, email, mobile, or company/GST details — a change
    queues here for review. Approving applies it immediately; an approved email/mobile change
    resets that field's verified status, since it hasn't actually been re-proven.
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
              <th>Customer</th>
              <th>Requested changes</th>
              <th>Note</th>
              <th>Submitted</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="request in requests" :key="request.id">
              <td>
                <div class="font-weight-medium">
                  {{ request.user_full_name }}
                </div>
                <div class="text-body-2 text-medium-emphasis">
                  {{ request.user_email }}
                </div>
              </td>
              <td>
                <div v-for="f in requestedFields(request)" :key="f.label" class="text-body-2">
                  <strong>{{ f.label }}:</strong> {{ f.value }}
                </div>
              </td>
              <td style="max-inline-size: 220px;">
                {{ request.customer_note || '—' }}
              </td>
              <td>{{ new Date(request.created_at).toLocaleString('en-IN') }}</td>
              <td>
                <VChip :color="statusColor(request.status)" size="small" class="text-capitalize">
                  {{ request.status }}
                </VChip>
              </td>
              <td>
                <VSelect
                  v-if="request.status === 'pending'"
                  :model-value="request.status"
                  :items="[
                    { value: 'approved', title: 'Approve' },
                    { value: 'rejected', title: 'Reject' },
                  ]"
                  placeholder="Review"
                  density="compact"
                  variant="outlined"
                  hide-details
                  style="min-inline-size: 140px;"
                  :loading="updatingId === request.id"
                  :disabled="updatingId === request.id"
                  @update:model-value="(value: string) => onUpdateStatus(request, value)"
                />
              </td>
            </tr>
            <tr v-if="!requests.length">
              <td colspan="6" class="text-center text-medium-emphasis">
                No profile change requests.
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
