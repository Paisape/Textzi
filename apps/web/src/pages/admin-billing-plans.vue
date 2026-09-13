<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const stepUp = useStepUpAuth()

type Plan = {
  id: string
  channel: string
  name: string
  period: string
  price: number
  message_limit: number | null
  user_limit: number | null
  active: boolean
  visible_to_customers: boolean
  feature_flags: string[] | null
}

const CRM_FEATURE_OPTIONS = [
  { title: 'Quotes', value: 'crm-quotes' },
  { title: 'Automation', value: 'crm-automation' },
  { title: 'Report Builder', value: 'crm-report-builder' },
  { title: 'Email channel', value: 'crm-email' },
  { title: 'Tickets / Helpdesk', value: 'tickets' },
]

const plans = ref<Plan[]>([])
const loading = ref(false)
const loadError = ref('')
const channelFilter = ref<'all' | 'waba' | 'crm'>('all')

async function loadPlans() {
  loading.value = true
  loadError.value = ''
  try {
    plans.value = await stepUp.withStepUp(() => $api<Plan[]>('/v1/admin/billing-plans'))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load billing plans.')
  }
  finally {
    loading.value = false
  }
}

const filteredPlans = computed(() => channelFilter.value === 'all' ? plans.value : plans.value.filter(p => p.channel === channelFilter.value))

const busyPlanId = ref<string | null>(null)

async function toggleActive(plan: Plan) {
  busyPlanId.value = plan.id
  try {
    const updated = await stepUp.withStepUp(() => $api<Plan>(`/v1/admin/billing-plans/${plan.id}`, {
      method: 'PUT',
      body: { channel: plan.channel, name: plan.name, period: plan.period, price: plan.price, message_limit: plan.message_limit, user_limit: plan.user_limit, active: !plan.active, visible_to_customers: plan.visible_to_customers },
    }))
    plan.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this plan.')
  }
  finally {
    busyPlanId.value = null
  }
}

async function toggleVisibility(plan: Plan) {
  busyPlanId.value = plan.id
  try {
    const updated = await stepUp.withStepUp(() => $api<Plan>(`/v1/admin/billing-plans/${plan.id}`, {
      method: 'PUT',
      body: { channel: plan.channel, name: plan.name, period: plan.period, price: plan.price, message_limit: plan.message_limit, user_limit: plan.user_limit, active: plan.active, visible_to_customers: !plan.visible_to_customers },
    }))
    plan.visible_to_customers = updated.visible_to_customers
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this plan.')
  }
  finally {
    busyPlanId.value = null
  }
}

// --- Feature-flags edit dialog -------------------------------------------------------------

const featuresDialog = ref(false)
const featuresError = ref('')
const featuresSaving = ref(false)
const featuresPlan = ref<Plan | null>(null)
const featuresRestrict = ref(false)
const featuresSelected = ref<string[]>([])

function openFeaturesDialog(plan: Plan) {
  featuresPlan.value = plan
  featuresRestrict.value = plan.feature_flags !== null
  featuresSelected.value = plan.feature_flags ? [...plan.feature_flags] : []
  featuresError.value = ''
  featuresDialog.value = true
}

async function saveFeatures() {
  if (!featuresPlan.value)
    return
  featuresSaving.value = true
  featuresError.value = ''
  const plan = featuresPlan.value
  try {
    const updated = await stepUp.withStepUp(() => $api<Plan>(`/v1/admin/billing-plans/${plan.id}`, {
      method: 'PUT',
      body: {
        channel: plan.channel, name: plan.name, period: plan.period, price: plan.price,
        message_limit: plan.message_limit, user_limit: plan.user_limit, active: plan.active,
        visible_to_customers: plan.visible_to_customers,
        feature_flags: featuresRestrict.value ? featuresSelected.value : null,
      },
    }))
    plan.feature_flags = updated.feature_flags
    featuresDialog.value = false
  }
  catch (error: any) {
    featuresError.value = extractErrorMessage(error, 'Could not update this plan\'s features.')
  }
  finally {
    featuresSaving.value = false
  }
}

