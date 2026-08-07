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

type ZohoSettings = {
  client_id: string | null
  accounts_domain: string | null
  api_domain: string | null
  organization_id: string | null
  gst_tax_id_intrastate: string | null
  gst_tax_id_interstate: string | null
  gst_tax_id_zero_rated: string | null
  payment_deposit_account_id: string | null
  item_code_sms_service: string | null
  item_code_platform_fee_dlt: string | null
  item_code_platform_fee_whatsapp: string | null
  configured: boolean
  connected: boolean
}

type ZohoAccount = { account_id: string, account_name: string, account_type: string }
type ZohoTaxRate = { tax_id: string, tax_name: string, tax_percentage: number | null }

const clientId = ref('')
const clientSecret = ref('')
const accountsDomain = ref('accounts.zoho.in')
const organizationId = ref('')
const gstTaxIdIntrastate = ref('')
const gstTaxIdInterstate = ref('')
const gstTaxIdZeroRated = ref('')
const paymentDepositAccountId = ref('')
const accounts = ref<ZohoAccount[]>([])
const accountsError = ref('')
const accountsLoading = ref(false)
const accountOptions = computed(() => accounts.value.map(a => ({ title: `${a.account_name} (${a.account_type || 'other'})`, value: a.account_id })))
const taxRates = ref<ZohoTaxRate[]>([])
const taxRatesError = ref('')
const taxRatesLoading = ref(false)
const taxRateOptions = computed(() => taxRates.value.map(t => ({ title: t.tax_percentage != null ? `${t.tax_name} (${t.tax_percentage}%)` : t.tax_name, value: t.tax_id })))
const itemCodeSmsService = ref('')
const itemCodePlatformFeeDlt = ref('')
const itemCodePlatformFeeWhatsapp = ref('')
const configured = ref(false)
const connected = ref(false)
const apiDomain = ref('')

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

const grantCode = ref('')
const connectError = ref('')
const connectSuccess = ref('')
const connecting = ref(false)

function applySettings(result: ZohoSettings) {
  clientId.value = result.client_id ?? ''
  accountsDomain.value = result.accounts_domain ?? 'accounts.zoho.in'
  organizationId.value = result.organization_id ?? ''
  apiDomain.value = result.api_domain ?? ''
  gstTaxIdIntrastate.value = result.gst_tax_id_intrastate ?? ''
  gstTaxIdInterstate.value = result.gst_tax_id_interstate ?? ''
  gstTaxIdZeroRated.value = result.gst_tax_id_zero_rated ?? ''
  paymentDepositAccountId.value = result.payment_deposit_account_id ?? ''
  itemCodeSmsService.value = result.item_code_sms_service ?? ''
  itemCodePlatformFeeDlt.value = result.item_code_platform_fee_dlt ?? ''
  itemCodePlatformFeeWhatsapp.value = result.item_code_platform_fee_whatsapp ?? ''
  configured.value = result.configured
  connected.value = result.connected
}

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<ZohoSettings>('/v1/admin/platform/zoho-settings')
    applySettings(result)
    if (connected.value)
      await Promise.all([loadAccounts(), loadTaxRates()])
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Zoho Books settings.')
  }
}

async function loadAccounts() {
  accountsError.value = ''
  accountsLoading.value = true
  try {
    accounts.value = await $api<ZohoAccount[]>('/v1/admin/platform/zoho-accounts')
  }
  catch (error: any) {
    accountsError.value = extractErrorMessage(error, 'Could not fetch the account list from Zoho Books.')
  }
  finally {
    accountsLoading.value = false
  }
}

async function loadTaxRates() {
  taxRatesError.value = ''
  taxRatesLoading.value = true
  try {
    taxRates.value = await $api<ZohoTaxRate[]>('/v1/admin/platform/zoho-tax-rates')
  }
  catch (error: any) {
    taxRatesError.value = extractErrorMessage(error, 'Could not fetch tax rates from Zoho Books.')
  }
  finally {
    taxRatesLoading.value = false
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<ZohoSettings>('/v1/admin/platform/zoho-settings', {
      method: 'PUT',
      body: {
        client_id: clientId.value || null,
        client_secret: clientSecret.value || null,
        accounts_domain: accountsDomain.value || null,
        organization_id: organizationId.value || null,
        gst_tax_id_intrastate: gstTaxIdIntrastate.value || null,
        gst_tax_id_interstate: gstTaxIdInterstate.value || null,
        gst_tax_id_zero_rated: gstTaxIdZeroRated.value || null,
        payment_deposit_account_id: paymentDepositAccountId.value || null,
        item_code_sms_service: itemCodeSmsService.value || null,
        item_code_platform_fee_dlt: itemCodePlatformFeeDlt.value || null,
        item_code_platform_fee_whatsapp: itemCodePlatformFeeWhatsapp.value || null,
      },
    })
    applySettings(result)
    clientSecret.value = ''
    saveSuccess.value = 'Saved.'
    if (connected.value)
      await Promise.all([loadAccounts(), loadTaxRates()])
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Zoho Books settings.')
  }
  finally {
    saving.value = false
  }
}

