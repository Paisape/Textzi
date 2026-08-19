<script setup lang="ts">
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'
import { themeConfig } from '@themeConfig'

definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

type LineItem = { description: string, hsn_code: string, quantity: number, unit_price: number }
type PublicQuote = {
  quote_number: string | null
  line_items: LineItem[]
  status: 'draft' | 'sent' | 'accepted' | 'rejected'
  subtotal: number
  cgst: number
  sgst: number
  igst: number
  total: number
  company_name: string
  contact_name: string
  signed_by_name: string | null
  signed_at: string | null
}

const route = useRoute()
const quoteId = route.params.id as string

const quote = ref<PublicQuote | null>(null)
const loading = ref(true)
const loadError = ref('')

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(value)
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    quote.value = await $api<PublicQuote>(`/v1/public/quote/${quoteId}`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'This quote link is invalid or has expired.')
  }
  finally {
    loading.value = false
  }
}

const signedByName = ref('')
const turnstileToken = ref('')
const turnstileRef = ref<InstanceType<typeof TurnstileWidget>>()
const signing = ref(false)
const signError = ref('')

async function sign(accept: boolean) {
  if (!signedByName.value.trim()) {
    signError.value = 'Enter your name to continue.'
    return
  }
  signing.value = true
  signError.value = ''
  try {
    quote.value = await $api<PublicQuote>(`/v1/public/quote/${quoteId}/sign`, {
      method: 'POST',
      body: { signed_by_name: signedByName.value.trim(), accept, turnstile_token: turnstileToken.value },
    })
  }
  catch (error: any) {
    signError.value = extractErrorMessage(error, 'Could not record your response. Please try again.')
    turnstileRef.value?.reset()
  }
  finally {
    signing.value = false
  }
}

onMounted(load)
</script>

<template>
  <RouterLink to="/">
    <div class="auth-logo d-flex align-center gap-x-3">
      <VNodeRenderer :nodes="themeConfig.app.logo" />
      <h1 class="auth-title">
        {{ themeConfig.app.title }}
      </h1>
    </div>
  </RouterLink>

  <div class="d-flex align-center justify-center bg-surface" style="min-block-size: calc(100vh - 80px); padding: 24px;">
    <VCard max-width="640" class="w-100">
      <VCardText v-if="loading" class="text-center pa-8">
        <VProgressCircular indeterminate color="primary" />
      </VCardText>

      <VCardText v-else-if="loadError" class="pa-8">
        <VAlert type="error" variant="tonal">
          {{ loadError }}
        </VAlert>
      </VCardText>

      <VCardText v-else-if="quote" class="pa-6">
        <div class="d-flex align-center justify-space-between mb-4">
          <div>
            <h1 class="text-h5 mb-1">
              Quote {{ quote.quote_number || '' }}
            </h1>
            <p class="text-body-2 text-medium-emphasis mb-0">
              For {{ quote.contact_name }}<span v-if="quote.company_name"> · {{ quote.company_name }}</span>
            </p>
          </div>
          <VChip
            :color="quote.status === 'accepted' ? 'success' : quote.status === 'rejected' ? 'error' : 'primary'"
            variant="tonal"
          >
            {{ quote.status }}
          </VChip>
        </div>

        <VTable density="compact" class="mb-4">
          <thead>
            <tr>
              <th>Description</th>
              <th>HSN</th>
              <th class="text-end">
                Qty
              </th>
              <th class="text-end">
                Unit price
              </th>
              <th class="text-end">
                Amount
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, idx) in quote.line_items" :key="idx">
              <td>{{ item.description }}</td>
              <td>{{ item.hsn_code }}</td>
              <td class="text-end">
                {{ item.quantity }}
              </td>
              <td class="text-end">
                {{ inr(item.unit_price) }}
              </td>
              <td class="text-end">
                {{ inr(item.quantity * item.unit_price) }}
              </td>
            </tr>
          </tbody>
        </VTable>

        <div class="d-flex flex-column ga-1 mb-4" style="max-inline-size: 260px; margin-inline-start: auto;">
          <div class="d-flex justify-space-between text-body-2">
            <span class="text-medium-emphasis">Subtotal</span>
            <span>{{ inr(quote.subtotal) }}</span>
          </div>
          <div v-if="quote.cgst" class="d-flex justify-space-between text-body-2">
            <span class="text-medium-emphasis">CGST</span>
            <span>{{ inr(quote.cgst) }}</span>
          </div>
          <div v-if="quote.sgst" class="d-flex justify-space-between text-body-2">
            <span class="text-medium-emphasis">SGST</span>
            <span>{{ inr(quote.sgst) }}</span>
          </div>
          <div v-if="quote.igst" class="d-flex justify-space-between text-body-2">
            <span class="text-medium-emphasis">IGST</span>
            <span>{{ inr(quote.igst) }}</span>
          </div>
          <VDivider class="my-1" />
          <div class="d-flex justify-space-between text-h6">
            <span>Total</span>
            <span>{{ inr(quote.total) }}</span>
          </div>
        </div>

        <template v-if="quote.status === 'sent'">
          <VDivider class="mb-4" />
          <p class="text-body-2 font-weight-medium mb-2">
            Accept or reject this quote
          </p>
          <VAlert v-if="signError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ signError }}
          </VAlert>
          <VTextField v-model="signedByName" label="Your name" density="compact" class="mb-3" />
          <TurnstileWidget id="turnstile-quote" ref="turnstileRef" v-model="turnstileToken" class="mb-3" />
          <div class="d-flex ga-2">
            <VBtn color="success" :loading="signing" @click="sign(true)">
              Accept quote
            </VBtn>
            <VBtn color="error" variant="outlined" :loading="signing" @click="sign(false)">
              Reject
            </VBtn>
          </div>
        </template>

        <VAlert v-else-if="quote.signed_by_name" type="success" variant="tonal" class="mt-2">
          {{ quote.status === 'accepted' ? 'Accepted' : 'Rejected' }} by {{ quote.signed_by_name }}
          <span v-if="quote.signed_at">on {{ new Date(quote.signed_at).toLocaleDateString() }}</span>
        </VAlert>
      </VCardText>
    </VCard>
  </div>
</template>