async function deletePlan(plan: Plan) {
  busyPlanId.value = plan.id
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/billing-plans/${plan.id}`, { method: 'DELETE' }))
    await loadPlans()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this plan.')
  }
  finally {
    busyPlanId.value = null
  }
}

// --- Create dialog ---

const createDialog = ref(false)
const createError = ref('')
const creating = ref(false)
const form = ref({ channel: 'waba', name: '', period: 'monthly', price: 0, message_limit: null as number | null, user_limit: null as number | null, active: true, visible_to_customers: true, restrictFeatures: false, feature_flags: [] as string[] })

// CRM plans are monthly/quarterly only (no yearly tier) -- reset period if a channel switch
// leaves it on a value that channel no longer offers.
watch(() => form.value.channel, (channel) => {
  if (channel === 'crm' && form.value.period === 'yearly')
    form.value.period = 'monthly'
  if (channel === 'waba')
    form.value.restrictFeatures = false
})

function openCreateDialog() {
  form.value = { channel: 'waba', name: '', period: 'monthly', price: 0, message_limit: null, user_limit: null, active: true, visible_to_customers: true, restrictFeatures: false, feature_flags: [] }
  createError.value = ''
  createDialog.value = true
}

async function createPlan() {
  if (!form.value.name.trim() || !form.value.price)
    return
  creating.value = true
  createError.value = ''
  try {
    const plan = await stepUp.withStepUp(() => $api<Plan>('/v1/admin/billing-plans', {
      method: 'POST',
      body: {
        channel: form.value.channel, name: form.value.name, period: form.value.period, price: form.value.price,
        message_limit: form.value.message_limit, user_limit: form.value.user_limit, active: form.value.active,
        visible_to_customers: form.value.visible_to_customers,
        feature_flags: form.value.restrictFeatures ? form.value.feature_flags : null,
      },
    }))
    plans.value.push(plan)
    createDialog.value = false
  }
  catch (error: any) {
    createError.value = extractErrorMessage(error, 'Could not create this plan.')
  }
  finally {
    creating.value = false
  }
}

onMounted(loadPlans)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <h1 class="text-h4">
      Billing Plans
    </h1>
    <VBtn prepend-icon="tabler-plus" @click="openCreateDialog">
      New plan
    </VBtn>
  </div>
  <p class="text-medium-emphasis mb-6">
    Subscription tiers for the WhatsApp and CRM channels -- what customers see and pay for on
    their Manage &gt; Billing tab.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <VTabs v-model="channelFilter" class="mb-4">
    <VTab value="all">
      All
    </VTab>
    <VTab value="waba">
      WhatsApp
    </VTab>
    <VTab value="crm">
      CRM
    </VTab>
  </VTabs>

  <VCard>
    <VTable>
      <thead>
        <tr>
          <th>Channel</th>
          <th>Name</th>
          <th>Period</th>
          <th>Price</th>
          <th>Message limit</th>
          <th>Seat limit</th>
          <th>Active</th>
          <th>Customer-visible</th>
          <th>Features</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr v-for="plan in filteredPlans" :key="plan.id">
          <td>{{ plan.channel === 'waba' ? 'WhatsApp' : 'CRM' }}</td>
          <td>{{ plan.name }}</td>
          <td>{{ plan.period }}</td>
          <td>₹{{ plan.price.toLocaleString('en-IN') }}</td>
          <td>{{ plan.message_limit ?? '—' }}</td>
          <td>{{ plan.user_limit ?? '—' }}</td>
          <td>
            <VSwitch :model-value="plan.active" density="compact" hide-details :disabled="busyPlanId === plan.id" @update:model-value="toggleActive(plan)" />
          </td>
          <td>
            <VSwitch :model-value="plan.visible_to_customers" density="compact" hide-details :disabled="busyPlanId === plan.id" @update:model-value="toggleVisibility(plan)" />
          </td>
          <td>
            <VBtn v-if="plan.channel === 'crm'" size="small" variant="text" @click="openFeaturesDialog(plan)">
              {{ plan.feature_flags === null ? 'All' : `${plan.feature_flags.length} selected` }}
            </VBtn>
            <span v-else class="text-medium-emphasis">—</span>
          </td>
          <td>
            <VBtn size="small" variant="text" icon="tabler-trash" :loading="busyPlanId === plan.id" :disabled="busyPlanId === plan.id" @click="deletePlan(plan)" />
          </td>
        </tr>
      </tbody>
    </VTable>
    <p v-if="!loading && !filteredPlans.length" class="text-medium-emphasis text-center pa-6">
      No plans yet.
    </p>
  </VCard>

  <VDialog v-model="createDialog" max-width="480">
    <VCard>
      <VCardTitle>New billing plan</VCardTitle>
      <VCardText>
        <VAlert v-if="createError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ createError }}
        </VAlert>
        <VSelect
          v-model="form.channel"
          label="Channel"
          :items="[{ title: 'WhatsApp', value: 'waba' }, { title: 'CRM', value: 'crm' }]"
          class="mb-3"
        />
        <AppTextField v-model="form.name" label="Plan name" placeholder="Growth" class="mb-3" />
        <VSelect
          v-model="form.period"
          label="Billing period"
          :items="form.channel === 'crm'
            ? [{ title: 'Monthly', value: 'monthly' }, { title: 'Quarterly', value: 'quarterly' }]
            : [{ title: 'Monthly', value: 'monthly' }, { title: 'Quarterly', value: 'quarterly' }, { title: 'Yearly', value: 'yearly' }]"
          class="mb-3"
        />
        <AppTextField v-model.number="form.price" type="number" label="Price (pre-tax, ₹)" class="mb-3" />
        <AppTextField v-if="form.channel === 'waba'" v-model.number="form.message_limit" type="number" label="Message limit (optional)" class="mb-3" />
        <AppTextField v-model.number="form.user_limit" type="number" label="Seat limit (optional)" class="mb-3" />
        <VSwitch
          v-model="form.visible_to_customers"
          label="Visible to customers"
          hide-details
          class="mb-1"
        />
        <p class="text-caption text-medium-emphasis mb-4">
          Off for a custom/negotiated tier (e.g. "Unlimited") -- only reachable by granting it to a
          specific customer from their account page, never shown on the self-serve pricing page.
        </p>
        <template v-if="form.channel === 'crm'">
          <VSwitch
            v-model="form.restrictFeatures"
            label="Restrict this plan to specific features"
            hide-details
            class="mb-1"
          />
          <p class="text-caption text-medium-emphasis mb-3">
            Off means every CRM feature is unlocked -- the default for every plan. On lets you pick
            exactly which of the features below this plan includes; core CRM (Leads/Deals/Contacts/
            Companies/Tasks/Pipelines/Reports) is always included either way.
          </p>
          <VSelect
            v-if="form.restrictFeatures"
            v-model="form.feature_flags"
            label="Included features"
            :items="CRM_FEATURE_OPTIONS"
            multiple
            chips
            class="mb-1"
          />
        </template>
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="createDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="creating" @click="createPlan">
          Create
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="featuresDialog" max-width="480">
    <VCard v-if="featuresPlan">
      <VCardTitle>Features -- {{ featuresPlan.name }}</VCardTitle>
      <VCardText>
        <VAlert v-if="featuresError" type="error" variant="tonal" density="compact" class="mb-3">
          {{ featuresError }}
        </VAlert>
        <VSwitch
          v-model="featuresRestrict"
          label="Restrict this plan to specific features"
          hide-details
          class="mb-1"
        />
        <p class="text-caption text-medium-emphasis mb-3">
          Off means every CRM feature is unlocked. Core CRM (Leads/Deals/Contacts/Companies/Tasks/
          Pipelines/Reports) is always included either way.
        </p>
        <VSelect
          v-if="featuresRestrict"
          v-model="featuresSelected"
          label="Included features"
          :items="CRM_FEATURE_OPTIONS"
          multiple
          chips
        />
      </VCardText>
      <VCardText class="d-flex justify-end ga-3 pt-0">
        <VBtn variant="text" @click="featuresDialog = false">
          Cancel
        </VBtn>
        <VBtn :loading="featuresSaving" @click="saveFeatures">
          Save
        </VBtn>
      </VCardText>
    </VCard>
  </VDialog>
</template>
