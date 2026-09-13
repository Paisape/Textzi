<script setup lang="ts">
import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar, Doughnut } from 'vue-chartjs'

ChartJS.register(ArcElement, BarElement, CategoryScale, Legend, LinearScale, Tooltip)

definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type ObjectType = 'deal' | 'lead' | 'task'
type ChartType = 'bar' | 'donut' | 'table'
type ReportRow = { label: string, value: number }
type SavedReport = { id: string, name: string, object_type: ObjectType, group_by: string, measure: string, chart_type: ChartType }
type Dashboard = { id: string, name: string, widget_report_ids: string[], created_at: string }

const CHART_COLORS = ['#7367F0', '#28C76F', '#FF9F43', '#EA5455', '#00CFE8', '#82868B', '#5A8DEE', '#FFD93D']

const dashboards = ref<Dashboard[]>([])
const savedReports = ref<SavedReport[]>([])
const activeDashboardId = ref<string | null>(null)
const widgetData = ref<Record<string, ReportRow[]>>({})
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const crmInactiveMessage = ref('')
const running = ref(false)

const activeDashboard = computed(() => dashboards.value.find(d => d.id === activeDashboardId.value) || null)

function reportById(id: string) {
  return savedReports.value.find(r => r.id === id)
}

async function runActiveDashboard() {
  if (!activeDashboard.value)
    return
  running.value = true
  try {
    widgetData.value = await $api<Record<string, { rows: ReportRow[] }>>(`/v1/crm/dashboards/${activeDashboard.value.id}/run`)
      .then(result => Object.fromEntries(Object.entries(result).map(([id, r]) => [id, r.rows])))
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not run this dashboard.')
  }
  finally {
    running.value = false
  }
}

async function selectDashboard(id: string) {
  activeDashboardId.value = id
  await runActiveDashboard()
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    const [dashboardResult, reportResult] = await Promise.all([
      $api<Dashboard[]>('/v1/crm/dashboards'),
      $api<SavedReport[]>('/v1/crm/reports/saved'),
    ])
    dashboards.value = dashboardResult
    savedReports.value = reportResult
    if (dashboardResult.length)
      await selectDashboard(dashboardResult[0].id)
  }
  catch (error: any) {
    if (error?.response?.status === 422) {
      crmInactive.value = true
      crmInactiveMessage.value = extractErrorMessage(error, 'Upgrade your CRM plan to use this feature.')
    }
    else {
      loadError.value = extractErrorMessage(error, 'Could not load dashboards.')
    }
  }
  finally {
    loading.value = false
  }
}

// --- Create / rename dashboard ---

const dialog = ref(false)
const dialogName = ref('')
const editingDashboardId = ref<string | null>(null)
const saving = ref(false)
const saveError = ref('')

function openCreate() {
  editingDashboardId.value = null
  dialogName.value = ''
  saveError.value = ''
  dialog.value = true
}

function openRename(dashboard: Dashboard) {
  editingDashboardId.value = dashboard.id
  dialogName.value = dashboard.name
  saveError.value = ''
  dialog.value = true
}

async function saveDashboard() {
  if (!dialogName.value.trim())
    return
  saving.value = true
  saveError.value = ''
  try {
    if (editingDashboardId.value) {
      const updated = await $api<Dashboard>(`/v1/crm/dashboards/${editingDashboardId.value}`, { method: 'PATCH', body: { name: dialogName.value.trim() } })
      const index = dashboards.value.findIndex(d => d.id === editingDashboardId.value)
      if (index !== -1)
        dashboards.value[index] = updated
    }
    else {
      const created = await $api<Dashboard>('/v1/crm/dashboards', { method: 'POST', body: { name: dialogName.value.trim(), widget_report_ids: [] } })
      dashboards.value.unshift(created)
      await selectDashboard(created.id)
    }
    dialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save this dashboard.')
  }
  finally {
    saving.value = false
  }
}

const deletingDashboardId = ref<string | null>(null)

async function deleteDashboard(dashboard: Dashboard) {
  deletingDashboardId.value = dashboard.id
  try {
    await $api(`/v1/crm/dashboards/${dashboard.id}`, { method: 'DELETE' })
    dashboards.value = dashboards.value.filter(d => d.id !== dashboard.id)
    if (activeDashboardId.value === dashboard.id)
      activeDashboardId.value = dashboards.value[0]?.id || null
    if (activeDashboardId.value)
      await runActiveDashboard()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this dashboard.')
  }
  finally {
    deletingDashboardId.value = null
  }
}

// --- Add / remove widgets on the active dashboard ---

const addWidgetDialog = ref(false)
const addWidgetReportId = ref<string | null>(null)
const addWidgetSaving = ref(false)

const availableReportsToAdd = computed(() => {
  const used = new Set(activeDashboard.value?.widget_report_ids || [])
  return savedReports.value.filter(r => !used.has(r.id))
})

function openAddWidget() {
  addWidgetReportId.value = availableReportsToAdd.value[0]?.id || null
  addWidgetDialog.value = true
}

async function addWidget() {
  if (!activeDashboard.value || !addWidgetReportId.value)
    return
  addWidgetSaving.value = true
  try {
    const widgetIds = [...activeDashboard.value.widget_report_ids, addWidgetReportId.value]
    const updated = await $api<Dashboard>(`/v1/crm/dashboards/${activeDashboard.value.id}`, { method: 'PATCH', body: { widget_report_ids: widgetIds } })
    const index = dashboards.value.findIndex(d => d.id === updated.id)
    if (index !== -1)
      dashboards.value[index] = updated
    addWidgetDialog.value = false
    await runActiveDashboard()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not add this widget.')
  }
  finally {
    addWidgetSaving.value = false
  }
}

