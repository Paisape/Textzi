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

type RuleRow = { code: number, label: string | null, refund: boolean }

const loadError = ref('')
const rules = ref<RuleRow[]>([])

async function loadRules() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    rules.value = await stepUp.withStepUp(() => $api<RuleRow[]>('/v1/admin/delivery-status-rules'))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load delivery status rules.')
  }
}

const newCode = ref<number | null>(null)
const newLabel = ref('')
const newRefund = ref(true)
const ruleSubmitting = ref(false)
const ruleError = ref('')

async function onSaveRule() {
  ruleError.value = ''
  if (newCode.value === null || newCode.value < 0) {
    ruleError.value = 'Enter the DeliveryStatusCode this rule applies to.'
    return
  }
  ruleSubmitting.value = true
  try {
    await stepUp.withStepUp(() => $api('/v1/admin/delivery-status-rules', {
      method: 'POST',
      body: { code: newCode.value, label: newLabel.value.trim() || null, refund: newRefund.value },
    }))
    newCode.value = null; newLabel.value = ''; newRefund.value = true
    await loadRules()
  }
  catch (error: any) {
    ruleError.value = extractErrorMessage(error, 'Could not save this rule.')
  }
  finally {
    ruleSubmitting.value = false
  }
}

const deletingCode = ref<number | null>(null)
async function onDeleteRule(code: number) {
  deletingCode.value = code
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/delivery-status-rules/${code}`, { method: 'DELETE' }))
    await loadRules()
  }
  catch (error: any) {
    ruleError.value = extractErrorMessage(error, 'Could not remove this rule.')
  }
  finally {
    deletingCode.value = null
  }
}

const REFERENCE_CODES = [
  { code: 2, meaning: 'DELIVERED' },
  { code: 3, meaning: 'EXPIRED' },
  { code: 5, meaning: 'UNDELIVERABLE' },
  { code: 8, meaning: 'REJECTED' },
  { code: 10, meaning: 'FAILED' },
  { code: 11, meaning: 'DELIVERY_FAILED' },
  { code: 79, meaning: 'Entity is blacklisted' },
  { code: 80, meaning: 'Entity is not active' },
  { code: 91, meaning: 'Invalid MSISDN number' },
  { code: 93, meaning: 'Invalid API Key' },
  { code: 100, meaning: 'HTTP Client errors (4xx)' },
  { code: 101, meaning: 'HTTP Server errors (5xx)' },
]

onMounted(loadRules)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Delivery Status Rules
  </h1>
  <p class="text-medium-emphasis mb-6">
    Every DeliveryStatusCode reported back by a delivery-report webhook counts as a
    <strong>billable success</strong> by default (the charge from send time stands) unless it's
    listed here. A code you add here is treated as a failed send; whether that also refunds the
    customer's wallet is your choice per code.
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
    <VCard class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-4">
          Configured rules
        </h6>
        <VAlert
          v-if="ruleError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ ruleError }}
        </VAlert>

        <VTable class="mb-6">
          <thead>
            <tr>
              <th>Code</th>
              <th>Label</th>
              <th>Outcome</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="rule in rules"
              :key="rule.code"
            >
              <td class="font-weight-medium">
                {{ rule.code }}
              </td>
              <td>{{ rule.label || '—' }}</td>
              <td>
                <VChip
                  size="small"
                  :color="rule.refund ? 'error' : 'warning'"
                >
                  {{ rule.refund ? 'Failed — refunded' : 'Failed — no refund' }}
                </VChip>
              </td>
              <td>
                <VBtn
                  size="small"
                  variant="text"
                  color="error"
                  :loading="deletingCode === rule.code"
                  @click="onDeleteRule(rule.code)"
                >
                  Remove
                </VBtn>
              </td>
            </tr>
            <tr v-if="!rules.length">
              <td
                colspan="4"
                class="text-center text-medium-emphasis"
              >
                No rules configured yet — every delivery status code counts as a billable success.
              </td>
            </tr>
          </tbody>
        </VTable>

        <h6 class="text-h6 mb-4">
          Add / update a rule
        </h6>
        <VForm @submit.prevent="onSaveRule">
          <VRow>
            <VCol
              cols="12"
              sm="2"
            >
              <AppTextField
                v-model.number="newCode"
                type="number"
                label="Code"
                placeholder="91"
              />
            </VCol>
            <VCol
              cols="12"
              sm="5"
            >
              <AppTextField
                v-model="newLabel"
                label="Label (optional)"
                placeholder="Invalid MSISDN number"
              />
            </VCol>
            <VCol
              cols="12"
              sm="3"
              class="d-flex align-center"
            >
              <VSwitch
                v-model="newRefund"
                :label="newRefund ? 'Refund the customer' : 'No refund'"
                color="error"
              />
            </VCol>
            <VCol
              cols="12"
              sm="2"
              class="d-flex align-end"
            >
              <VBtn
                type="submit"
                :loading="ruleSubmitting"
              >
                Save rule
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>

    <VCard>
      <VCardText>
        <h6 class="text-h6 mb-4">
          Reference — common TTBS codes
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Not exhaustive — see the TTBS integration docs for the full list (0–11 base statuses,
          74–101 and 600–705 scrubbing/DLT codes).
        </p>
        <VTable density="compact">
          <thead>
            <tr>
              <th>Code</th>
              <th>Meaning</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ref in REFERENCE_CODES"
              :key="ref.code"
            >
              <td>{{ ref.code }}</td>
              <td>{{ ref.meaning }}</td>
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
