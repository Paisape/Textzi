<script setup lang="ts">
import WabaAutomationRulesPage from './waba-automation-rules.vue'
import WabaTemplatesPage from './waba-templates.vue'

definePage({
  meta: {
    layout: 'default',
  },
})

declare global {
  interface Window {
    FB?: {
      init: (config: Record<string, unknown>) => void
      login: (callback: (response: any) => void, options: Record<string, unknown>) => void
    }
    fbAsyncInit?: () => void
  }
}

type WabaStatus = {
  connected: boolean
  phone_number: string | null
  verified_name: string | null
  waba_id: string | null
  connected_at: string | null
  quality_rating: string | null
  messaging_tier: string | null
  status_checked_at: string | null
}

type BusinessProfile = {
  about: string | null
  address: string | null
  description: string | null
  email: string | null
  profile_picture_url: string | null
  websites: string[]
  vertical: string | null
}

const activeTab = ref<'connect' | 'templates' | 'automation' | 'canned' | 'labels' | 'billing' | 'hours-sla' | 'macros' | 'csat' | 'webhooks' | 'team'>('connect')

const status = ref<WabaStatus | null>(null)
const loadError = ref('')
const connecting = ref(false)
const connectError = ref('')
const disconnecting = ref(false)
const refreshingStatus = ref(false)
const refreshStatusError = ref('')
const registeringPhone = ref(false)
const registerPhoneResult = ref<{ ok: boolean, detail: string } | null>(null)
const registerPhonePin = ref('')

async function onRegisterPhone() {
  registerPhoneResult.value = null
  registeringPhone.value = true
  try {
    await $api('/v1/waba/register-phone', { method: 'POST', body: { pin: registerPhonePin.value.trim() || null } })
    registerPhoneResult.value = { ok: true, detail: 'Registered successfully -- this number can now send messages.' }
  }
  catch (error: any) {
    registerPhoneResult.value = { ok: false, detail: extractErrorMessage(error, 'Could not register this phone number.') }
  }
  finally {
    registeringPhone.value = false
  }
}

const qualityColor = computed(() => {
  const r = status.value?.quality_rating
  if (r === 'GREEN')
    return 'success'
  if (r === 'YELLOW')
    return 'warning'
  if (r === 'RED')
    return 'error'
  return 'default'
})

async function refreshWabaStatus() {
  refreshStatusError.value = ''
  refreshingStatus.value = true
  try {
    const result = await $api<{ quality_rating: string | null, messaging_tier: string | null, status_checked_at: string | null }>('/v1/waba/refresh-status', { method: 'POST' })
    if (status.value)
      Object.assign(status.value, result)
  }
  catch (error: any) {
    refreshStatusError.value = extractErrorMessage(error, 'Could not refresh status from Meta.')
  }
  finally {
    refreshingStatus.value = false
  }
}

// --- Direct connect (fallback when Embedded Signup isn't configured yet) ------------------

const directConnectOpen = ref(false)
const directTokenVisible = ref(false)
const directConnecting = ref(false)
const directConnectError = ref('')
const directForm = ref({ waba_id: '', phone_number_id: '', access_token: '', business_id: '' })

async function onDirectConnect() {
  directConnectError.value = ''
  directConnecting.value = true
  try {
    status.value = await $api<WabaStatus>('/v1/waba/connect-direct', {
      method: 'POST',
      body: {
        waba_id: directForm.value.waba_id.trim(),
        phone_number_id: directForm.value.phone_number_id.trim(),
        access_token: directForm.value.access_token.trim(),
        business_id: directForm.value.business_id.trim() || null,
      },
    })
    if (status.value.connected) {
      directConnectOpen.value = false
      directForm.value = { waba_id: '', phone_number_id: '', access_token: '', business_id: '' }
      loadBusinessProfile()
    }
  }
  catch (error: any) {
    directConnectError.value = extractErrorMessage(error, 'Could not complete the WhatsApp connection.')
  }
  finally {
    directConnecting.value = false
  }
}

// --- Business profile ---------------------------------------------------------------------

const profile = ref<BusinessProfile | null>(null)
const profileLoading = ref(false)
const profileError = ref('')
const profileSaving = ref(false)
const profileSaveSuccess = ref('')
const profileForm = ref({ about: '', address: '', description: '', email: '', websites: '' })

