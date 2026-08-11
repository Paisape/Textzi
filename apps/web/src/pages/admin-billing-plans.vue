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
}

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

async function toggleActive(plan: Plan) {
  try {
    const updated = await stepUp.withStepUp(() => $api<Plan>(`/v1/admin/billing-plans/${plan.id}`, {
      method: 'PUT',
      body: { channel: plan.channel, name: plan.name, period: plan.period, price: plan.price, message_limit: plan.message_limit, user_limit: plan.user_limit, active: !plan.active },
    }))
    plan.active = updated.active
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this plan.')
  }
}

async function deletePlan(plan: Plan) {
  try {
    await stepUp.withStepUp(() => $api(`/v1/admin/billing-plans/${plan.id}`, { method: 'DELETE' }))
    await loadPlans()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this plan.')
  }
}

// --- Create dialog ---

const createDialog = ref(false)
const createError = ref('')
const creating = ref(false)
const form = ref({ channel: 'waba', name: '', period: 'monthly', price: 0, message_limit: null as number | null, user_limit: null as number | null, active: true })

function openCreateDialog() {
  form.value = { channel: 'waba', name: '', period: 'monthly', price: 0, message_limit: null, user_limit: null, active: true }
  createError.value = ''
  createDialog.value = true
}

async function createPlan() {
  if (!form.value.name.trim() || !form.value.price)
    return
  creating.value = true
  createError.value = ''
  try {
    const plan = await stepUp.withStepUp(() => $api<Plan>('/v1/admin/billing-plans', { method: 'POST', body: form.value }))
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
            <VSwitch :model-value="plan.active" density="compact" hide-details @update:model-value="toggleActive(plan)" />
          </td>
          <td>
            <VBtn size="small" variant="text" icon="tabler-trash" @click="deletePlan(plan)" />
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
          :items="[{ title: 'Monthly', value: 'monthly' }, { title: 'Quarterly', value: 'quarterly' }, { title: 'Yearly', value: 'yearly' }]"
          class="mb-3"
        />
        <AppTextField v-model.number="form.price" type="number" label="Price (pre-tax, ₹)" class="mb-3" />
        <AppTextField v-if="form.channel === 'waba'" v-model.number="form.message_limit" type="number" label="Message limit (optional)" class="mb-3" />
        <AppTextField v-model.number="form.user_limit" type="number" label="Seat limit (optional)" class="mb-3" />
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
</template>
