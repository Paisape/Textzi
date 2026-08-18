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
type SavedReport = { id: string, name: string, object_type: ObjectType, group_by: string, measure: string, chart_type: ChartType, filters: Record<string, string>, schedule: 'weekly' | 'monthly' | null }
type DrillDownRow = { id: string, label: string, sublabel: string | null }
type AssignableUser = { id: string, full_name: string }
type Pipeline = { id: string, name: string }

const OBJECT_PATH: Record<ObjectType, string> = { deal: '/crm-deals', lead: '/crm-leads', task: '/crm-tasks' }

const OBJECT_OPTIONS = [
  { title: 'Deals', value: 'deal' },
  { title: 'Leads', value: 'lead' },
  { title: 'Tasks', value: 'task' },
]

const GROUP_BY_OPTIONS: Record<ObjectType, { title: string, value: string }[]> = {
  deal: [
    { title: 'Stage', value: 'stage' },
    { title: 'Status', value: 'status' },
    { title: 'Source', value: 'source' },
    { title: 'Owner', value: 'owner_user_id' },
    { title: 'Pipeline', value: 'pipeline_id' },
  ],
  lead: [
    { title: 'Status', value: 'status' },
    { title: 'Source', value: 'source' },
    { title: 'Owner', value: 'owner_user_id' },
  ],
  task: [
    { title: 'Type', value: 'type' },
    { title: 'Assigned to', value: 'assigned_user_id' },
    { title: 'Done?', value: 'done' },
  ],
}

const MEASURE_OPTIONS: Record<ObjectType, { title: string, value: string }[]> = {
  deal: [
    { title: 'Number of deals', value: 'count' },
    { title: 'Total value', value: 'sum_value' },
    { title: 'Average probability', value: 'avg_probability' },
  ],
  lead: [
    { title: 'Number of leads', value: 'count' },
    { title: 'Average score', value: 'avg_score' },
  ],
  task: [
    { title: 'Number of tasks', value: 'count' },
  ],
}

const CHART_TYPE_OPTIONS = [
  { title: 'Bar chart', value: 'bar' },
  { title: 'Donut chart', value: 'donut' },
  { title: 'Table', value: 'table' },
]

const users = ref<AssignableUser[]>([])
const pipelines = ref<Pipeline[]>([])
const savedReports = ref<SavedReport[]>([])
const loadError = ref('')
const crmInactive = ref(false)

const form = reactive({
  object_type: 'deal' as ObjectType,
  group_by: 'stage',
  measure: 'count',
  chart_type: 'bar' as ChartType,
  status: '' as string,
  pipeline_id: '' as string,
  owner_user_id: '' as string,
  done: '' as string,
})

watch(() => form.object_type, () => {
  form.group_by = GROUP_BY_OPTIONS[form.object_type][0].value
  form.measure = MEASURE_OPTIONS[form.object_type][0].value
  form.status = ''
  form.pipeline_id = ''
  form.owner_user_id = ''
  form.done = ''
})

function currentFilters(): Record<string, string> {
  const filters: Record<string, string> = {}
  if (form.object_type === 'deal') {
    if (form.status)
      filters.status = form.status
    if (form.pipeline_id)
      filters.pipeline_id = form.pipeline_id
    if (form.owner_user_id)
      filters.owner_user_id = form.owner_user_id
  }
  else if (form.object_type === 'lead') {
    if (form.status)
      filters.status = form.status
    if (form.owner_user_id)
      filters.owner_user_id = form.owner_user_id
  }
  else if (form.object_type === 'task') {
    if (form.done)
      filters.done = form.done
    if (form.owner_user_id)
      filters.assigned_user_id = form.owner_user_id
  }
  return filters
}

const rows = ref<ReportRow[] | null>(null)
const running = ref(false)
const runError = ref('')

async function run() {
  running.value = true
  runError.value = ''
  try {
    const result = await $api<{ rows: ReportRow[] }>('/v1/crm/reports/run', {
      method: 'POST',
      body: { object_type: form.object_type, group_by: form.group_by, measure: form.measure, filters: currentFilters() },
    })
    rows.value = result.rows
  }
  catch (error: any) {
    runError.value = extractErrorMessage(error, 'Could not run this report.')
  }
  finally {
    running.value = false
  }
}