async function loadBusinessProfile() {
  profileLoading.value = true
  profileError.value = ''
  try {
    profile.value = await $api<BusinessProfile>('/v1/waba/business-profile')
    profileForm.value = {
      about: profile.value.about || '',
      address: profile.value.address || '',
      description: profile.value.description || '',
      email: profile.value.email || '',
      websites: (profile.value.websites || []).join(', '),
    }
  }
  catch (error: any) {
    profileError.value = extractErrorMessage(error, 'Could not load the business profile.')
  }
  finally {
    profileLoading.value = false
  }
}

async function saveBusinessProfile() {
  profileSaveSuccess.value = ''
  profileError.value = ''
  profileSaving.value = true
  try {
    profile.value = await $api<BusinessProfile>('/v1/waba/business-profile', {
      method: 'PUT',
      body: {
        about: profileForm.value.about || null,
        address: profileForm.value.address || null,
        description: profileForm.value.description || null,
        email: profileForm.value.email || null,
        websites: profileForm.value.websites ? profileForm.value.websites.split(',').map(w => w.trim()).filter(Boolean) : [],
      },
    })
    profileSaveSuccess.value = 'Saved.'
  }
  catch (error: any) {
    profileError.value = extractErrorMessage(error, 'Could not save the business profile.')
  }
  finally {
    profileSaving.value = false
  }
}

let sdkReadyPromise: Promise<void> | null = null
// Meta's Embedded Signup delivers the connected account's IDs via a postMessage event, separate
// from the FB.login() callback's authorization code -- the two arrive independently and can race,
// so this is populated by the listener and read (with a short wait) once the callback fires.
let capturedSignupData: { waba_id?: string, phone_number_id?: string, business_id?: string } | null = null

async function loadStatus() {
  loadError.value = ''
  try {
    status.value = await $api<WabaStatus>('/v1/waba/status')
    if (status.value.connected)
      loadBusinessProfile()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load WhatsApp connection status.')
  }
}

function loadFacebookSdk(appId: string): Promise<void> {
  if (sdkReadyPromise)
    return sdkReadyPromise
  sdkReadyPromise = new Promise((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB!.init({ appId, autoLogAppEvents: true, xfbml: true, version: 'v23.0' })
      resolve()
    }
    const script = document.createElement('script')
    script.src = 'https://connect.facebook.net/en_US/sdk.js'
    script.async = true
    script.defer = true
    script.onerror = () => {
      // Clear the cached promise on failure -- otherwise a transient blip (ad-blocker, flaky
      // network) permanently poisons every later "Connect WhatsApp" click for the rest of the
      // page's lifetime, since they'd all just get handed this same already-rejected promise
      // instead of actually retrying the script load.
      sdkReadyPromise = null
      reject(new Error('Could not load the Facebook SDK'))
    }
    document.body.appendChild(script)
  })
  return sdkReadyPromise
}

function onSignupMessage(event: MessageEvent) {
  // Exact-host check (not just "ends with facebook.com", which would also match an attacker's
  // "notfacebook.com" or "evilfacebook.com") -- not the real trust boundary either way (the
  // actual security guarantee is server-side: waba.py's /connect exchanges the authorization
  // `code` for a token using Textzi's own app secret, and Meta ties that code to a specific WABA,
  // so a spoofed postMessage with the wrong waba_id/phone_number_id would simply fail that
  // exchange, not grant access to anything) -- but a correct check costs nothing and avoids
  // capturedSignupData being overwritten with attacker-chosen values before the real one arrives.
  if (event.origin !== 'https://www.facebook.com' && event.origin !== 'https://web.facebook.com')
    return
  try {
    const data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
    if (data?.type === 'WA_EMBEDDED_SIGNUP' && data?.event === 'FINISH') {
      capturedSignupData = {
        waba_id: data.data?.waba_id,
        phone_number_id: data.data?.phone_number_id,
        business_id: data.data?.business_id,
      }
    }
  }
  catch {
    // Not a JSON postMessage we care about -- ignore anything that doesn't parse as ours.
  }
}

onMounted(() => {
  window.addEventListener('message', onSignupMessage)
  loadStatus()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onSignupMessage)
  if (loginTimeoutId)
    clearTimeout(loginTimeoutId)
})

