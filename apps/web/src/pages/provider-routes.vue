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

type ProviderRouteConfig = {
  endpoint: string
  method?: string
  auth_style?: string
  auth_key_name?: string | null
  param_mapping?: Record<string, string>
  user?: string
}

type ProviderRoute = {
  route_name: string
  provider_type: string
  config: ProviderRouteConfig
}

type RoutePolicy = {
  id: string
  subject_type: string
  subject_id: string
  routes: string[]
}

const loadError = ref('')
const routes = ref<ProviderRoute[]>([])
const policies = ref<RoutePolicy[]>([])

async function loadRoutes() {
  routes.value = await stepUp.withStepUp(() => $api<ProviderRoute[]>('/v1/admin/provider-routes'))
}

async function loadPolicies() {
  policies.value = await $api<RoutePolicy[]>('/v1/admin/route-policies')
}

async function load() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    await Promise.all([loadRoutes(), loadPolicies()])
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load provider routes.')
  }
}

// Provider route create
const newRouteName = ref('')
const newEndpoint = ref('')
const newMethod = ref('POST')
const newAuthStyle = ref('none')
const newAuthKeyName = ref('')
const newAuthValue = ref('')
const newMapTo = ref('to')
const newMapFrom = ref('from')
const newMapContent = ref('text')
const routeSubmitting = ref(false)
const routeError = ref('')

const METHOD_OPTIONS = ['GET', 'POST']
const AUTH_STYLE_OPTIONS = [
  { value: 'none', title: 'None' },
  { value: 'header', title: 'Custom header' },
  { value: 'query', title: 'Query parameter' },
  { value: 'bearer', title: 'Bearer token' },
]

async function onCreateRoute() {
  routeError.value = ''
  if (!newRouteName.value.trim() || !newEndpoint.value.trim()) {
    routeError.value = 'Enter a route name and the provider endpoint URL.'
    return
  }
  if (newAuthStyle.value !== 'none' && newAuthStyle.value !== 'bearer' && !newAuthKeyName.value.trim()) {
    routeError.value = 'Enter the auth parameter/header name for this auth style.'
    return
  }
  routeSubmitting.value = true
  try {
    await stepUp.withStepUp(() => $api('/v1/admin/provider-routes', {
      method: 'POST',
      body: {
        route_name: newRouteName.value.trim(),
        endpoint: newEndpoint.value.trim(),
        method: newMethod.value,
        auth_style: newAuthStyle.value,
        auth_key_name: newAuthKeyName.value.trim() || null,
        auth_value: newAuthValue.value.trim() || null,
        param_mapping: {
          to: newMapTo.value.trim() || 'to',
          from: newMapFrom.value.trim() || 'from',
          content: newMapContent.value.trim() || 'text',
        },
      },
    }))
    newRouteName.value = ''; newEndpoint.value = ''; newAuthKeyName.value = ''; newAuthValue.value = ''
    newMethod.value = 'POST'; newAuthStyle.value = 'none'
    newMapTo.value = 'to'; newMapFrom.value = 'from'; newMapContent.value = 'text'
    await loadRoutes()
  }
  catch (error: any) {
    routeError.value = extractErrorMessage(error, 'Could not save this provider route.')
  }
  finally {
    routeSubmitting.value = false
  }
}

// Tata Tele (TTBS) provider route create -- one route = one Textzi<->TTBS account, shared
// across every customer's messages (the agreement is between Textzi and Tata, not per-customer).
// PE_ID/Template_ID are deliberately NOT configured here -- those are resolved per-message at
// dispatch time (platform's own DLT identity for platform SMS, the sending customer's own
// registered DLT identity for tenant SMS).
const newTtbsRouteName = ref('')
const newTtbsEndpoint = ref('https://ttbssmsgw.tatatel.co.in/campaignService/campaigns/qs')
const newTtbsUser = ref('')
const newTtbsPswd = ref('')
const ttbsSubmitting = ref(false)
const ttbsError = ref('')
const createdWebhookUrl = ref('')
const createdWebhookRouteName = ref('')

