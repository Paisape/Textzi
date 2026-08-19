<script setup lang="ts">
import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip } from 'chart.js'
import { Bar, Line } from 'vue-chartjs'

ChartJS.register(ArcElement, BarElement, CategoryScale, Legend, LinearScale, LineElement, PointElement, Tooltip)

definePage({
  meta: {
    layout: 'default',
    channel: 'sms',
  },
})

type FailureReason = { reason: string, count: number }
type VolumeDay = { date: string, sent: number, delivered: number, failed: number }
type Analytics = {
  total_sent: number
  delivered_count: number
  failed_count: number
  pending_count: number
  delivery_rate: number | null
  failure_reasons: FailureReason[]
  volume_by_day: VolumeDay[]
}

const RANGE_OPTIONS = [
  { title: 'Last 7 days', value: 7 },
  { title: 'Last 30 days', value: 30 },
  { title: 'Last 90 days', value: 90 },
]

const days = ref(30)
const analytics = ref<Analytics | null>(null)
const loading = ref(false)
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    analytics.value = await $api<Analytics>('/v1/reports/sms-analytics', { params: { days: days.value } })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load SMS analytics.')
  }
  finally {
    loading.value = false
  }
}

const volumeChartData = computed(() => ({
  labels: (analytics.value?.volume_by_day || []).map(d => new Date(d.date).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })),
  datasets: [
    { label: 'Delivered', data: (analytics.value?.volume_by_day || []).map(d => d.delivered), borderColor: '#28C76F', backgroundColor: '#28C76F', tension: 0.35 },
    { label: 'Failed', data: (analytics.value?.volume_by_day || []).map(d => d.failed), borderColor: '#EA5455', backgroundColor: '#EA5455', tension: 0.35 },
  ],
}))

const failureChartData = computed(() => ({
  labels: (analytics.value?.failure_reasons || []).map(f => f.reason),
  datasets: [{ label: 'Failures', data: (analytics.value?.failure_reasons || []).map(f => f.count), backgroundColor: '#EA5455' }],
}))

const chartOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' as const } } }
const barOptions = { responsive: true, maintainAspectRatio: false, indexAxis: 'y' as const, plugins: { legend: { display: false } } }

watch(days, load)
onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-4">
    <h1 class="text-h4 mb-0">
      SMS Analytics
    </h1>
    <VSelect v-model="days" :items="RANGE_OPTIONS" item-title="title" item-value="value" density="compact" hide-details style="max-inline-size: 200px;" />
  </div>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="analytics">
    <VRow>
      <VCol cols="6" sm="3">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Total sent
            </p>
            <p class="text-h6 mb-0">
              {{ analytics.total_sent }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="3">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Delivery rate
            </p>
            <p class="text-h6 mb-0">
              {{ analytics.delivery_rate !== null ? `${analytics.delivery_rate}%` : '—' }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="3">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Delivered
            </p>
            <p class="text-h6 mb-0 text-success">
              {{ analytics.delivered_count }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="6" sm="3">
        <VCard>
          <VCardText>
            <p class="text-caption text-medium-emphasis mb-1">
              Failed
            </p>
            <p class="text-h6 mb-0 text-error">
              {{ analytics.failed_count }}
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VRow class="mt-2">
      <VCol cols="12" md="7">
        <VCard class="h-100">
          <VCardText>
            <h2 class="text-h6 mb-4">
              Volume over time
            </h2>
            <div style="height: 280px;">
              <Line :data="volumeChartData" :options="chartOptions" />
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" md="5">
        <VCard class="h-100">
          <VCardText>
            <h2 class="text-h6 mb-4">
              Failure reasons
            </h2>
            <div v-if="analytics.failure_reasons.length" style="height: 280px;">
              <Bar :data="failureChartData" :options="barOptions" />
            </div>
            <p v-else class="text-medium-emphasis mb-0">
              No failed sends in this range.
            </p>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>
  </template>
</template>