async function removeWidget(reportId: string) {
  if (!activeDashboard.value)
    return
  const widgetIds = activeDashboard.value.widget_report_ids.filter(id => id !== reportId)
  try {
    const updated = await $api<Dashboard>(`/v1/crm/dashboards/${activeDashboard.value.id}`, { method: 'PATCH', body: { widget_report_ids: widgetIds } })
    const index = dashboards.value.findIndex(d => d.id === updated.id)
    if (index !== -1)
      dashboards.value[index] = updated
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not remove this widget.')
  }
}

function chartDataFor(reportId: string) {
  const rows = widgetData.value[reportId] || []
  return {
    labels: rows.map(r => formatLabel(r.label)),
    datasets: [{ data: rows.map(r => r.value), backgroundColor: CHART_COLORS, borderWidth: 0 }],
  }
}

const chartOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
const doughnutOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' as const } } }

onMounted(loadAll)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1">
    <div>
      <h1 class="text-h4 mb-1">
        Dashboards
      </h1>
      <p class="text-medium-emphasis">
        Arrange your saved reports from the Report Builder into one screen.
      </p>
    </div>
    <VBtn color="primary" prepend-icon="tabler-plus" @click="openCreate">
      New dashboard
    </VBtn>
  </div>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    {{ crmInactiveMessage }}
    <RouterLink to="/channels-crm?tab=billing" class="font-weight-medium">
      View plans
    </RouterLink>
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <p v-if="!loading && !dashboards.length" class="text-medium-emphasis text-center pa-6">
      No dashboards yet — create one, then add widgets from your saved reports.
      <RouterLink :to="{ name: 'crm-report-builder' }">
        Build a report first
      </RouterLink> if you haven't saved any yet.
    </p>

    <template v-else-if="dashboards.length">
      <VTabs v-model="activeDashboardId" class="mb-4" @update:model-value="(id: string) => selectDashboard(id)">
        <VTab v-for="dashboard in dashboards" :key="dashboard.id" :value="dashboard.id">
          {{ dashboard.name }}
        </VTab>
      </VTabs>

      <div v-if="activeDashboard" class="d-flex ga-2 mb-4">
        <VBtn size="small" variant="tonal" prepend-icon="tabler-plus" :disabled="!availableReportsToAdd.length" @click="openAddWidget">
          Add widget
        </VBtn>
        <VBtn size="small" variant="text" prepend-icon="tabler-pencil" @click="openRename(activeDashboard)">
          Rename
        </VBtn>
        <VBtn size="small" variant="text" color="error" prepend-icon="tabler-trash" :loading="deletingDashboardId === activeDashboard.id" @click="deleteDashboard(activeDashboard)">
          Delete dashboard
        </VBtn>
      </div>

      <VProgressLinear v-if="running" indeterminate class="mb-4" />

      <p v-if="activeDashboard && !activeDashboard.widget_report_ids.length" class="text-medium-emphasis text-center pa-6">
        No widgets yet — add one of your saved reports.
      </p>

      <VRow v-else-if="activeDashboard">
        <VCol v-for="reportId in activeDashboard.widget_report_ids" :key="reportId" cols="12" md="6">
          <VCard v-if="reportById(reportId)">
            <VCardItem>
              <VCardTitle>{{ reportById(reportId)!.name }}</VCardTitle>
              <template #append>
                <VBtn icon="tabler-x" size="small" variant="text" title="Remove from dashboard" @click="removeWidget(reportId)" />
              </template>
            </VCardItem>
            <VCardText>
              <p v-if="!(widgetData[reportId] || []).length" class="text-medium-emphasis text-center pa-6 mb-0">
                No data for this report yet.
              </p>
              <div v-else style="block-size: 280px;">
                <Bar v-if="reportById(reportId)!.chart_type === 'bar'" :data="chartDataFor(reportId)" :options="chartOptions" />
                <Doughnut v-else-if="reportById(reportId)!.chart_type === 'donut'" :data="chartDataFor(reportId)" :options="doughnutOptions" />
                <VTable v-else density="compact">
                  <tbody>
                    <tr v-for="row in widgetData[reportId]" :key="row.label">
                      <td>{{ formatLabel(row.label) }}</td>
                      <td class="text-end">
                        {{ row.value }}
                      </td>
                    </tr>
                  </tbody>
                </VTable>
              </div>
            </VCardText>
          </VCard>
        </VCol>
      </VRow>
    </template>
  </template>

  <VDialog v-model="dialog" max-width="400" persistent>
    <VCard :title="editingDashboardId ? 'Rename dashboard' : 'New dashboard'">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="dialog = false" />
      </template>
      <VCardText>
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact" class="mb-4">
          {{ saveError }}
        </VAlert>
        <VTextField v-model="dialogName" label="Dashboard name" density="compact" autofocus />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="dialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!dialogName.trim()" @click="saveDashboard">
          {{ editingDashboardId ? 'Save' : 'Create' }}
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>

  <VDialog v-model="addWidgetDialog" max-width="400" persistent>
    <VCard title="Add widget">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="addWidgetDialog = false" />
      </template>
      <VCardText>
        <VSelect
          v-model="addWidgetReportId" label="Saved report" density="compact"
          :items="availableReportsToAdd.map(r => ({ title: r.name, value: r.id }))"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="addWidgetDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="addWidgetSaving" :disabled="!addWidgetReportId" @click="addWidget">
          Add
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