let loginTimeoutId: ReturnType<typeof setTimeout> | undefined
let loginCallbackFired = false

async function handleLoginResponse(response: any) {
  loginCallbackFired = true
  if (loginTimeoutId)
    clearTimeout(loginTimeoutId)
  try {
    const code = response?.authResponse?.code
    if (!code) {
      connectError.value = 'WhatsApp connection was cancelled or did not complete.'
      return
    }
    // The code has only a 30-second TTL (per Meta's own docs) -- this wait is intentionally
    // short, just enough for the postMessage event to arrive if it hasn't already.
    for (let i = 0; i < 20 && !capturedSignupData?.waba_id; i++)
      await new Promise(resolve => setTimeout(resolve, 100))
    if (!capturedSignupData?.waba_id || !capturedSignupData?.phone_number_id) {
      connectError.value = 'Could not read the connected WhatsApp account details. Please try again.'
      return
    }
    status.value = await $api<WabaStatus>('/v1/waba/connect', {
      method: 'POST',
      body: {
        code,
        waba_id: capturedSignupData.waba_id,
        phone_number_id: capturedSignupData.phone_number_id,
        business_id: capturedSignupData.business_id,
      },
    })
    if (status.value.connected)
      loadBusinessProfile()
  }
  catch (error: any) {
    connectError.value = extractErrorMessage(error, 'Could not complete the WhatsApp connection.')
  }
  finally {
    connecting.value = false
  }
}

async function onConnect() {
  connectError.value = ''
  connecting.value = true
  capturedSignupData = null
  loginCallbackFired = false
  try {
    const config = await $api<{ app_id: string, config_id: string }>('/v1/waba/config')
    await loadFacebookSdk(config.app_id)
    window.FB!.login(handleLoginResponse, {
      config_id: config.config_id,
      response_type: 'code',
      override_default_response_type: true,
      extras: { setup: {} },
    })
    // Meta's own callback fires when the popup closes (success or cancel) -- but if a browser or
    // extension blocks the popup outright before FB's SDK can wire that up, the callback may
    // never fire at all, leaving the button spinning forever with connecting.value stuck true
    // (only handleLoginResponse's own finally block ever resets it). This is the fallback.
    loginTimeoutId = setTimeout(() => {
      if (!loginCallbackFired) {
        connecting.value = false
        connectError.value = 'The WhatsApp connection window didn\'t respond -- check if your browser blocked a popup, then try again.'
      }
    }, 90000)
  }
  catch (error: any) {
    connectError.value = extractErrorMessage(error, 'Could not start the WhatsApp connection.')
    connecting.value = false
  }
}

async function onDisconnect() {
  connectError.value = ''
  disconnecting.value = true
  try {
    status.value = await $api<WabaStatus>('/v1/waba/disconnect', { method: 'POST' })
  }
  catch (error: any) {
    connectError.value = extractErrorMessage(error, 'Could not disconnect WhatsApp.')
  }
  finally {
    disconnecting.value = false
  }
}

// --- Canned responses -----------------------------------------------------------------------

type CannedResponse = { id: string, shortcut: string, body: string }

const cannedResponses = ref<CannedResponse[]>([])
const cannedLoading = ref(false)
const cannedError = ref('')
const cannedLoaded = ref(false)

async function loadCannedResponses() {
  cannedLoading.value = true
  cannedError.value = ''
  try {
    cannedResponses.value = await $api<CannedResponse[]>('/v1/waba/canned-responses')
    cannedLoaded.value = true
  }
  catch (error: any) {
    cannedError.value = extractErrorMessage(error, 'Could not load canned responses.')
  }
  finally {
    cannedLoading.value = false
  }
}

const cannedDialog = ref(false)
const cannedForm = ref({ id: '', shortcut: '', body: '' })
const cannedSaving = ref(false)
const cannedFormError = ref('')

function openCannedDialog(item?: CannedResponse) {
  cannedForm.value = item ? { id: item.id, shortcut: item.shortcut, body: item.body } : { id: '', shortcut: '', body: '' }
  cannedFormError.value = ''
  cannedDialog.value = true
}

