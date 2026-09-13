<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type TallyConnection = { connected: boolean, company_name: string | null, gateway_url: string | null, enabled: boolean }

const connection = ref<TallyConnection>({ connected: false, company_name: null, gateway_url: null, enabled: false })
const loading = ref(false)
const loadError = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const saving = ref(false)
const disconnecting = ref(false)

const companyNameInput = ref('')
const gatewayUrlInput = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    connection.value = await $api<TallyConnection>('/v1/tally/connection')
    companyNameInput.value = connection.value.company_name || ''
    gatewayUrlInput.value = connection.value.gateway_url || ''
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load Tally export settings.')
  }
  finally {
    loading.value = false
  }
}

async function onSave() {
  saveError.value = ''
  saveSuccess.value = ''
  if (!companyNameInput.value.trim()) {
    saveError.value = 'Enter your exact Tally company name.'
    return
  }
  saving.value = true
  try {
    connection.value = await $api<TallyConnection>('/v1/tally/connect', {
      method: 'POST',
      body: { company_name: companyNameInput.value.trim(), gateway_url: gatewayUrlInput.value.trim() || null },
    })
    saveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save Tally export settings.')
  }
  finally {
    saving.value = false
  }
}

async function onDisconnect() {
  saveError.value = ''
  disconnecting.value = true
  try {
    await $api('/v1/tally/connection', { method: 'DELETE' })
    connection.value = { connected: false, company_name: null, gateway_url: null, enabled: false }
    companyNameInput.value = ''
    gatewayUrlInput.value = ''
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not turn off Tally export.')
  }
  finally {
    disconnecting.value = false
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Tally Export
  </h1>
  <p class="text-medium-emphasis mb-6">
    Export your invoices as Tally-importable vouchers. Tally has no cloud API of its own, so this
    always works as a downloadable XML file you import via Gateway of Tally &gt; Import &gt; Data --
    if your own Tally is reachable from the internet (a cloud-hosted Tally, VPN, or a
    deliberately port-forwarded connection), you can additionally push invoices directly instead.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VCard v-if="!loading" max-width="640">
    <VCardText>
      <VChip :color="connection.connected ? 'success' : 'default'" size="small" class="mb-4">
        {{ connection.connected ? 'Set up' : 'Not set up' }}
      </VChip>

      <VAlert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
        {{ saveError }}
      </VAlert>
      <VAlert v-if="saveSuccess" type="success" variant="tonal" density="compact" class="mb-4">
        {{ saveSuccess }}
      </VAlert>

      <AppTextField
        v-model="companyNameInput"
        label="Your Tally company name"
        placeholder="Exactly as it appears in Tally"
        class="mb-4"
      />
      <AppTextField
        v-model="gatewayUrlInput"
        label="Tally gateway URL (optional)"
        placeholder="http://203.0.113.5:9000"
        class="mb-1"
      />
      <p class="text-caption text-medium-emphasis mb-4">
        Leave blank to only download XML files -- works for every setup with zero networking.
        Fill in only if your Tally's own XML gateway (port 9000 by default) is reachable from the
        internet; Tally itself warns this should never be exposed publicly without a VPN or
        firewall rule limited to Textzi, so only set this if you understand that risk.
      </p>

      <div class="d-flex ga-3">
        <VBtn :loading="saving" @click="onSave">
          Save
        </VBtn>
        <VBtn v-if="connection.connected" variant="text" color="error" :loading="disconnecting" @click="onDisconnect">
          Turn off Tally export
        </VBtn>
      </div>
    </VCardText>
  </VCard>

  <p class="text-medium-emphasis mt-6">
    <RouterLink to="/invoices" class="font-weight-medium">
      Go to Invoices
    </RouterLink>
    to download or push a specific invoice once this is set up.
  </p>
</template>
