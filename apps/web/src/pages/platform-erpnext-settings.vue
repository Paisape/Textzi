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
  cgst_account_head: string | null
  sgst_account_head: string | null
  print_format: string | null
  customer_group: string
  territory: string
  sales_invoice_naming_series: string | null
  item_code_wallet_recharge: string | null
  item_code_dlt_fee: string | null
  item_code_channel_subscription: string | null
  item_code_admin_credit: string | null
  configured: boolean
}

const baseUrl = ref('')
const apiKey = ref('')
const apiSecret = ref('')
const company = ref('')
const cgstAccountHead = ref('')
const sgstAccountHead = ref('')
const printFormat = ref('')
const customerGroup = ref('Commercial')
const territory = ref('India')
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
    cgstAccountHead.value = result.cgst_account_head ?? ''
    sgstAccountHead.value = result.sgst_account_head ?? ''
    printFormat.value = result.print_format ?? ''
    customerGroup.value = result.customer_group
    territory.value = result.territory
    salesInvoiceNamingSeries.value = result.sales_invoice_naming_series ?? ''
    itemCodeWalletRecharge.value = result.item_code_wallet_recharge ?? ''
    itemCodeDltFee.value = result.item_code_dlt_fee ?? ''
    itemCodeChannelSubscription.value = result.item_code_channel_subscription ?? ''
    itemCodeAdminCredit.value = result.item_code_admin_credit ?? ''
    configured.value = result.configured
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load ERPNext settings.')
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
        cgst_account_head: cgstAccountHead.value || null,
        sgst_account_head: sgstAccountHead.value || null,
        print_format: printFormat.value || null,
        customer_group: customerGroup.value,
        territory: territory.value,
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
              label="Customer group"
              placeholder="Commercial"
              hint="Must be a real (non-group/leaf) Customer Group in ERPNext — 'All Customer Groups' itself is a parent node and will be rejected."
              persistent-hint
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="territory"
              label="Territory"
              placeholder="India"
              hint="Same rule as Customer Group — 'All Territories' is a parent node, not a valid value."
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
            <AppTextField
              v-model="cgstAccountHead"
              label="CGST account head"
              placeholder="Output Tax CGST - COMPANY"
            />
          </VCol>
          <VCol cols="12" sm="6">
            <AppTextField
              v-model="sgstAccountHead"
              label="SGST account head"
              placeholder="Output Tax SGST - COMPANY"
              hint="Textzi's own already-computed GST amount is split in half and posted to these two accounts as an exact amount — never a percentage template, which could silently drift from what was actually charged. Both leave blank only if every invoice type you sync has zero GST."
              persistent-hint
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