async function saveCanned() {
  if (!cannedForm.value.shortcut.trim() || !cannedForm.value.body.trim())
    return
  cannedSaving.value = true
  cannedFormError.value = ''
  try {
    const body = { shortcut: cannedForm.value.shortcut.trim(), body: cannedForm.value.body.trim() }
    if (cannedForm.value.id) {
      const updated = await $api<CannedResponse>(`/v1/waba/canned-responses/${cannedForm.value.id}`, { method: 'PUT', body })
      const i = cannedResponses.value.findIndex(c => c.id === updated.id)
      if (i !== -1)
        cannedResponses.value[i] = updated
    }
    else {
      cannedResponses.value.push(await $api<CannedResponse>('/v1/waba/canned-responses', { method: 'POST', body }))
    }
    cannedDialog.value = false
  }
  catch (error: any) {
    cannedFormError.value = extractErrorMessage(error, 'Could not save this canned response.')
  }
  finally {
    cannedSaving.value = false
  }
}

async function deleteCanned(item: CannedResponse) {
  try {
    await $api(`/v1/waba/canned-responses/${item.id}`, { method: 'DELETE' })
    cannedResponses.value = cannedResponses.value.filter(c => c.id !== item.id)
  }
  catch (error: any) {
    cannedError.value = extractErrorMessage(error, 'Could not delete this canned response.')
  }
}

// --- Labels -----------------------------------------------------------------------------------

type LabelItem = { id: string, scope: string, name: string, color: string }

const conversationLabels = ref<LabelItem[]>([])
const contactLabels = ref<LabelItem[]>([])
const labelsLoading = ref(false)
const labelsError = ref('')
const labelsLoaded = ref(false)

const LABEL_COLORS = ['primary', 'secondary', 'success', 'warning', 'error', 'info']

async function loadLabels() {
  labelsLoading.value = true
  labelsError.value = ''
  try {
    const [conv, contact] = await Promise.all([
      $api<LabelItem[]>('/v1/waba/labels', { params: { scope: 'conversation' } }),
      $api<LabelItem[]>('/v1/waba/labels', { params: { scope: 'contact' } }),
    ])
    conversationLabels.value = conv
    contactLabels.value = contact
    labelsLoaded.value = true
  }
  catch (error: any) {
    labelsError.value = extractErrorMessage(error, 'Could not load labels.')
  }
  finally {
    labelsLoading.value = false
  }
}

const labelDialog = ref(false)
const labelForm = ref({ scope: 'conversation' as 'conversation' | 'contact', name: '', color: 'primary' })
const labelSaving = ref(false)
const labelFormError = ref('')

function openLabelDialog(scope: 'conversation' | 'contact') {
  labelForm.value = { scope, name: '', color: 'primary' }
  labelFormError.value = ''
  labelDialog.value = true
}

async function createLabel() {
  if (!labelForm.value.name.trim())
    return
  labelSaving.value = true
  labelFormError.value = ''
  try {
    const label = await $api<LabelItem>('/v1/waba/labels', {
      method: 'POST',
      body: { scope: labelForm.value.scope, name: labelForm.value.name.trim(), color: labelForm.value.color },
    })
    if (label.scope === 'conversation')
      conversationLabels.value.push(label)
    else
      contactLabels.value.push(label)
    labelDialog.value = false
  }
  catch (error: any) {
    labelFormError.value = extractErrorMessage(error, 'Could not create this label.')
  }
  finally {
    labelSaving.value = false
  }
}

async function deleteLabel(item: LabelItem) {
  try {
    await $api(`/v1/waba/labels/${item.id}`, { method: 'DELETE' })
    conversationLabels.value = conversationLabels.value.filter(l => l.id !== item.id)
    contactLabels.value = contactLabels.value.filter(l => l.id !== item.id)
  }
  catch (error: any) {
    labelsError.value = extractErrorMessage(error, 'Could not delete this label.')
  }
}

