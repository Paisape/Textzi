<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

type FunnelStage = { stage: string, count: number, value: number }
type Reports = {
  funnel: FunnelStage[]
  forecast: number
  open_value: number
  won_value: number
  lost_value: number
  open_count: number
  won_count: number
  lost_count: number
  win_rate: number | null
}
type Pipeline = { id: string, name: string, stages: string[] }
type EmployeeSalesRow = { user_id: string, full_name: string, won_count: number, won_value: number }
type ProductSalesRow = { description: string, count: number, value: number }
type ExtendedReports = {
  by_employee: EmployeeSalesRow[]
  by_product: ProductSalesRow[]
  outstanding_count: number
  outstanding_value: number
  follow_up: { total: number, done: number, overdue: number, done_rate: number | null }
}

const pipelines = ref<Pipeline[]>([])
const pipelineId = ref<string | null>(null)
const reports = ref<Reports | null>(null)
const extended = ref<ExtendedReports | null>(null)
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

async function load() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    if (!pipelines.value.length)
      pipelines.value = await $api<Pipeline[]>('/v1/crm/pipelines')
    const [reportsResult, extendedResult] = await Promise.all([
      $api<Reports>('/v1/crm/reports', { params: pipelineId.value ? { pipeline_id: pipelineId.value } : {} }),
      $api<ExtendedReports>('/v1/crm/reports/extended'),
    ])
    reports.value = reportsResult
    extended.value = extendedResult
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load reports.')
  }
  finally {
    loading.value = false
  }
}

const maxFunnelValue = computed(() => {
  if (!reports.value?.funnel.length)
    return 1
  return Math.max(1, ...reports.value.funnel.map(f => f.value))
})

watch(pipelineId, load)
onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-3">
    <h1 class="text-h4">
      CRM Reports
    </h1>
    <VSelect
      v-if="pipelines.length > 1"
      v-model="pipelineId"
      :items="[{ title: 'All pipelines', value: null }, ...pipelines.map(p => ({ title: p.name, value: p.id }))]"
      density="compact" variant="outlined" style="max-width: 220px;"
    />
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, tickets, and customers.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>

  <template v-if="reports">
    <VRow class="mb-2">
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Forecast
            </p>
            <p class="text-h6 mb-0">
              {{ inr(reports.forecast) }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Open pipeline
            </p>
            <p class="text-h6 mb-0">
              {{ inr(reports.open_value) }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              {{ reports.open_count }} deals
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Won
            </p>
            <p class="text-h6 mb-0 text-success">
              {{ inr(reports.won_value) }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              {{ reports.won_count }} deals
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Lost
            </p>
            <p class="text-h6 mb-0 text-error">
              {{ inr(reports.lost_value) }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              {{ reports.lost_count }} deals
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Win rate
            </p>
            <p class="text-h6 mb-0">
              {{ reports.win_rate !== null ? `${reports.win_rate}%` : '—' }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard>
      <VCardText>
        <h2 class="text-h6 mb-4">
          Pipeline by stage
        </h2>
        <div v-if="reports.funnel.length" class="d-flex flex-column gap-3">
          <div v-for="stage in reports.funnel" :key="stage.stage">
            <div class="d-flex align-center justify-space-between mb-1">
              <span class="text-body-2 text-capitalize">{{ stage.stage }}</span>
              <span class="text-caption text-medium-emphasis">{{ stage.count }} deals · {{ inr(stage.value) }}</span>
            </div>
            <div class="bg-primary rounded" :style="{ width: `${(stage.value / maxFunnelValue) * 100}%`, height: '10px', minWidth: stage.value ? '4px' : '0' }" />
          </div>
        </div>
        <p v-else class="text-medium-emphasis mb-0">
          No open deals yet.
        </p>
      </VCardText>
    </VCard>
  </template>

  <template v-if="extended">
    <VRow class="mt-2">
      <VCol cols="12" sm="6" md="4">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Outstanding (quotes not yet invoiced)
            </p>
            <p class="text-h6 mb-0">
              {{ inr(extended.outstanding_value) }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              {{ extended.outstanding_count }} quote{{ extended.outstanding_count === 1 ? '' : 's' }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="4">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Follow-up completion
            </p>
            <p class="text-h6 mb-0">
              {{ extended.follow_up.done_rate !== null ? `${extended.follow_up.done_rate}%` : '—' }}
            </p>
            <p class="text-caption text-medium-emphasis mb-0">
              {{ extended.follow_up.done }} done · {{ extended.follow_up.overdue }} overdue · {{ extended.follow_up.total }} total
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VRow class="mt-2">
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h2 class="text-h6 mb-3">
              Sales by employee
            </h2>
            <VTable density="compact">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Deals won</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in extended.by_employee" :key="row.user_id">
                  <td>{{ row.full_name }}</td>
                  <td>{{ row.won_count }}</td>
                  <td>{{ inr(row.won_value) }}</td>
                </tr>
              </tbody>
            </VTable>
            <p v-if="!extended.by_employee.length" class="text-medium-emphasis text-center pa-4 mb-0">
              No won deals yet.
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h2 class="text-h6 mb-3">
              Sales by product
            </h2>
            <VTable density="compact">
              <thead>
                <tr>
                  <th>Product / line item</th>
                  <th>Count</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in extended.by_product" :key="row.description">
                  <td>{{ row.description }}</td>
                  <td>{{ row.count }}</td>
                  <td>{{ inr(row.value) }}</td>
                </tr>
              </tbody>
            </VTable>
            <p v-if="!extended.by_product.length" class="text-medium-emphasis text-center pa-4 mb-0">
              No accepted quotes yet.
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>
  </template>
</template>