async function onConnect() {
  connectError.value = ''
  connectSuccess.value = ''
  if (!grantCode.value.trim()) {
    connectError.value = 'Paste the grant code generated from api-console.zoho.com.'
    return
  }
  connecting.value = true
  try {
    const result = await $api<ZohoSettings>('/v1/admin/platform/zoho-connect', {
      method: 'POST',
      body: { grant_code: grantCode.value.trim() },
    })
    applySettings(result)
    grantCode.value = ''
    connectSuccess.value = 'Connected.'
    if (connected.value)
      await Promise.all([loadAccounts(), loadTaxRates()])
  }
  catch (error: any) {
    connectError.value = extractErrorMessage(error, 'Could not connect to Zoho Books.')
  }
  finally {
    connecting.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Zoho Books Integration
  </h1>
  <p class="text-medium-emphasis mb-6">
    Zoho Books is the source of truth for the invoice document itself, but only for organizations
    an admin has manually linked from their customer detail page — nothing syncs automatically.
    Once linked, every issued invoice for that organization creates the Invoice in Zoho, resolves
    the correct GST (interstate IGST vs. intrastate CGST+SGST), and fetches the rendered PDF back.
    If any step fails, Textzi's own PDF is used as a fallback so the customer is never left without
    an invoice — check <RouterLink to="/zoho-sync-log">Zoho Sync Log</RouterLink> to see exactly
    what failed and retry it.
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
    <VCard max-width="760" class="mb-6">
      <VCardText>
        <VChip
          :color="connected ? 'success' : 'warning'"
          size="small"
          class="mb-4"
        >
          {{ connected ? `Connected${apiDomain ? ` (${apiDomain})` : ''}` : 'Not connected (Textzi\'s own PDF is used for every invoice)' }}
        </VChip>

        <VAlert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ saveError }}
        </VAlert>
        <VAlert v-if="saveSuccess" type="success" variant="tonal" density="compact" class="mb-4">
          {{ saveSuccess }}
        </VAlert>

        <VForm @submit.prevent="onSave">
          <h6 class="text-h6 mb-4">
            Self-client credentials
          </h6>
          <VRow>
            <VCol cols="12" sm="6">
              <AppTextField
                v-model="clientId"
                label="Client ID"
                placeholder="from api-console.zoho.com"
              />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField
                v-model="clientSecret"
                type="password"
                label="Client secret"
                placeholder="Leave blank to keep the current secret"
              />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField
                v-model="accountsDomain"
                label="Accounts domain"
                placeholder="accounts.zoho.in"
                hint="The India data center domain for an Indian GST-registered org — do not change unless your Zoho org is on a different data center."
                persistent-hint
              />
            </VCol>
            <VCol cols="12" sm="6">
              <AppTextField
                v-model="organizationId"
                label="Zoho Organization ID"
                placeholder="from Zoho Books: Settings > Organizations"
              />
            </VCol>
            <VCol cols="12">
              <VBtn type="submit" :loading="saving" variant="tonal">
                Save credentials
              </VBtn>
            </VCol>
          </VRow>
        </VForm>

        <VDivider class="my-6" />

        <h6 class="text-h6 mb-2">
          Connect
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          A one-time step: generate a self-client grant/authorization code from
          api-console.zoho.com (scoped to ZohoBooks.contacts.ALL, .items.ALL, .invoices.ALL,
          .customerpayments.ALL, .settings.READ) and paste it below. Save the credentials above
          first — this exchanges the code for a permanent refresh token, which is then kept fresh
          automatically; you should not need to do this again unless the connection is revoked.
        </p>
        <VAlert v-if="connectError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ connectError }}
        </VAlert>
        <VAlert v-if="connectSuccess" type="success" variant="tonal" density="compact" class="mb-4">
          {{ connectSuccess }}
        </VAlert>
        <VForm @submit.prevent="onConnect">
          <VRow>
            <VCol cols="12" sm="8">
              <AppTextField
                v-model="grantCode"
                label="Grant code"
                placeholder="1000.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
              />
            </VCol>
            <VCol cols="12" sm="4" class="d-flex align-center">
              <VBtn type="submit" :loading="connecting">
                Connect
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>

    <VCard max-width="760">
      <VCardText>
        <VForm @submit.prevent="onSave">
          <h6 class="text-h6 mb-4">
            GST &amp; payment
          </h6>
          <VRow>
            <VCol cols="12" sm="6">
              <VAutocomplete
                v-model="gstTaxIdIntrastate"
                :items="taxRateOptions"
                :loading="taxRatesLoading"
                label="Intrastate GST rate (CGST + SGST)"
                hint="Used when the customer's state matches Textzi's own registered state."
                persistent-hint
                clearable
              />
            </VCol>
            <VCol cols="12" sm="6">
              <VAutocomplete
                v-model="gstTaxIdInterstate"
                :items="taxRateOptions"
                :loading="taxRatesLoading"
                label="Interstate GST rate (IGST)"
                hint="Used when the customer's state differs from Textzi's own registered state."
                persistent-hint
                clearable
              />
            </VCol>
            <VCol cols="12" sm="6">
              <VAutocomplete
                v-model="gstTaxIdZeroRated"
                :items="taxRateOptions"
                :loading="taxRatesLoading"
                label="Zero-rate GST (0%)"
                hint="Zoho requires a tax on every line item once GST is enabled, even at 0% -- used for invoices with no GST at all (e.g. a free/promotional admin credit)."
                persistent-hint
                clearable
              />
            </VCol>
            <VCol cols="12" sm="6">
              <VAutocomplete
                v-model="paymentDepositAccountId"
                :items="accountOptions"
                :loading="accountsLoading"
                label="Payment deposit account (Bank / Cash)"
                hint="Where a reconciling Customer Payment deposits to, for any invoice marked paid. Required before any 'paid' invoice can sync."
                persistent-hint
                clearable
              />
            </VCol>
            <VCol
              v-if="accountsError"
              cols="12"
            >
              <VAlert type="warning" variant="tonal" density="compact">
                {{ accountsError }}
              </VAlert>
            </VCol>
            <VCol
              v-if="taxRatesError"
              cols="12"
            >
              <VAlert type="warning" variant="tonal" density="compact">
                {{ taxRatesError }}
              </VAlert>
            </VCol>
          </VRow>

          <VDivider class="my-6" />

          <h6 class="text-h6 mb-2">
            Items
          </h6>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Three Zoho Items, each matched to a real GST SAC code: "SMS Service" (wallet recharges
            and admin manual credits, SAC 998413), "Platform fee (DLT Registration Service)" (SAC
            998314), and "Platform fee (WhatsApp Business Platform Fee)" (SAC 998314). Leave blank
            to have Textzi find an existing item with that exact name in Zoho on first use, or
            create one if none exists — paste a Zoho item id here directly only if you want to
            pin a specific one.
          </p>
          <VRow>
            <VCol cols="12" sm="4">
              <AppTextField
                v-model="itemCodeSmsService"
                label="SMS Service (Zoho item id)"
                hint="Wallet recharges + admin manual credits. Blank = auto-detect by name."
                persistent-hint
              />
            </VCol>
            <VCol cols="12" sm="4">
              <AppTextField
                v-model="itemCodePlatformFeeDlt"
                label="Platform fee — DLT Registration (Zoho item id)"
                hint="DLT registration fee invoices. Blank = auto-detect by name."
                persistent-hint
              />
            </VCol>
            <VCol cols="12" sm="4">
              <AppTextField
                v-model="itemCodePlatformFeeWhatsapp"
                label="Platform fee — WhatsApp (Zoho item id)"
                hint="Channel subscription invoices. Blank = auto-detect by name."
                persistent-hint
              />
            </VCol>
            <VCol cols="12">
              <VBtn type="submit" :loading="saving">
                Save
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>
  </template>
</template>
