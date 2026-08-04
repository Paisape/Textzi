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

type SmsSettings = {
  pe_id: string | null
  pe_operator: string | null
  header_id: string | null
  sender_id: string | null
  dlt_template_id: string | null
  template_body: string | null
  route: string | null
}

type WalletTransaction = { id: string, type: string, amount: number, balance_after: number, reference: string | null, created_at: string }
type Wallet = { balance: number, transactions: WalletTransaction[] }

const form = ref<SmsSettings>({
  pe_id: '', pe_operator: '', header_id: '', sender_id: '', dlt_template_id: '', template_body: '', route: '',
})
const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

const wallet = ref<Wallet | null>(null)
const topupAmount = ref<number | null>(null)
const topupNotes = ref('')
const toppingUp = ref(false)
const topupError = ref('')

const testRecipient = ref('')
const testSending = ref(false)
const testError = ref('')
const testResult = ref<{ message_id: string, status: string, recipient: string } | null>(null)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<SmsSettings>('/v1/admin/platform/sms-settings')
    form.value = { ...result, pe_id: result.pe_id ?? '', pe_operator: result.pe_operator ?? '', header_id: result.header_id ?? '', sender_id: result.sender_id ?? '', dlt_template_id: result.dlt_template_id ?? '', template_body: result.template_body ?? '', route: result.route ?? '' }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load SMS settings.')
  }
}

async function loadWallet() {
  if (!authStore.isAdmin)
    return
  try {
    wallet.value = await $api<Wallet>('/v1/admin/platform/wallet')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load the platform wallet.')
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    await $api('/v1/admin/platform/sms-settings', {
      method: 'PUT',
      body: {
        pe_id: form.value.pe_id || null,
        pe_operator: form.value.pe_operator || null,
        header_id: form.value.header_id || null,
        sender_id: form.value.sender_id || null,
        dlt_template_id: form.value.dlt_template_id || null,
        template_body: form.value.template_body || null,
        route: form.value.route || null,
      },
    })
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save SMS settings.')
  }
  finally {
    saving.value = false
  }
}

async function onTopup() {
  topupError.value = ''
  if (!topupAmount.value) {
    topupError.value = 'Enter an amount.'
    return
  }
  toppingUp.value = true
  try {
    wallet.value = await $api<Wallet>('/v1/admin/platform/wallet/topup', { method: 'POST', body: { amount: topupAmount.value, notes: topupNotes.value || null } })
    topupAmount.value = null
    topupNotes.value = ''
  }
  catch (error: any) {
    topupError.value = extractErrorMessage(error, 'Could not top up the platform wallet.')
  }
  finally {
    toppingUp.value = false
  }
}

async function onTestSend() {
  testError.value = ''
  testResult.value = null
  if (!testRecipient.value) {
    testError.value = 'Enter a recipient number.'
    return
  }
  testSending.value = true
  try {
    testResult.value = await $api<{ message_id: string, status: string, recipient: string }>('/v1/admin/platform/test-sms', {
      method: 'POST',
      body: { recipient: testRecipient.value },
    })
    await loadWallet()
  }
  catch (error: any) {
    testError.value = extractErrorMessage(error, 'Could not send the test SMS.')
  }
  finally {
    testSending.value = false
  }
}

