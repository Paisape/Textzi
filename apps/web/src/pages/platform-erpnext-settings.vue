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

type ErpNextSettings = {
  base_url: string | null
  api_key: string | null
  company: string | null
  gst_tax_template: string | null
  payment_account: string | null
  print_format: string | null
  customer_group: string | null
  sales_invoice_naming_series: string | null
  item_code_wallet_recharge: string | null
  item_code_dlt_fee: string | null
  item_code_channel_subscription: string | null
  item_code_admin_credit: string | null
  configured: boolean
}

type ErpNextAccount = { name: string, account_name: string, account_type: string }
type ErpNextTaxTemplate = { name: string, is_default: boolean }

const baseUrl = ref('')
const apiKey = ref('')
const apiSecret = ref('')
const company = ref('')
const gstTaxTemplate = ref('')
const paymentAccount = ref('')
const printFormat = ref('')
const accounts = ref<ErpNextAccount[]>([])
const accountsError = ref('')
const accountsLoading = ref(false)
const accountOptions = computed(() => accounts.value.map(a => ({ title: `${a.account_name} (${a.account_type || 'other'})`, value: a.name })))
const taxTemplates = ref<ErpNextTaxTemplate[]>([])
const taxTemplatesError = ref('')
const taxTemplatesLoading = ref(false)
const taxTemplateOptions = computed(() => taxTemplates.value.map(t => ({ title: t.is_default ? `${t.name} (default)` : t.name, value: t.name })))
const customerGroup = ref('')
const salesInvoiceNamingSeries = ref('')
const itemCodeWalletRecharge = ref('')
const itemCodeDltFee = ref('')
const itemCodeChannelSubscription = ref('')
const itemCodeAdminCredit = ref('')
const configured = ref(false)

const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)

async function loadSettings() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    const result = await $api<ErpNextSettings>('/v1/admin/platform/erpnext-settings')
    baseUrl.value = result.base_url ?? ''
    apiKey.value = result.api_key ?? ''
    company.value = result.company ?? ''
    gstTaxTemplate.value = result.gst_tax_template ?? ''
    paymentAccount.value = result.payment_account ?? ''
    printFormat.value = result.print_format ?? ''
    customerGroup.value = result.customer_group ?? ''
    salesInvoiceNamingSeries.value = result.sales_invoice_naming_series ?? ''
    itemCodeWalletRecharge.value = result.item_code_wallet_recharge ?? ''
    itemCodeDltFee.value = result.item_code_dlt_fee ?? ''
    itemCodeChannelSubscription.value = result.item_code_channel_subscription ?? ''
    itemCodeAdminCredit.value = result.item_code_admin_credit ?? ''
    configured.value = result.configured
    if (configured.value) {
      await Promise.all([loadAccounts(), loadTaxTemplates()])
    }
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load ERPNext settings.')
  }
}

async function loadAccounts() {
  accountsError.value = ''
  accountsLoading.value = true
  try {
    accounts.value = await $api<ErpNextAccount[]>('/v1/admin/platform/erpnext-accounts')
  }
  catch (error: any) {
    accountsError.value = extractErrorMessage(error, 'Could not fetch the account list from ERPNext.')
  }
  finally {
    accountsLoading.value = false
  }
}

