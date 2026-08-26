<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'finance',
  },
})

const authStore = useAuthStore()
const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'finance') : null)

type BankTransferRequest = {
  id: string
  entity_id: string
  organization_name: string | null
  transfer_date: string
  mode: string
  amount: number
  utr_number: string
  notes: string | null
  status: string
  credited_amount: number | null
  admin_note: string | null
  reviewed_at: string | null
  created_at: string
}

const requests = ref<BankTransferRequest[]>([])
const loading = ref(false)
const loadError = ref('')
const statusFilter = ref<string | null>('pending')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    requests.value = await $api<BankTransferRequest[]>('/v1/admin/textzi-wallet/requests', { params: statusFilter.value ? { request_status: statusFilter.value } : {} })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load bank transfer requests.')
  }
  finally {
    loading.value = false
  }
}

const statusColor: Record<string, string> = { pending: 'warning', approved: 'success', rejected: 'error' }

const reviewDialog = ref(false)
const reviewingRequest = ref<BankTransferRequest | null>(null)
const reviewCreditedAmount = ref<number | null>(null)
const reviewNote = ref('')
const reviewSubmitting = ref(false)
const reviewError = ref('')

function openApprove(request: BankTransferRequest) {
  reviewingRequest.value = request
  reviewCreditedAmount.value = request.amount
  reviewNote.value = ''
  reviewError.value = ''
  reviewDialog.value = true
}

async function confirmApprove() {
  if (!reviewingRequest.value || !reviewCreditedAmount.value)
    return
  reviewSubmitting.value = true
  reviewError.value = ''
  try {
    const updated = await $api<BankTransferRequest>(`/v1/admin/textzi-wallet/requests/${reviewingRequest.value.id}`, {
      method: 'PATCH',
      body: { status: 'approved', credited_amount: reviewCreditedAmount.value, admin_note: reviewNote.value || null },
    })
    const index = requests.value.findIndex(r => r.id === updated.id)
    if (index !== -1) {
      if (statusFilter.value)
        requests.value.splice(index, 1)
      else
        requests.value[index] = updated
    }
    reviewDialog.value = false
  }
  catch (error: any) {
    reviewError.value = extractErrorMessage(error, 'Could not approve this request.')
  }
  finally {
    reviewSubmitting.value = false
  }
}

async function reject(request: BankTransferRequest) {
  const note = window.prompt('Reason for rejecting this request (optional):') || undefined
  try {
    const updated = await $api<BankTransferRequest>(`/v1/admin/textzi-wallet/requests/${request.id}`, {
      method: 'PATCH',
      body: { status: 'rejected', admin_note: note || null },
    })
    const index = requests.value.findIndex(r => r.id === updated.id)
    if (index !== -1) {
      if (statusFilter.value)
        requests.value.splice(index, 1)
      else
        requests.value[index] = updated
    }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reject this request.')
  }
}

async function downloadReceipt(request: BankTransferRequest) {
  try {
    const blob = await $api<Blob, 'blob'>(`/v1/admin/textzi-wallet/requests/${request.id}/receipt`, { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `receipt-${request.utr_number}`
    link.click()
    URL.revokeObjectURL(url)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not download this receipt.')
  }
}

watch(statusFilter, load)
onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Bank Transfer Requests
  </h1>
  <p class="text-medium-emphasis mb-6">
    Customer-submitted "I sent a bank transfer" claims — verify the UTR/amount against the real
    bank statement before approving. Approving credits the customer's Textzi Wallet with whatever
    amount you enter here, not necessarily what they claimed.
  </p>

  <VAlert v-if="hasAccess === false" type="warning" variant="tonal">
    This page is restricted to Super Admin, Operator Admin, and Finance Team roles.
  </VAlert>

  <template v-else-if="hasAccess">
    <div class="d-flex align-center justify-space-between mb-4 flex-wrap ga-3">
      <VSelect
        v-model="statusFilter"
        :items="[{ title: 'Pending', value: 'pending' }, { title: 'Approved', value: 'approved' }, { title: 'Rejected', value: 'rejected' }, { title: 'All', value: null }]"
        density="compact"
        variant="outlined"
        style="max-width: 200px;"
      />
    </div>

    <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
      {{ loadError }}
    </VAlert>

    <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-4" />

    <VCard v-if="requests.length">
      <VTable>
        <thead>
          <tr>
            <th>Customer</th>
            <th>Date</th>
            <th>Mode</th>
            <th>Claimed</th>
            <th>UTR</th>
            <th>Receipt</th>
            <th>Status</th>
            <th>Credited</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="req in requests" :key="req.id">
            <td>{{ req.organization_name || '—' }}</td>
            <td>{{ req.transfer_date }}</td>
            <td class="text-uppercase">
              {{ req.mode }}
            </td>
            <td>₹{{ req.amount.toLocaleString('en-IN') }}</td>
            <td>{{ req.utr_number }}</td>
            <td>
              <VBtn size="small" variant="text" @click="downloadReceipt(req)">
                View
              </VBtn>
            </td>
            <td>
              <VChip :color="statusColor[req.status]" size="small">
                {{ req.status }}
              </VChip>
            </td>
            <td>{{ req.credited_amount != null ? `₹${req.credited_amount.toLocaleString('en-IN')}` : '—' }}</td>
            <td>
              <div v-if="req.status === 'pending'" class="d-flex ga-2">
                <VBtn size="small" color="success" variant="tonal" @click="openApprove(req)">
                  Approve
                </VBtn>
                <VBtn size="small" color="error" variant="tonal" @click="reject(req)">
                  Reject
                </VBtn>
              </div>
              <span v-else-if="req.admin_note" class="text-caption text-medium-emphasis">{{ req.admin_note }}</span>
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
    <p v-else-if="!loading" class="text-medium-emphasis text-center pa-8">
      No requests.
    </p>
  </template>

  <VDialog v-model="reviewDialog" max-width="440">
    <VCard v-if="reviewingRequest">
      <VCardTitle>Approve bank transfer request</VCardTitle>
      <VCardText>
        <VAlert v-if="reviewError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ reviewError }}
        </VAlert>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Customer claimed ₹{{ reviewingRequest.amount.toLocaleString('en-IN') }} via {{ reviewingRequest.mode.toUpperCase() }}
          (UTR {{ reviewingRequest.utr_number }}). Enter the amount actually verified against the bank statement.
        </p>
        <AppTextField
          v-model.number="reviewCreditedAmount"
          type="number"
          label="Amount to credit (₹)"
          class="mb-4"
        />
        <AppTextField
          v-model="reviewNote"
          label="Admin note (optional)"
        />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="reviewDialog = false">
          Cancel
        </VBtn>
        <VBtn color="success" :loading="reviewSubmitting" @click="confirmApprove">
          Approve &amp; credit wallet
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