onMounted(async () => {
  await loadSettings()
  await loadWallet()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Platform SMS Setting
  </h1>
  <p class="text-medium-emphasis mb-6">
    Textzi's own sender identity, used only for its own operational SMS (currently: login OTPs).
    Entirely separate from any customer's DLT setup.
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
    class="mb-4"
  >
    {{ loadError }}
  </VAlert>

  <VRow v-else-if="isAdmin">
    <VCol cols="12" md="7">
      <VCard>
        <VCardText>
          <VAlert
            v-if="saveError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ saveError }}
          </VAlert>
          <VAlert
            v-if="saveSuccess"
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ saveSuccess }}
          </VAlert>
          <VForm @submit.prevent="onSave">
            <VRow>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.pe_id"
                  label="PE ID"
                  placeholder="1701234567890123456"
                />
              </VCol>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.pe_operator"
                  label="Operator"
                  placeholder="Jio / Airtel / Vi"
                />
              </VCol>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.header_id"
                  label="DLT header id"
                  placeholder="1701234567890123456"
                />
              </VCol>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.sender_id"
                  label="Sender id"
                  placeholder="TXTZPL"
                />
              </VCol>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.dlt_template_id"
                  label="DLT template id"
                  placeholder="1707123456789012345"
                />
              </VCol>
              <VCol cols="12" sm="6">
                <AppTextField
                  v-model="form.route"
                  label="Provider route (blank = simulated)"
                  placeholder="default-simulated-route"
                />
              </VCol>
              <VCol cols="12">
                <AppTextarea
                  v-model="form.template_body"
                  label="OTP message template"
                  placeholder="Your Textzi verification code is {{code}}. Do not share it with anyone."
                  hint="Must contain {{code}} -- the placeholder gets replaced with the actual OTP."
                  persistent-hint
                  rows="3"
                />
              </VCol>
              <VCol cols="12">
                <VBtn
                  type="submit"
                  :loading="saving"
                >
                  Save
                </VBtn>
              </VCol>
            </VRow>
          </VForm>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" md="5">
      <VCard>
        <VCardText>
          <h6 class="text-h6 mb-2">
            Platform Wallet
          </h6>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Internal use only -- funds the platform's own SMS sending. No rupee conversion, no
            GST, no invoicing.
          </p>
          <div class="text-h4 mb-4">
            {{ wallet?.balance ?? 0 }} credits
          </div>

          <VAlert
            v-if="topupError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ topupError }}
          </VAlert>
          <VForm @submit.prevent="onTopup">
            <AppTextField
              v-model.number="topupAmount"
              type="number"
              label="Credits to add"
              placeholder="100"
              class="mb-4"
            />
            <AppTextField
              v-model="topupNotes"
              label="Notes (optional)"
              placeholder="Reason for this top-up"
              class="mb-4"
            />
            <VBtn
              type="submit"
              :loading="toppingUp"
            >
              Top Up
            </VBtn>
          </VForm>

          <VDivider class="my-4" />

          <VTable density="compact">
            <thead>
              <tr>
                <th>Type</th>
                <th>Amount</th>
                <th>Balance</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="tx in wallet?.transactions ?? []"
                :key="tx.id"
              >
                <td class="text-capitalize">
                  {{ tx.type.replaceAll('_', ' ') }}
                </td>
                <td>{{ tx.amount > 0 ? '+' : '' }}{{ tx.amount }}</td>
                <td>{{ tx.balance_after }}</td>
              </tr>
              <tr v-if="!wallet?.transactions.length">
                <td colspan="3" class="text-center text-medium-emphasis">
                  No transactions yet.
                </td>
              </tr>
            </tbody>
          </VTable>
        </VCardText>
      </VCard>

      <VCard class="mt-6">
        <VCardText>
          <h6 class="text-h6 mb-2">
            Send Test SMS
          </h6>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Fires a real send through this exact configuration (PE ID, template, route) to any
            number, so a delivery issue can be reproduced without a full registration or login
            flow. Costs 1 platform wallet credit. Check
            <RouterLink to="/admin-messages">
              Platform Messages
            </RouterLink>
            afterward for the full request/response/DR telemetry.
          </p>

          <VAlert
            v-if="testError"
            type="error"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            {{ testError }}
          </VAlert>
          <VAlert
            v-if="testResult"
            type="success"
            variant="tonal"
            density="compact"
            class="mb-4"
          >
            Sent to {{ testResult.recipient }} — status: {{ testResult.status }}.
          </VAlert>

          <VForm @submit.prevent="onTestSend">
            <AppTextField
              v-model="testRecipient"
              label="Recipient mobile number"
              placeholder="9876543210"
              class="mb-4"
            />
            <VBtn
              type="submit"
              color="secondary"
              :loading="testSending"
            >
              Send Test SMS
            </VBtn>
          </VForm>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