watch(activeTab, tab => {
  if (tab === 'canned' && !cannedLoaded.value)
    loadCannedResponses()
  if (tab === 'labels' && !labelsLoaded.value)
    loadLabels()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    WhatsApp
  </h1>
  <p class="text-medium-emphasis mb-6">
    Connection, templates, automation, canned responses, and labels for your WhatsApp channel.
  </p>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="connect">
      Connect
    </VTab>
    <VTab value="templates">
      Templates
    </VTab>
    <VTab value="automation">
      Automation Rules
    </VTab>
    <VTab value="canned">
      Canned Responses
    </VTab>
    <VTab value="labels">
      Labels
    </VTab>
    <VTab value="billing">
      Billing
    </VTab>
    <VTab value="hours-sla">
      Hours & SLA
    </VTab>
    <VTab value="macros">
      Macros
    </VTab>
    <VTab value="csat">
      CSAT
    </VTab>
    <VTab value="webhooks">
      Webhooks
    </VTab>
    <VTab value="team">
      Team
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="connect">
      <p class="text-body-2 text-medium-emphasis mb-4">
        Textzi acts as your Meta Tech Provider -- your account and messaging costs are billed by
        Meta directly to your own payment method; any Textzi subscription is only for using
        Textzi's platform.
      </p>

      <VAlert v-if="loadError" type="error" variant="tonal" class="mb-6">
        {{ loadError }}
      </VAlert>

      <VCard v-else max-width="640">
        <VCardText>
          <VAlert v-if="connectError" type="error" variant="tonal" density="compact" class="mb-4">
            {{ connectError }}
          </VAlert>

          <template v-if="status?.connected">
            <VChip color="success" size="small" class="mb-4">
              Connected
            </VChip>
            <VTable density="compact" class="mb-4">
              <tbody>
                <tr>
                  <td class="text-medium-emphasis">
                    Number
                  </td>
                  <td>{{ status.phone_number || '—' }}</td>
                </tr>
                <tr>
                  <td class="text-medium-emphasis">
                    Display name
                  </td>
                  <td>{{ status.verified_name || '—' }}</td>
                </tr>
                <tr>
                  <td class="text-medium-emphasis">
                    Connected
                  </td>
                  <td>{{ status.connected_at ? new Date(status.connected_at).toLocaleString('en-IN') : '—' }}</td>
                </tr>
              </tbody>
            </VTable>
            <VAlert v-if="registerPhoneResult" :type="registerPhoneResult.ok ? 'success' : 'error'" variant="tonal" density="compact" class="mb-3">
              {{ registerPhoneResult.detail }}
            </VAlert>
            <div class="d-flex align-center flex-wrap ga-3 mb-3">
              <VTextField
                v-model="registerPhonePin" label="Two-step verification PIN (only if this number already had one set on Meta)"
                placeholder="6 digits" density="compact" style="max-width: 380px;" hide-details
              />
              <VBtn variant="tonal" :loading="registeringPhone" @click="onRegisterPhone">
                Register phone number
              </VBtn>
            </div>
            <VBtn color="error" variant="tonal" :loading="disconnecting" @click="onDisconnect">
              Disconnect
            </VBtn>
          </template>

          <template v-else>
            <VChip color="warning" size="small" class="mb-4">
              Not connected
            </VChip>
            <p class="text-body-2 text-medium-emphasis mb-4">
              You'll be asked to log in with Facebook and select or create your WhatsApp Business
              Account. This opens a secure window hosted by Meta.
            </p>
            <VBtn prepend-icon="tabler-brand-whatsapp" :loading="connecting" @click="onConnect">
              Connect WhatsApp
            </VBtn>

            <div class="mt-4">
              <VBtn size="small" variant="text" @click="directConnectOpen = !directConnectOpen">
                {{ directConnectOpen ? 'Hide direct connect' : 'Or connect directly with a token' }}
              </VBtn>
              <div v-if="directConnectOpen" class="mt-3" style="max-width: 480px;">
                <p class="text-caption text-medium-emphasis mb-3">
                  For when Embedded Signup isn't set up yet, or you already manage your own Meta
                  access token. Get these from Meta App Dashboard &gt; WhatsApp &gt; API Setup (a
                  free temporary token + test number, no App Review needed) or a permanent System
                  User token from Business Settings.
                </p>
                <VAlert v-if="directConnectError" type="error" variant="tonal" density="compact" class="mb-3">
                  {{ directConnectError }}
                </VAlert>
                <VTextField v-model="directForm.waba_id" label="WhatsApp Business Account ID" autocomplete="off" density="compact" class="mb-3" />
                <VTextField v-model="directForm.phone_number_id" label="Phone number ID" autocomplete="off" density="compact" class="mb-3" />
                <VTextField
                  v-model="directForm.access_token" label="Access token" autocomplete="off"
                  :type="directTokenVisible ? 'text' : 'password'"
                  :append-inner-icon="directTokenVisible ? 'tabler-eye-off' : 'tabler-eye'"
                  density="compact" class="mb-3"
                  @click:append-inner="directTokenVisible = !directTokenVisible"
                />
                <VTextField v-model="directForm.business_id" label="Business ID (optional)" autocomplete="off" density="compact" class="mb-4" />
                <VBtn
                  :loading="directConnecting"
                  :disabled="!directForm.waba_id.trim() || !directForm.phone_number_id.trim() || !directForm.access_token.trim()"
                  @click="onDirectConnect"
                >
                  Connect directly
                </VBtn>
              </div>
            </div>
          </template>
        </VCardText>
      </VCard>

      <VCard v-if="status?.connected" max-width="640" class="mt-6">
        <VCardText>
          <h2 class="text-h6 mb-3">
            Account standing
          </h2>
          <VAlert v-if="refreshStatusError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ refreshStatusError }}
          </VAlert>
          <VTable density="compact" class="mb-4">
            <tbody>
              <tr>
                <td class="text-medium-emphasis">
                  Quality rating
                </td>
                <td>
                  <VChip v-if="status.quality_rating" size="small" :color="qualityColor">
                    {{ status.quality_rating }}
                  </VChip>
                  <span v-else class="text-medium-emphasis">Not checked yet</span>
                </td>
              </tr>
              <tr>
                <td class="text-medium-emphasis">
                  Messaging tier
                </td>
                <td>{{ status.messaging_tier || '—' }}</td>
              </tr>
              <tr>
                <td class="text-medium-emphasis">
                  Last checked
                </td>
                <td>{{ status.status_checked_at ? new Date(status.status_checked_at).toLocaleString('en-IN') : 'Never' }}</td>
              </tr>
            </tbody>
          </VTable>
          <VBtn size="small" variant="tonal" :loading="refreshingStatus" @click="refreshWabaStatus">
            Refresh from Meta
          </VBtn>
        </VCardText>
      </VCard>

      <VCard v-if="status?.connected" max-width="640" class="mt-6">
        <VCardText>
          <h2 class="text-h6 mb-1">
            Business profile
          </h2>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Shown to customers on your WhatsApp Business profile.
          </p>
          <VAlert v-if="profileError" type="error" variant="tonal" density="compact" class="mb-3">
            {{ profileError }}
          </VAlert>
          <VAlert v-if="profileSaveSuccess" type="success" variant="tonal" density="compact" class="mb-3">
            {{ profileSaveSuccess }}
          </VAlert>
          <VProgressLinear v-if="profileLoading" indeterminate class="mb-3" />
          <template v-else-if="profile">
            <AppTextField v-model="profileForm.about" label="About" :maxlength="139" class="mb-3" />
            <VTextarea v-model="profileForm.description" label="Description" rows="2" class="mb-3" />
            <AppTextField v-model="profileForm.address" label="Address" class="mb-3" />
            <AppTextField v-model="profileForm.email" label="Email" class="mb-3" />
            <AppTextField v-model="profileForm.websites" label="Websites (comma-separated)" class="mb-4" />
            <VBtn :loading="profileSaving" @click="saveBusinessProfile">
              Save
            </VBtn>
          </template>
        </VCardText>
      </VCard>
    </VWindowItem>

    <VWindowItem value="templates">
      <WabaTemplatesPage />
    </VWindowItem>

    <VWindowItem value="automation">
      <WabaAutomationRulesPage />
    </VWindowItem>

    <VWindowItem value="canned">
      <div class="d-flex align-center justify-space-between mb-4">
        <p class="text-body-2 text-medium-emphasis mb-0">
          Saved `/shortcut` replies agents can pull into the composer while chatting.
        </p>
        <VBtn prepend-icon="tabler-plus" @click="openCannedDialog()">
          New canned response
        </VBtn>
      </div>
      <VAlert v-if="cannedError" type="error" variant="tonal" class="mb-4">
        {{ cannedError }}
      </VAlert>
      <VCard>
        <VTable>
          <thead>
            <tr>
              <th>Shortcut</th>
              <th>Body</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in cannedResponses" :key="item.id">
              <td>/{{ item.shortcut }}</td>
              <td class="text-truncate" style="max-width: 400px;">
                {{ item.body }}
              </td>
              <td class="text-right">
                <VBtn size="small" variant="text" icon="tabler-pencil" @click="openCannedDialog(item)" />
                <VBtn size="small" variant="text" icon="tabler-trash" @click="deleteCanned(item)" />
              </td>
            </tr>
          </tbody>
        </VTable>
        <p v-if="!cannedLoading && !cannedResponses.length" class="text-medium-emphasis text-center pa-6">
          No canned responses yet.
        </p>
      </VCard>
    </VWindowItem>

    <VWindowItem value="labels">
      <VAlert v-if="labelsError" type="error" variant="tonal" class="mb-4">
        {{ labelsError }}
      </VAlert>
      <VRow>
        <VCol cols="12" md="6">
          <VCard>
            <VCardText>
              <div class="d-flex align-center justify-space-between mb-3">
                <h2 class="text-h6">
                  Conversation labels
                </h2>
                <VBtn size="small" prepend-icon="tabler-plus" @click="openLabelDialog('conversation')">
                  New
                </VBtn>
              </div>
              <div class="d-flex flex-wrap ga-2">
                <VChip v-for="label in conversationLabels" :key="label.id" :color="label.color" closable @click:close="deleteLabel(label)">
                  {{ label.name }}
                </VChip>
              </div>
              <p v-if="!labelsLoading && !conversationLabels.length" class="text-medium-emphasis mb-0">
                No conversation labels yet.
              </p>
            </VCardText>
          </VCard>
        </VCol>
        <VCol cols="12" md="6">
          <VCard>
            <VCardText>
              <div class="d-flex align-center justify-space-between mb-3">
                <h2 class="text-h6">
                  Contact labels
                </h2>
                <VBtn size="small" prepend-icon="tabler-plus" @click="openLabelDialog('contact')">
                  New
                </VBtn>
              </div>
              <div class="d-flex flex-wrap ga-2">
                <VChip v-for="label in contactLabels" :key="label.id" :color="label.color" closable @click:close="deleteLabel(label)">
                  {{ label.name }}
                </VChip>
              </div>
              <p v-if="!labelsLoading && !contactLabels.length" class="text-medium-emphasis mb-0">
                No contact labels yet.
              </p>
            </VCardText>
          </VCard>
        </VCol>
      </VRow>
    </VWindowItem>

    <VWindowItem value="billing">
      <ChannelBillingPanel channel="waba" />
    </VWindowItem>

    <VWindowItem value="hours-sla">
      <WabaHoursSlaPanel />
    </VWindowItem>

    <VWindowItem value="macros">
      <WabaMacrosPanel />
    </VWindowItem>

    <VWindowItem value="csat">
      <WabaCsatPanel />
    </VWindowItem>

    <VWindowItem value="webhooks">
      <WabaWebhookPanel />
    </VWindowItem>

    <VWindowItem value="team">
      <WabaTeamCapacityPanel />
    </VWindowItem>
  </VWindow>

  <VDialog v-model="cannedDialog" max-width="480">
    <VCard>
      <VCardTitle>{{ cannedForm.id ? 'Edit canned response' : 'New canned response' }}</VCardTitle>
      <VCardText>
        <VAlert v-if="cannedFormError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ cannedFormError }}
        </VAlert>
        <AppTextField v-model="cannedForm.shortcut" label="Shortcut" placeholder="hours" :maxlength="25" class="mb-3" />
        <VTextarea v-model="cannedForm.body" label="Body" placeholder="We're open Mon-Sat, 10am-7pm." rows="3" :maxlength="500" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="cannedDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="cannedSaving" @click="saveCanned">
          Save
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="labelDialog" max-width="420">
    <VCard>
      <VCardTitle>New {{ labelForm.scope }} label</VCardTitle>
      <VCardText>
        <VAlert v-if="labelFormError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ labelFormError }}
        </VAlert>
        <AppTextField v-model="labelForm.name" label="Name" class="mb-3" />
        <VSelect v-model="labelForm.color" :items="LABEL_COLORS" label="Color" />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="labelDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="labelSaving" @click="createLabel">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