async function loadTaxTemplates() {
  taxTemplatesError.value = ''
  taxTemplatesLoading.value = true
  try {
    taxTemplates.value = await $api<ErpNextTaxTemplate[]>('/v1/admin/platform/erpnext-tax-templates')
  }
  catch (error: any) {
    taxTemplatesError.value = extractErrorMessage(error, 'Could not fetch tax templates from ERPNext.')
  }
  finally {
    taxTemplatesLoading.value = false
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    const result = await $api<ErpNextSettings>('/v1/admin/platform/erpnext-settings', {
      method: 'PUT',
      body: {
        base_url: baseUrl.value || null,
        api_key: apiKey.value || null,
        api_secret: apiSecret.value || null,
        company: company.value || null,
        gst_tax_template: gstTaxTemplate.value || null,
        payment_account: paymentAccount.value || null,
        print_format: printFormat.value || null,
        customer_group: customerGroup.value || null,
        sales_invoice_naming_series: salesInvoiceNamingSeries.value || null,
        item_code_wallet_recharge: itemCodeWalletRecharge.value || null,
        item_code_dlt_fee: itemCodeDltFee.value || null,
        item_code_channel_subscription: itemCodeChannelSubscription.value || null,
        item_code_admin_credit: itemCodeAdminCredit.value || null,
      },
    })
    configured.value = result.configured
    apiSecret.value = ''
    saveSuccess.value = 'Saved.'
    if (configured.value)
      await Promise.all([loadAccounts(), loadTaxTemplates()])
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save ERPNext settings.')
  }
  finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <h1 class="text-h4 mb-1">
    ERPNext Integration
  </h1>
  <p class="text-medium-emphasis mb-6">
    ERPNext is the source of truth for the invoice document itself — every issued invoice
    creates (or reuses) a Customer, auto-creates the mapped Item if it doesn't exist yet, creates
    a Sales Invoice, and fetches the rendered PDF back. If any step fails, Textzi's own PDF is
    used as a fallback so the customer is never left without an invoice — check
    <RouterLink to="/erpnext-sync-log">ERPNext Sync Log</RouterLink> to see exactly what failed
    and retry it.
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

  <VCard
    v-else-if="isAdmin"
    max-width="760"
  >
    <VCardText>
      <VChip
        :color="configured ? 'success' : 'warning'"
        size="small"
        class="mb-4"
      >
        {{ configured ? 'Configured' : 'Not configured (Textzi\'s own PDF is used for every invoice)' }}
      </VChip>

      <VAlert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ saveError }}
      </VAlert>
      <VAlert v-if="saveSuccess" type="success" variant="tonal" density="compact" class="mb-4">
        {{ saveSuccess }}
      </VAlert>

      <VForm @submit.prevent="onSave">
        <h6 class="text-h6 mb-4">
          Connection
        </h6>
        <VRow>
          <VCol cols="12" sm="8">
            <AppTextField
              v-model="baseUrl"
              label="ERPNext base URL"
              placeholder="https://erp.paisape.org"
            />
          </VCol>
          <VCol cols="12" sm="4">
            <AppTextField
              v-model="company"
              label="Company (as in ERPNext)"
              placeholder="Paisape Techfin Private Limited"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="apiKey"
              label="API key"
              placeholder="from ERPNext: My Settings > API Access"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="apiSecret"
              type="password"
              label="API secret"
              placeholder="Leave blank to keep the current secret"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="customerGroup"
              label="Customer group (optional)"
              placeholder="Commercial"
              hint="Purely for your own reporting inside ERPNext — not required. Leave blank to have ERPNext leave every Customer Textzi creates with no group set."
              persistent-hint
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="salesInvoiceNamingSeries"
              label="Sales Invoice naming series (optional)"
              placeholder="SI-.####."
              hint="Leave blank to use ERPNext's own default series. Only needs setting if that default produces an invoice number over 16 characters — GST (india_compliance) rejects creation outright above that length."
              persistent-hint
            />
          </VCol>
          <VCol cols="12" sm="6">
            <VAutocomplete
              v-model="gstTaxTemplate"
              :items="taxTemplateOptions"
              :loading="taxTemplatesLoading"
              label="GST tax template"
              placeholder="Output GST In-state - COMPANY"
              hint="A Sales Taxes and Charges Template already configured in ERPNext — referencing it by name is all that's needed for ERPNext to compute and post the correct CGST/SGST lines itself. Required before any invoice with GST can sync."
              persistent-hint
              clearable
            />
          </VCol>
          <VCol cols="12" sm="6">
            <VAutocomplete
              v-model="paymentAccount"
              :items="accountOptions"
              :loading="accountsLoading"
              label="Payment account (Bank / Cash)"
              placeholder="Cash - COMPANY"
              hint="Where a reconciling Payment Entry deposits to, for any invoice marked paid (wallet recharge, DLT fee, channel subscription always are; an admin manual credit is the admin's own choice). Required before any 'paid' invoice can sync."
              persistent-hint
              clearable
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="printFormat"
              label="Print format (optional)"
              placeholder="leave blank for ERPNext's default"
              hint="If your default Sales Invoice print format fails to render (e.g. a broken image reference), name a working one here."
              persistent-hint
            />
          </VCol>
          <VCol
            v-if="accountsError"
            cols="12"
          >
            <VAlert type="warning" variant="tonal" density="compact">
              {{ accountsError }} — the payment account field above will show as plain text until this is fixed; type the exact ERPNext account name manually in the meantime.
            </VAlert>
          </VCol>
          <VCol
            v-if="taxTemplatesError"
            cols="12"
          >
            <VAlert type="warning" variant="tonal" density="compact">
              {{ taxTemplatesError }} — the GST tax template field above will show as plain text until this is fixed; type the exact ERPNext template name manually in the meantime.
            </VAlert>
          </VCol>
        </VRow>

        <VDivider class="my-6" />

        <h6 class="text-h6 mb-2">
          Item codes
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Auto-created in ERPNext the first time each is referenced — you only need to choose a
          code here, not create it yourself first.
        </p>
        <VRow>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="itemCodeWalletRecharge"
              label="Wallet recharge"
              placeholder="SMS-CREDITS"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="itemCodeDltFee"
              label="DLT fee"
              placeholder="DLT-FEE"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="itemCodeChannelSubscription"
              label="Channel subscription"
              placeholder="CHANNEL-SUB"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="itemCodeAdminCredit"
              label="Admin manual credit"
              placeholder="ADMIN-CREDIT"
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
