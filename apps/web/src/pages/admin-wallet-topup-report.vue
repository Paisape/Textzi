<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useStepUpAuth } from '@/composables/useStepUpAuth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'finance',
  },
})

const authStore = useAuthStore()
const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'finance') : null)
const stepUp = useStepUpAuth()

type ReportRow = {
  order_id: string
  user_name: string | null
  user_email: string | null
  created_at: string
  ip_address: string | null
  rate_card_name: string | null
  amount: number
  gst_amount: number
  total_received: number
  credits_applied: number | null
  expected_credits: number | null
  mismatch: boolean
}

const rows = ref<ReportRow[]>([])
const loadError = ref('')
const loading = ref(false)
const mismatchesOnly = ref(false)

async function load() {
  loadError.value = ''
  loading.value = true
  try {
    await authStore.load()
    if (!(authStore.isAdmin || authStore.staffArea === 'finance'))
      return
    rows.value = await stepUp.withStepUp(() =>
      $api<ReportRow[]>('/v1/admin/wallet-topup-report', { query: { mismatches_only: mismatchesOnly.value } }),
    )
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the wallet top-up report.')
  }
  finally {
    loading.value = false
  }
}

const mismatchCount = computed(() => rows.value.filter(r => r.mismatch).length)

watch(mismatchesOnly, load)
onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Wallet Top-up Reconciliation
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every Razorpay wallet recharge, with the credits actually applied checked against what the
    order's own locked-in rate says they should be. A mismatch here suspends the account and
    deactivates its API keys automatically the moment it's detected — this report is for
    visibility across history, not the enforcement point itself.
  </p>

  <VAlert
    v-if="hasAccess === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin, Operator Admin, and Finance Team roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="hasAccess">
    <VAlert
      v-if="mismatchCount > 0"
      type="error"
      variant="tonal"
      class="mb-4"
    >
      {{ mismatchCount }} mismatched top-up{{ mismatchCount === 1 ? '' : 's' }} found — the affected
      account(s) should already be suspended with their API keys deactivated. Investigate before
      reinstating.
    </VAlert>

    <VSwitch
      v-model="mismatchesOnly"
      label="Show mismatches only"
      density="comfortable"
      class="mb-4"
    />

    <VCard>
      <VTable>
        <thead>
          <tr>
            <th>Date</th>
            <th>User</th>
            <th>IP Address</th>
            <th>Plan</th>
            <th>Top-up Amount</th>
            <th>Amount Received (incl. GST)</th>
            <th>Credits Applied</th>
            <th>Expected Credits</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.order_id"
            :class="{ 'bg-error/10': row.mismatch }"
          >
            <td class="text-no-wrap">
              {{ new Date(row.created_at).toLocaleString('en-IN') }}
            </td>
            <td>
              <div>{{ row.user_name ?? '—' }}</div>
              <div class="text-caption text-medium-emphasis">
                {{ row.user_email ?? '—' }}
              </div>
            </td>
            <td>{{ row.ip_address ?? '—' }}</td>
            <td>{{ row.rate_card_name ?? '—' }}</td>
            <td>₹{{ row.amount.toLocaleString('en-IN') }}</td>
            <td>₹{{ row.total_received.toLocaleString('en-IN') }}</td>
            <td>{{ row.credits_applied?.toFixed(2) ?? '—' }}</td>
            <td>{{ row.expected_credits?.toFixed(2) ?? '—' }}</td>
            <td>
              <VChip
                size="small"
                :color="row.mismatch ? 'error' : 'success'"
              >
                {{ row.mismatch ? 'Mismatch' : 'Match' }}
              </VChip>
            </td>
          </tr>
          <tr v-if="!loading && !rows.length">
            <td
              colspan="9"
              class="text-center text-medium-emphasis"
            >
              No wallet top-ups recorded yet.
            </td>
          </tr>
        </tbody>
      </VTable>
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
