<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useStepUpAuth } from '@/composables/useStepUpAuth'

definePage({
  meta: {
    layout: 'default',
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

// -- Customer --------------------------------------------------------------
type ChannelStatus = { subscription_paid: boolean, dlt_status: string, channel_active: boolean }
type ReportsSummary = { total: number, submitted: number, failed: number, accepted: number }

const walletBalance = ref<number | null>(null)
const channelStatus = ref<ChannelStatus | null>(null)
const reportsSummary = ref<ReportsSummary | null>(null)
const customerLoadError = ref('')

const DLT_STATUS_LABELS: Record<string, string> = {
  approved: 'DLT approved',
  pending_review: 'DLT review pending',
  not_started: 'DLT not started',
}
const DLT_STATUS_COLORS: Record<string, string> = {
  approved: 'success',
  pending_review: 'warning',
  not_started: 'error',
}

async function loadCustomerDashboard() {
  customerLoadError.value = ''
  try {
    const [wallet, status, summary] = await Promise.all([
      $api<{ available_balance: number }>('/v1/wallet'),
      $api<ChannelStatus>('/v1/channels/sms/status'),
      $api<ReportsSummary>('/v1/channels/sms/reports/summary'),
    ])
    walletBalance.value = wallet.available_balance
    channelStatus.value = status
    reportsSummary.value = summary
  }
  catch (error: any) {
    customerLoadError.value = extractErrorMessage(error, 'Could not load your dashboard.')
  }
}

// -- Admin -------------------------------------------------------------------
type Notification = { id: string, severity: string, title: string, description: string, link: string | null }
type UsageSummary = { total_organizations: number, total_messages_sent: number, total_wallet_credits_issued: number, total_revenue: number }

const notifications = ref<Notification[]>([])
const usageSummary = ref<UsageSummary | null>(null)
const adminLoadError = ref('')
const stepUp = useStepUpAuth()

const SEVERITY_COLORS: Record<string, string> = { info: 'info', warning: 'warning', critical: 'error' }
const SEVERITY_ICONS: Record<string, string> = { info: 'tabler-info-circle', warning: 'tabler-alert-triangle', critical: 'tabler-alert-octagon' }

async function loadAdminDashboard() {
  adminLoadError.value = ''
  try {
    notifications.value = await $api<Notification[]>('/v1/admin/notifications')
    usageSummary.value = await stepUp.withStepUp(() => $api<UsageSummary>('/v1/admin/usage/summary'))
  }
  catch (error: any) {
    adminLoadError.value = extractErrorMessage(error, 'Could not load the platform overview.')
  }
}

async function load() {
  await authStore.load()
  if (authStore.isAdmin)
    await loadAdminDashboard()
  else
    await loadCustomerDashboard()
}

onMounted(load)
</script>

<template>
  <template v-if="isAdmin">
    <h1 class="text-h4 mb-1">
      Platform Overview
    </h1>
    <p class="text-medium-emphasis mb-6">
      What needs attention right now, and where to go next.
    </p>

    <VAlert v-if="adminLoadError" type="error" variant="tonal" class="mb-6">
      {{ adminLoadError }}
    </VAlert>

    <VRow class="mb-6">
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-building-store" size="16" class="me-1" />Customers
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ usageSummary?.total_organizations ?? '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-message-2" size="16" class="me-1" />Messages sent
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ usageSummary ? usageSummary.total_messages_sent.toLocaleString('en-IN') : '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-currency-rupee" size="16" class="me-1" />Total revenue
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ usageSummary ? `Rs. ${usageSummary.total_revenue.toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-coin" size="16" class="me-1" />Wallet credits issued
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ usageSummary ? usageSummary.total_wallet_credits_issued.toLocaleString('en-IN', { maximumFractionDigits: 0 }) : '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VRow>
      <VCol cols="12" md="7">
        <VCard title="Needs attention">
          <VCardText v-if="!notifications.length" class="text-medium-emphasis">
            Nothing needs attention right now.
          </VCardText>
          <VList v-else lines="two">
            <VListItem
              v-for="n in notifications"
              :key="n.id"
              :to="n.link ?? undefined"
            >
              <template #prepend>
                <VIcon :icon="SEVERITY_ICONS[n.severity] ?? 'tabler-info-circle'" :color="SEVERITY_COLORS[n.severity] ?? 'info'" />
              </template>
              <VListItemTitle>{{ n.title }}</VListItemTitle>
              <VListItemSubtitle>{{ n.description }}</VListItemSubtitle>
            </VListItem>
          </VList>
        </VCard>
      </VCol>
      <VCol cols="12" md="5">
        <VCard title="Quick links">
          <VCardText class="d-flex flex-column gap-2">
            <VBtn variant="tonal" prepend-icon="tabler-building-store" to="/customers">
              Customers
            </VBtn>
            <VBtn variant="tonal" prepend-icon="tabler-file-certificate" to="/dlt-requests">
              DLT Requests
            </VBtn>
            <VBtn variant="tonal" prepend-icon="tabler-receipt-rupee" to="/rate-cards">
              Rate Cards
            </VBtn>
            <VBtn variant="tonal" prepend-icon="tabler-chart-bar" to="/admin-usage">
              Usage & Revenue
            </VBtn>
            <VBtn variant="tonal" prepend-icon="tabler-server-cog" to="/platform-general-settings">
              Platform Settings
            </VBtn>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

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

  <template v-else-if="isAdmin === false">
    <h1 class="text-h4 mb-1">
      Dashboard
    </h1>
    <p class="text-medium-emphasis mb-6">
      Your account at a glance.
    </p>

    <VAlert v-if="customerLoadError" type="error" variant="tonal" class="mb-6">
      {{ customerLoadError }}
    </VAlert>

    <VAlert
      v-if="channelStatus && channelStatus.dlt_status !== 'approved'"
      :type="DLT_STATUS_COLORS[channelStatus.dlt_status] === 'error' ? 'error' : 'warning'"
      variant="tonal"
      class="mb-6"
    >
      Your SMS channel isn't fully active yet ({{ DLT_STATUS_LABELS[channelStatus.dlt_status] ?? channelStatus.dlt_status }}).
      <RouterLink to="/channels-sms">
        Complete DLT registration
      </RouterLink>
      to start sending.
    </VAlert>

    <VRow class="mb-6">
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-wallet" size="16" class="me-1" />Available balance
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ walletBalance !== null ? `${walletBalance.toLocaleString('en-IN', { maximumFractionDigits: 2 })} SMS` : '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-message-2" size="16" class="me-1" />Messages sent
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ reportsSummary?.total ?? '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-circle-check" size="16" class="me-1" />Submitted
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ reportsSummary?.submitted ?? '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
      <VCol cols="12" sm="6" md="3">
        <VCard>
          <VCardText>
            <p class="text-body-2 text-medium-emphasis mb-1">
              <VIcon icon="tabler-alert-circle" size="16" class="me-1" />Failed
            </p>
            <h4 class="text-h4 font-weight-bold">
              {{ reportsSummary?.failed ?? '—' }}
            </h4>
          </VCardText>
        </VCard>
      </VCol>
    </VRow>

    <VCard title="Quick actions">
      <VCardText class="d-flex flex-wrap gap-3">
        <VBtn prepend-icon="tabler-message-2" to="/sms">
          Send SMS
        </VBtn>
        <VBtn variant="tonal" prepend-icon="tabler-wallet" to="/wallet">
          Add Credits
        </VBtn>
        <VBtn variant="tonal" prepend-icon="tabler-receipt" to="/invoices">
          View Invoices
        </VBtn>
        <VBtn variant="tonal" prepend-icon="tabler-users-group" to="/team">
          Team
        </VBtn>
      </VCardText>
    </VCard>
  </template>
</template>