async function onCreateTtbsRoute() {
  ttbsError.value = ''
  createdWebhookUrl.value = ''
  if (!newTtbsRouteName.value.trim() || !newTtbsEndpoint.value.trim() || !newTtbsUser.value.trim() || !newTtbsPswd.value.trim()) {
    ttbsError.value = 'Enter a route name, the TTBS endpoint, and Textzi\'s TTBS username/password.'
    return
  }
  ttbsSubmitting.value = true
  try {
    const result = await stepUp.withStepUp(() => $api<{ route_name: string, webhook_url: string | null }>('/v1/admin/provider-routes/ttbs', {
      method: 'POST',
      body: {
        route_name: newTtbsRouteName.value.trim(),
        endpoint: newTtbsEndpoint.value.trim(),
        user: newTtbsUser.value.trim(),
        pswd: newTtbsPswd.value.trim(),
      },
    }))
    createdWebhookRouteName.value = result.route_name
    createdWebhookUrl.value = result.webhook_url || ''
    newTtbsRouteName.value = ''; newTtbsUser.value = ''; newTtbsPswd.value = ''
    await loadRoutes()
  }
  catch (error: any) {
    ttbsError.value = extractErrorMessage(error, 'Could not save this TTBS provider route.')
  }
  finally {
    ttbsSubmitting.value = false
  }
}

const viewingWebhookRoute = ref<string | null>(null)
async function onViewWebhookUrl(routeName: string) {
  viewingWebhookRoute.value = routeName
  ttbsError.value = ''
  try {
    const result = await stepUp.withStepUp(() => $api<{ webhook_url: string | null, configured: boolean }>(`/v1/admin/provider-routes/${encodeURIComponent(routeName)}/webhook-url`))
    createdWebhookRouteName.value = routeName
    createdWebhookUrl.value = result.webhook_url || ''
    if (!result.configured)
      ttbsError.value = 'No webhook is set up for this route yet (or PUBLIC_API_BASE_URL is unset on the server) -- use "Generate Webhook" below to create one, then register it with Tata.'
  }
  catch (error: any) {
    ttbsError.value = extractErrorMessage(error, 'Could not fetch the webhook URL for this route.')
  }
  finally {
    viewingWebhookRoute.value = null
  }
}

const generatingWebhookRoute = ref<string | null>(null)
async function onGenerateWebhookSecret(routeName: string) {
  generatingWebhookRoute.value = routeName
  ttbsError.value = ''
  try {
    const result = await stepUp.withStepUp(() => $api<{ webhook_url: string | null, configured: boolean }>(`/v1/admin/provider-routes/${encodeURIComponent(routeName)}/regenerate-webhook-secret`, { method: 'POST' }))
    createdWebhookRouteName.value = routeName
    createdWebhookUrl.value = result.webhook_url || ''
    if (!result.configured)
      ttbsError.value = 'A webhook token was generated, but PUBLIC_API_BASE_URL is unset on the server, so no callback URL could be built.'
  }
  catch (error: any) {
    ttbsError.value = extractErrorMessage(error, 'Could not generate a webhook secret for this route.')
  }
  finally {
    generatingWebhookRoute.value = null
  }
}