const saveDialog = ref(false)
const saveName = ref('')
const saveSchedule = ref<'weekly' | 'monthly' | null>(null)
const saving = ref(false)
const saveError = ref('')

function openSaveDialog() {
  saveName.value = ''
  saveSchedule.value = null
  saveError.value = ''
  saveDialog.value = true
}

async function saveReport() {
  if (!saveName.value.trim())
    return
  saving.value = true
  saveError.value = ''
  try {
    const created = await $api<SavedReport>('/v1/crm/reports/saved', {
      method: 'POST',
      body: {
        name: saveName.value.trim(), object_type: form.object_type, group_by: form.group_by,
        measure: form.measure, chart_type: form.chart_type, filters: currentFilters(), schedule: saveSchedule.value,
      },
    })
    savedReports.value.unshift(created)
    saveDialog.value = false
  }
  catch (error: any) {
    saveError.value = extractErrorMessage(error, 'Could not save this report.')
  }
  finally {
    saving.value = false
  }
}

async function toggleSchedule(report: SavedReport, schedule: 'weekly' | 'monthly' | null) {
  try {
    const updated = await $api<SavedReport>(`/v1/crm/reports/saved/${report.id}`, { method: 'PATCH', body: { schedule } })
    report.schedule = updated.schedule
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not update this report\'s schedule.')
  }
}

async function loadSaved(report: SavedReport) {
  form.object_type = report.object_type
  await nextTick()
  form.group_by = report.group_by
  form.measure = report.measure
  form.chart_type = report.chart_type
  form.status = report.filters.status || ''
  form.pipeline_id = report.filters.pipeline_id || ''
  form.owner_user_id = report.filters.owner_user_id || report.filters.assigned_user_id || ''
  form.done = report.filters.done || ''
  running.value = true
  runError.value = ''
  try {
    const result = await $api<{ rows: ReportRow[] }>(`/v1/crm/reports/saved/${report.id}/run`)
    rows.value = result.rows
  }
  catch (error: any) {
    runError.value = extractErrorMessage(error, 'Could not run this report.')
  }
  finally {
    running.value = false
  }
}

async function deleteSaved(report: SavedReport) {
  try {
    await $api(`/v1/crm/reports/saved/${report.id}`, { method: 'DELETE' })
    savedReports.value = savedReports.value.filter(r => r.id !== report.id)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not delete this report.')
  }
}

const CHART_COLORS = ['#7367F0', '#28C76F', '#FF9F43', '#EA5455', '#00CFE8', '#82868B', '#5A8DEE', '#FFD93D']

const chartData = computed(() => ({
  labels: (rows.value || []).map(r => formatLabel(r.label)),
  datasets: [{ data: (rows.value || []).map(r => r.value), backgroundColor: CHART_COLORS, borderWidth: 0 }],
}))

// --- Drill-down: click a chart segment (or table row) to see the underlying records -----------

const drillDownOpen = ref(false)
const drillDownLabel = ref('')
const drillDownRows = ref<DrillDownRow[]>([])
const drillDownLoading = ref(false)

async function drillDown(label: string) {
  drillDownLabel.value = label
  drillDownOpen.value = true
  drillDownLoading.value = true
  drillDownRows.value = []
  try {
    const result = await $api<{ rows: DrillDownRow[] }>('/v1/crm/reports/drill-down', {
      method: 'POST',
      body: { object_type: form.object_type, group_by: form.group_by, group_value: label, filters: currentFilters() },
    })
    drillDownRows.value = result.rows
  }
  catch (error: any) {
    runError.value = extractErrorMessage(error, 'Could not load the underlying records.')
  }
  finally {
    drillDownLoading.value = false
  }
}

function onChartClick(_event: unknown, elements: { index: number }[]) {
  const index = elements[0]?.index
  if (index !== undefined && rows.value)
    drillDown(rows.value[index].label)
}

const chartOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, onClick: onChartClick }
const doughnutOptions = { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' as const } }, onClick: onChartClick }

onMounted(async () => {
  try {
    const [userResult, pipelineResult, savedResult] = await Promise.all([
      $api<AssignableUser[]>('/v1/waba/assignable-users'),
      $api<Pipeline[]>('/v1/crm/pipelines'),
      $api<SavedReport[]>('/v1/crm/reports/saved'),
    ])
    users.value = userResult
    pipelines.value = pipelineResult
    savedReports.value = savedResult
  }
  catch (error: any) {
    if (error?.response?.status === 422) {
      crmInactive.value = true
      return
    }
    loadError.value = extractErrorMessage(error, 'Could not load report builder.')
  }
  run()
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Report Builder
  </h1>
  <p class="text-medium-emphasis mb-6">
    Pick what to look at, how to group it, and how to measure it — no formulas, no code.
  </p>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use reports.
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <template v-if="!crmInactive">
    <VCard class="mb-4">
      <VCardText>
        <VRow>
          <VCol cols="12" sm="6" md="3">
            <VSelect v-model="form.object_type" :items="OBJECT_OPTIONS" label="Look at" density="compact" hide-details />
          </VCol>
          <VCol cols="12" sm="6" md="3">
            <VSelect v-model="form.group_by" :items="GROUP_BY_OPTIONS[form.object_type]" label="Group by" density="compact" hide-details />
          </VCol>
          <VCol cols="12" sm="6" md="3">
            <VSelect v-model="form.measure" :items="MEASURE_OPTIONS[form.object_type]" label="Measure" density="compact" hide-details />
          </VCol>
          <VCol cols="12" sm="6" md="3">
            <VSelect v-model="form.chart_type" :items="CHART_TYPE_OPTIONS" label="Show as" density="compact" hide-details />
          </VCol>
        </VRow>

        <VRow class="mt-1">
          <VCol v-if="form.object_type === 'deal' || form.object_type === 'lead'" cols="12" sm="6" md="3">
            <VSelect
              v-model="form.status" label="Filter: status" density="compact" hide-details clearable
              :items="form.object_type === 'deal' ? ['open', 'won', 'lost'] : ['new', 'contacted', 'qualified', 'unqualified', 'converted']"
            />
          </VCol>
          <VCol v-if="form.object_type === 'deal'" cols="12" sm="6" md="3">
            <VSelect
              v-model="form.pipeline_id" label="Filter: pipeline" density="compact" hide-details clearable
              :items="pipelines.map(p => ({ title: p.name, value: p.id }))"
            />
          </VCol>
          <VCol v-if="form.object_type !== 'task'" cols="12" sm="6" md="3">
            <VSelect
              v-model="form.owner_user_id" label="Filter: owner" density="compact" hide-details clearable
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
            />
          </VCol>
          <VCol v-if="form.object_type === 'task'" cols="12" sm="6" md="3">
            <VSelect
              v-model="form.done" label="Filter: done?" density="compact" hide-details clearable
              :items="[{ title: 'Open', value: 'false' }, { title: 'Done', value: 'true' }]"
            />
          </VCol>
          <VCol v-if="form.object_type === 'task'" cols="12" sm="6" md="3">
            <VSelect
              v-model="form.owner_user_id" label="Filter: assigned to" density="compact" hide-details clearable
              :items="users.map(u => ({ title: u.full_name, value: u.id }))"
            />
          </VCol>
        </VRow>

        <div class="d-flex gap-3 mt-4">
          <VBtn color="primary" :loading="running" @click="run">
            Run
          </VBtn>
          <VBtn variant="tonal" @click="openSaveDialog">
            Save this report
          </VBtn>
        </div>
      </VCardText>
    </VCard>

    <VAlert v-if="runError" type="error" variant="tonal" class="mb-4">
      {{ runError }}
    </VAlert>

    <VCard class="mb-4">
      <VCardText>
        <p v-if="rows && !rows.length" class="text-medium-emphasis text-center pa-6 mb-0">
          No data for this combination yet.
        </p>
        <template v-else-if="rows">
          <p class="text-caption text-medium-emphasis mb-2">
            Click a {{ form.chart_type === 'table' ? 'row' : 'segment' }} to see the underlying records.
          </p>
          <div style="block-size: 360px;">
            <Bar v-if="form.chart_type === 'bar'" :data="chartData" :options="chartOptions" />
            <Doughnut v-else-if="form.chart_type === 'donut'" :data="chartData" :options="doughnutOptions" />
            <VTable v-else>
              <thead>
                <tr>
                  <th>{{ GROUP_BY_OPTIONS[form.object_type].find(o => o.value === form.group_by)?.title }}</th>
                  <th>{{ MEASURE_OPTIONS[form.object_type].find(o => o.value === form.measure)?.title }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in rows" :key="row.label" class="cursor-pointer" @click="drillDown(row.label)">
                  <td>{{ formatLabel(row.label) }}</td>
                  <td>{{ row.value }}</td>
                </tr>
              </tbody>
            </VTable>
          </div>
        </template>
      </VCardText>
    </VCard>

    <VCard title="My saved reports">
      <VList v-if="savedReports.length" density="compact">
        <VListItem v-for="report in savedReports" :key="report.id" @click="loadSaved(report)">
          <VListItemTitle>{{ report.name }}</VListItemTitle>
          <VListItemSubtitle>{{ report.object_type }} · grouped by {{ report.group_by }}</VListItemSubtitle>
          <template #append>
            <VSelect
              :model-value="report.schedule" :items="[{ title: 'No email', value: null }, { title: 'Email weekly', value: 'weekly' }, { title: 'Email monthly', value: 'monthly' }]"
              density="compact" hide-details variant="plain" style="max-width: 150px;" class="me-2"
              @click.stop @update:model-value="(v: 'weekly' | 'monthly' | null) => toggleSchedule(report, v)"
            />
            <VBtn icon="tabler-trash" variant="text" size="small" @click.stop="deleteSaved(report)" />
          </template>
        </VListItem>
      </VList>
      <p v-else class="text-medium-emphasis text-center pa-6">
        No saved reports yet — build one above and save it.
      </p>
    </VCard>
  </template>

  <VDialog v-model="drillDownOpen" max-width="480">
    <VCard :title="formatLabel(drillDownLabel)">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="drillDownOpen = false" />
      </template>
      <VCardText>
        <VProgressLinear v-if="drillDownLoading" indeterminate class="mb-4" />
        <VList v-else-if="drillDownRows.length" density="compact">
          <VListItem
            v-for="row in drillDownRows" :key="row.id"
            :to="form.object_type === 'task' ? undefined : `${OBJECT_PATH[form.object_type]}/${row.id}`"
          >
            <VListItemTitle>{{ row.label }}</VListItemTitle>
            <VListItemSubtitle v-if="row.sublabel">
              {{ row.sublabel }}
            </VListItemSubtitle>
          </VListItem>
        </VList>
        <p v-else class="text-medium-emphasis text-center pa-6 mb-0">
          No records here.
        </p>
      </VCardText>
    </VCard>
  </VDialog>

  <VDialog v-model="saveDialog" max-width="420" persistent>
    <VCard title="Save this report">
      <template #append>
        <VBtn icon="tabler-x" variant="text" size="small" @click="saveDialog = false" />
      </template>
      <VCardText class="d-flex flex-column gap-4">
        <VAlert v-if="saveError" type="error" variant="tonal" density="compact">
          {{ saveError }}
        </VAlert>
        <VTextField v-model="saveName" label="Report name" density="compact" autofocus />
        <VSelect
          v-model="saveSchedule" label="Email this report to me (optional)" density="compact" hide-details clearable
          :items="[{ title: 'Weekly (every Monday)', value: 'weekly' }, { title: 'Monthly (1st of month)', value: 'monthly' }]"
        />
      </VCardText>
      <VCardActions>
        <VSpacer />
        <VBtn variant="text" @click="saveDialog = false">
          Cancel
        </VBtn>
        <VBtn color="primary" :loading="saving" :disabled="!saveName.trim()" @click="saveReport">
          Save
        </VBtn>
      </VCardActions>
    </VCard>
  </VDialog>
</template>
