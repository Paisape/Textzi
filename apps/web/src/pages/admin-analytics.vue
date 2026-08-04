<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'sales',
  },
})

const authStore = useAuthStore()
const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'sales') : null)

type CountRow = { path?: string, country?: string, referrer?: string, device_type?: string, views?: number, sessions?: number }

type AnalyticsSummary = {
  total_sessions: number
  total_page_views: number
  sessions_last_7_days: number
  top_pages: CountRow[]
  top_countries: CountRow[]
  top_referrers: CountRow[]
  device_breakdown: CountRow[]
}

type SessionRow = {
  id: string
  user_id: string | null
  user_email: string | null
  country: string | null
  browser: string | null
  os: string | null
  device_type: string | null
  first_referrer: string | null
  first_seen: string
  last_seen: string
  page_view_count: number
}

const summary = ref<AnalyticsSummary | null>(null)
const sessions = ref<SessionRow[]>([])
const loadError = ref('')

async function loadAnalytics() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!(authStore.isAdmin || authStore.staffArea === 'sales'))
      return
    const [summaryResult, sessionsResult] = await Promise.all([
      $api<AnalyticsSummary>('/v1/admin/analytics/summary'),
      $api<SessionRow[]>('/v1/admin/analytics/sessions'),
    ])
    summary.value = summaryResult
    sessions.value = sessionsResult
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load visitor analytics.')
  }
}

onMounted(loadAnalytics)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Analytics
  </h1>
  <p class="text-medium-emphasis mb-6">
    Visitor traffic on the public marketing site — pages viewed, approximate location, device,
    and referrer, grouped into anonymous browser sessions. No name, email, mobile, or any
    cross-site browsing history is ever collected (see Privacy Policy, Sections 1 &amp; 7).
  </p>

  <VAlert
    v-if="hasAccess === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin, Operator Admin, and Sales Team roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <template v-else-if="hasAccess && summary">
    <VRow class="mb-2">
      <VCol cols="12" sm="6" md="4">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Total Sessions
            </div>
            <div class="text-h5">
              {{ summary.total_sessions.toLocaleString('en-IN') }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="4">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Total Page Views
            </div>
            <div class="text-h5">
              {{ summary.total_page_views.toLocaleString('en-IN') }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="4">
        <VCard>
          <VCardText>
            <div class="text-body-2 text-medium-emphasis mb-1">
              Sessions (Last 7 Days)
            </div>
            <div class="text-h5">
              {{ summary.sessions_last_7_days.toLocaleString('en-IN') }}
            </div>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VRow class="mb-2">
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-3">
              Top Pages
            </h6>
            <VTable density="compact">
              <tbody>
                <tr v-for="row in summary.top_pages" :key="row.path">
                  <td>{{ row.path }}</td>
                  <td class="text-right">
                    {{ row.views }}
                  </td>
                </tr>
                <tr v-if="!summary.top_pages.length">
                  <td class="text-center text-medium-emphasis">
                    No page views yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-3">
              Top Countries
            </h6>
            <VTable density="compact">
              <tbody>
                <tr v-for="row in summary.top_countries" :key="row.country">
                  <td>{{ row.country }}</td>
                  <td class="text-right">
                    {{ row.sessions }}
                  </td>
                </tr>
                <tr v-if="!summary.top_countries.length">
                  <td class="text-center text-medium-emphasis">
                    No location data yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VRow class="mb-6">
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-3">
              Top Referrers
            </h6>
            <VTable density="compact">
              <tbody>
                <tr v-for="row in summary.top_referrers" :key="row.referrer">
                  <td class="text-truncate" style="max-inline-size: 320px;">
                    {{ row.referrer }}
                  </td>
                  <td class="text-right">
                    {{ row.sessions }}
                  </td>
                </tr>
                <tr v-if="!summary.top_referrers.length">
                  <td class="text-center text-medium-emphasis">
                    No referrer data yet (mostly direct visits).
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" md="6">
        <VCard>
          <VCardText>
            <h6 class="text-h6 mb-3">
              Device Breakdown
            </h6>
            <VTable density="compact">
              <tbody>
                <tr v-for="row in summary.device_breakdown" :key="row.device_type">
                  <td class="text-capitalize">
                    {{ row.device_type }}
                  </td>
                  <td class="text-right">
                    {{ row.sessions }}
                  </td>
                </tr>
                <tr v-if="!summary.device_breakdown.length">
                  <td class="text-center text-medium-emphasis">
                    No device data yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard>
      <VCardText>
        <h6 class="text-h6">
          Recent Sessions
        </h6>
      </VCardText>
      <VTable>
        <thead>
          <tr>
            <th>Started</th>
            <th>Identified As</th>
            <th>Country</th>
            <th>Browser</th>
            <th>OS</th>
            <th>Device</th>
            <th>First Referrer</th>
            <th>Page Views</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="session in sessions" :key="session.id">
            <td>{{ new Date(session.first_seen).toLocaleString('en-IN') }}</td>
            <td>{{ session.user_email || '—' }}</td>
            <td>{{ session.country || '—' }}</td>
            <td>{{ session.browser || '—' }}</td>
            <td>{{ session.os || '—' }}</td>
            <td class="text-capitalize">
              {{ session.device_type || '—' }}
            </td>
            <td class="text-truncate" style="max-inline-size: 240px;">
              {{ session.first_referrer || 'Direct' }}
            </td>
            <td>{{ session.page_view_count }}</td>
          </tr>
          <tr v-if="!sessions.length">
            <td colspan="8" class="text-center text-medium-emphasis">
              No sessions recorded yet.
            </td>
          </tr>
        </tbody>
      </VTable>
    </VCard>
  </template>
</template>