const deletingRoute = ref<string | null>(null)
async function onDeleteRoute(routeName: string) {
  deletingRoute.value = routeName
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/provider-routes/${encodeURIComponent(routeName)}`, { method: 'DELETE' }))
    await loadRoutes()
  }
  catch (error: any) {
    routeError.value = extractErrorMessage(error, 'Could not remove this provider route.')
  }
  finally {
    deletingRoute.value = null
  }
}

// Route policy create
const newSubjectType = ref<'user' | 'group'>('user')
const newSubjectId = ref('')
const newPolicyRoutes = ref<string[]>([])
const policySubmitting = ref(false)
const policyError = ref('')

const availableRouteNames = computed(() => [...routes.value.map(r => r.route_name), 'default-simulated-route'])

async function onCreatePolicy() {
  policyError.value = ''
  if (!newSubjectId.value.trim()) {
    policyError.value = 'Enter the user id or group name this policy applies to.'
    return
  }
  if (!newPolicyRoutes.value.length) {
    policyError.value = 'Select at least one route, in priority order.'
    return
  }
  policySubmitting.value = true
  try {
    await $api('/v1/admin/route-policies', {
      method: 'POST',
      body: {
        subject_type: newSubjectType.value,
        subject_id: newSubjectId.value.trim(),
        routes: newPolicyRoutes.value,
      },
    })
    newSubjectId.value = ''; newPolicyRoutes.value = []
    await loadPolicies()
  }
  catch (error: any) {
    policyError.value = extractErrorMessage(error, 'Could not save this route policy.')
  }
  finally {
    policySubmitting.value = false
  }
}

const deletingPolicy = ref<string | null>(null)
async function onDeletePolicy(id: string) {
  deletingPolicy.value = id
  try {
    await $api(`/v1/admin/route-policies/${id}`, { method: 'DELETE' })
    await loadPolicies()
  }
  catch (error: any) {
    policyError.value = extractErrorMessage(error, 'Could not remove this route policy.')
  }
  finally {
    deletingPolicy.value = null
  }
}

onMounted(load)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Provider Routes
  </h1>
  <p class="text-medium-emphasis mb-6">
    Connect outbound HTTPS SMS providers and decide which users or groups send through which route.
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
          HTTPS provider routes
        </h6>
        <VAlert
          v-if="routeError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ routeError }}
        </VAlert>
        <VForm
          class="mb-6"
          @submit.prevent="onCreateRoute"
        >
          <VRow>
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newRouteName"
                label="Route name"
                placeholder="tata-primary"
                hint="Referenced from route policies below."
                persistent-hint
              />
            </VCol>
            <VCol
              cols="12"
              sm="5"
            >
              <AppTextField
                v-model="newEndpoint"
                label="Provider endpoint URL"
                placeholder="https://api.provider.example.com/v1/send"
              />
            </VCol>
            <VCol
              cols="12"
              sm="3"
            >
              <VSelect
                v-model="newMethod"
                :items="METHOD_OPTIONS"
                label="HTTP method"
              />
            </VCol>

            <VCol
              cols="12"
              sm="3"
            >
              <VSelect
                v-model="newAuthStyle"
                :items="AUTH_STYLE_OPTIONS"
                item-title="title"
                item-value="value"
                label="Auth style"
              />
            </VCol>
            <VCol
              cols="12"
              sm="3"
            >
              <AppTextField
                v-model="newAuthKeyName"
                label="Auth param/header name"
                placeholder="X-Api-Key"
                :disabled="newAuthStyle === 'none' || newAuthStyle === 'bearer'"
              />
            </VCol>
            <VCol
              cols="12"
              sm="6"
            >
              <AppTextField
                v-model="newAuthValue"
                label="Auth value (API key / token)"
                type="password"
                placeholder="Stored encrypted; leave blank if unauthenticated"
                :disabled="newAuthStyle === 'none'"
              />
            </VCol>

            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newMapTo"
                label="Field name: recipient"
                placeholder="to"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newMapFrom"
                label="Field name: sender"
                placeholder="from"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newMapContent"
                label="Field name: message body"
                placeholder="text"
              />
            </VCol>

            <VCol cols="12">
              <VBtn
                type="submit"
                :loading="routeSubmitting"
              >
                Save provider route
              </VBtn>
            </VCol>
          </VRow>
        </VForm>

        <VTable>
          <thead>
            <tr>
              <th>Route name</th>
              <th>Type</th>
              <th>Endpoint</th>
              <th>Method / Auth</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="route in routes"
              :key="route.route_name"
            >
              <td class="font-weight-medium">
                {{ route.route_name }}
              </td>
              <td>
                <VChip
                  size="small"
                  :color="route.provider_type === 'ttbs' ? 'success' : 'info'"
                >
                  {{ route.provider_type === 'ttbs' ? 'Tata Tele (TTBS)' : 'Generic HTTPS' }}
                </VChip>
              </td>
              <td class="text-truncate" style="max-inline-size: 320px;">
                {{ route.config.endpoint }}
              </td>
              <td class="text-capitalize">
                <template v-if="route.provider_type === 'ttbs'">
                  QS · user: {{ route.config.user }}
                </template>
                <template v-else>
                  {{ route.config.method }} · {{ route.config.auth_style }}
                </template>
              </td>
              <td class="d-flex gap-2">
                <VBtn
                  v-if="route.provider_type === 'ttbs'"
                  size="small"
                  variant="outlined"
                  :loading="viewingWebhookRoute === route.route_name"
                  @click="onViewWebhookUrl(route.route_name)"
                >
                  View webhook URL
                </VBtn>
                <VBtn
                  v-if="route.provider_type === 'ttbs'"
                  size="small"
                  variant="outlined"
                  :loading="generatingWebhookRoute === route.route_name"
                  @click="onGenerateWebhookSecret(route.route_name)"
                >
                  Generate webhook
                </VBtn>
                <VBtn
                  size="small"
                  variant="text"
                  color="error"
                  :loading="deletingRoute === route.route_name"
                  @click="onDeleteRoute(route.route_name)"
                >
                  Remove
                </VBtn>
              </td>
            </tr>
            <tr v-if="!routes.length">
              <td
                colspan="5"
                class="text-center text-medium-emphasis"
              >
                No provider routes configured yet — messages fall back to the simulated provider.
              </td>
            </tr>
          </tbody>
        </VTable>
      </VCardText>
    </VCard>

    <VCard class="mb-6">
      <VCardText>
        <h6 class="text-h6 mb-2">
          Tata Tele (TTBS) provider route
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          The username/password below is Textzi's own TTBS account — our agreement is with Tata,
          the customer's agreement is with us — so one set of credentials is used for every
          send, platform or customer. PE_ID/Template_ID are never configured here: they're
          resolved automatically per message (the platform's own DLT identity for platform SMS,
          the sending customer's own registered DLT identity for their messages).
        </p>
        <VAlert
          v-if="ttbsError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ ttbsError }}
        </VAlert>
        <VAlert
          v-if="createdWebhookUrl"
          type="success"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          <div class="mb-2">
            Give this URL to Tata as the DR callback for route "{{ createdWebhookRouteName }}":
          </div>
          <code class="d-block text-wrap" style="word-break: break-all;">{{ createdWebhookUrl }}</code>
        </VAlert>
        <VForm @submit.prevent="onCreateTtbsRoute">
          <VRow>
            <VCol
              cols="12"
              sm="3"
            >
              <AppTextField
                v-model="newTtbsRouteName"
                label="Route name"
                placeholder="ttbs-primary"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newTtbsEndpoint"
                label="TTBS endpoint URL"
              />
            </VCol>
            <VCol
              cols="12"
              sm="2"
            >
              <AppTextField
                v-model="newTtbsUser"
                label="TTBS username"
              />
            </VCol>
            <VCol
              cols="12"
              sm="3"
            >
              <AppTextField
                v-model="newTtbsPswd"
                label="TTBS password"
                type="password"
                placeholder="Stored encrypted"
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                type="submit"
                :loading="ttbsSubmitting"
              >
                Save TTBS route
              </VBtn>
            </VCol>
          </VRow>
        </VForm>
      </VCardText>
    </VCard>

    <VCard>
      <VCardText>
        <h6 class="text-h6 mb-4">
          Route policies
        </h6>
        <p class="text-body-2 text-medium-emphasis mb-4">
          Decides which route a user or group's messages go through. Without a policy, a subject always uses "default-simulated-route".
        </p>
        <VAlert
          v-if="policyError"
          type="error"
          variant="tonal"
          density="compact"
          class="mb-4"
        >
          {{ policyError }}
        </VAlert>
        <VForm
          class="mb-6"
          @submit.prevent="onCreatePolicy"
        >
          <VRow>
            <VCol
              cols="12"
              sm="3"
            >
              <VSelect
                v-model="newSubjectType"
                :items="[{ value: 'user', title: 'User id' }, { value: 'group', title: 'Group' }]"
                item-title="title"
                item-value="value"
                label="Subject type"
              />
            </VCol>
            <VCol
              cols="12"
              sm="4"
            >
              <AppTextField
                v-model="newSubjectId"
                label="Subject id"
                placeholder="user id, or group name"
              />
            </VCol>
            <VCol
              cols="12"
              sm="5"
            >
              <VSelect
                v-model="newPolicyRoutes"
                :items="availableRouteNames"
                label="Routes (priority order)"
                multiple
                chips
              />
            </VCol>
            <VCol cols="12">
              <VBtn
                type="submit"
                :loading="policySubmitting"
              >
                Save policy
              </VBtn>
            </VCol>
          </VRow>
        </VForm>

        <VTable>
          <thead>
            <tr>
              <th>Subject type</th>
              <th>Subject id</th>
              <th>Routes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="policy in policies"
              :key="policy.id"
            >
              <td class="text-capitalize">
                {{ policy.subject_type }}
              </td>
              <td>{{ policy.subject_id }}</td>
              <td>{{ policy.routes.join(' → ') }}</td>
              <td>
                <VBtn
                  size="small"
                  variant="text"
                  color="error"
                  :loading="deletingPolicy === policy.id"
                  @click="onDeletePolicy(policy.id)"
                >
                  Remove
                </VBtn>
              </td>
            </tr>
            <tr v-if="!policies.length">
              <td
                colspan="4"
                class="text-center text-medium-emphasis"
              >
                No route policies configured yet.
              </td>
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
