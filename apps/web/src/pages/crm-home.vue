<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'crm',
  },
})

type CrmContact = { id: string, name: string, phone: string | null, email: string | null }
type Deal = { id: string, name: string | null, contact: CrmContact, value: number | null, stage: string, expected_close_date: string | null }
type Task = { id: string, title: string, type: string, due_at: string | null, priority: string }
type ActivityItem = { kind: string, label: string, at: string, link_id: string | null }
type CrmHome = {
  period_days: number
  leads_created: number
  deals_won: number
  deals_won_value: number
  deals_created: number
  open_pipeline_value: number
  tasks_overdue: number
  tasks_due_soon: number
  top_open_deals: Deal[]
  upcoming_tasks: Task[]
  recent_activity: ActivityItem[]
  at_risk_deals: Deal[]
}

const home = ref<CrmHome | null>(null)
const loading = ref(false)
const loadError = ref('')
const crmInactive = ref(false)
const periodDays = ref(30)

const PERIOD_OPTIONS = [
  { title: 'Last 7 days', value: 7 },
  { title: 'Last 30 days', value: 30 },
  { title: 'Last 90 days', value: 90 },
  { title: 'Last 12 months', value: 365 },
]

function inr(value: number) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)
}

function dealLabel(deal: Deal) {
  return deal.name || deal.contact.name
}

const ACTIVITY_ICONS: Record<string, string> = {
  lead_created: 'tabler-user-plus',
  deal_created: 'tabler-briefcase',
  deal_stage_changed: 'tabler-arrow-right',
  quote_sent: 'tabler-send',
  quote_signed: 'tabler-circle-check',
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

async function load() {
  loading.value = true
  loadError.value = ''
  crmInactive.value = false
  try {
    home.value = await $api<CrmHome>('/v1/crm/home', { params: { days: periodDays.value } })
  }
  catch (error: any) {
    if (error?.response?.status === 422)
      crmInactive.value = true
    else
      loadError.value = extractErrorMessage(error, 'Could not load your CRM dashboard.')
  }
  finally {
    loading.value = false
  }
}

watch(periodDays, load)
onMounted(load)
</script>

<template>
  <div class="d-flex flex-wrap align-center justify-space-between mb-1 ga-3">
    <h1 class="text-h4">
      CRM Home
    </h1>
    <VSelect
      v-model="periodDays"
      :items="PERIOD_OPTIONS"
      density="compact"
      variant="outlined"
      hide-details
      style="max-inline-size: 200px;"
    />
  </div>
  <p class="text-medium-emphasis mb-6">
    A snapshot of your pipeline, tasks, and recent activity.
    <RouterLink to="/crm-reports" class="font-weight-medium">
      View full reports
    </RouterLink>
  </p>

  <VAlert v-if="crmInactive" type="warning" variant="tonal" class="mb-4">
    Upgrade to the CRM plan to use leads, deals, and customers.
    <RouterLink to="/channels-crm?tab=billing" class="font-weight-medium">
      View plans
    </RouterLink>
  </VAlert>
  <VAlert v-else-if="loadError" type="error" variant="tonal" class="mb-4" closable @click:close="loadError = ''">
    {{ loadError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-4" />

  <template v-else-if="home">
    <VRow class="mb-2">
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Leads created" :value="String(home.leads_created)" />
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Deals created" :value="String(home.deals_created)" />
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Deals won" :value="String(home.deals_won)" :subtext="inr(home.deals_won_value)" color="success" />
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Open pipeline" :value="inr(home.open_pipeline_value)" />
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Tasks overdue" :value="String(home.tasks_overdue)" :color="home.tasks_overdue ? 'error' : undefined" />
      </VCol>
      <VCol cols="6" sm="4" md="2">
        <StatTile label="Due within 7 days" :value="String(home.tasks_due_soon)" />
      </VCol>
    </VRow>

    <VRow class="mb-2">
      <VCol cols="12" md="6">
        <VCard title="Top open deals">
          <VCardText v-if="!home.top_open_deals.length" class="text-medium-emphasis">
            No open deals yet.
          </VCardText>
          <VList v-else lines="two">
            <VListItem
              v-for="deal in home.top_open_deals"
              :key="deal.id"
              :to="{ name: 'crm-deals-id', params: { id: deal.id } }"
            >
              <VListItemTitle>{{ dealLabel(deal) }}</VListItemTitle>
              <VListItemSubtitle>{{ deal.stage }} &middot; {{ inr(deal.value || 0) }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard title="At-risk deals" subtitle="Open deals past their expected close date">
          <VCardText v-if="!home.at_risk_deals.length" class="text-medium-emphasis">
            Nothing at risk right now.
          </VCardText>
          <VList v-else lines="two">
            <VListItem
              v-for="deal in home.at_risk_deals"
              :key="deal.id"
              :to="{ name: 'crm-deals-id', params: { id: deal.id } }"
            >
              <template #prepend>
                <VIcon icon="tabler-alert-triangle" color="warning" />
              </template>
              <VListItemTitle>{{ dealLabel(deal) }}</VListItemTitle>
              <VListItemSubtitle>Expected close {{ formatDate(deal.expected_close_date!) }} &middot; {{ inr(deal.value || 0) }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </VCard>
      </VCol>
    </VRow>

    <VRow>
      <VCol cols="12" md="6">
        <VCard title="Upcoming tasks">
          <VCardText v-if="!home.upcoming_tasks.length" class="text-medium-emphasis">
            No open tasks with a due date.
          </VCardText>
          <VList v-else lines="two">
            <VListItem
              v-for="task in home.upcoming_tasks"
              :key="task.id"
              to="/crm-tasks"
            >
              <template #prepend>
                <VIcon icon="tabler-checkbox" />
              </template>
              <VListItemTitle>{{ task.title }}</VListItemTitle>
              <VListItemSubtitle>{{ task.type }} &middot; due {{ formatDate(task.due_at!) }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard title="Recent activity">
          <VCardText v-if="!home.recent_activity.length" class="text-medium-emphasis">
            Nothing yet.
          </VCardText>
          <VList v-else lines="two">
            <VListItem
              v-for="(item, index) in home.recent_activity"
              :key="`${item.kind}-${item.link_id}-${index}`"
            >
              <template #prepend>
                <VIcon :icon="ACTIVITY_ICONS[item.kind] ?? 'tabler-point'" />
              </template>
              <VListItemTitle>{{ item.label }}</VListItemTitle>
              <VListItemSubtitle>{{ formatDate(item.at) }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </VCard>
      </VCol>
    </VRow>
  </template>
</template>
