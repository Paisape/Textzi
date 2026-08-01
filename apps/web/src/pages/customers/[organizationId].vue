<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    staffArea: 'sales',
  },
})

const route = useRoute('customers-organization-id')
const authStore = useAuthStore()
const hasAccess = computed(() => authStore.loaded ? (authStore.isAdmin || authStore.staffArea === 'sales') : null)

type TeamMemberRow = { id: string, email: string, full_name: string, role: string, status: string }
type InvoiceRow = {
  id: string
  invoice_number: string | null
  type: string
  status: string
  total_amount: number
  issued_at: string | null
}
type HeaderRow = { id: string, header_id: string, value: string, status: string }
type PeIdRow = { id: string, value: string, operator: string, status: string, headers: HeaderRow[] }
type TemplateRow = { id: string, alias: string, dlt_template_id: string, category: string, status: string }
type EntityRow = { id: string, name: string, status: string, pe_ids: PeIdRow[], templates: TemplateRow[] }
type RechargeRow = { id: string, type: string, amount: number, reference: string | null, created_at: string }
type PaymentRow = { id: string, provider: string, provider_order_id: string, amount: number, status: string, created_at: string }

type OrgOverview = {
  organization_id: string
  organization_name: string
  gstin: string | null
  pan: string | null
  industry: string | null
  address: string | null
  created_at: string
  entities: EntityRow[]
  wallet_balance: number
  messages_sent: number
  total_recharged: number
  primary_contact_name: string | null
  primary_contact_email: string | null
  primary_contact_mobile: string | null
  primary_contact_two_factor_enabled: boolean
  users: TeamMemberRow[]
  invoices: InvoiceRow[]
  recharges: RechargeRow[]
  payments: PaymentRow[]
}

const PAYMENT_STATUS_COLORS: Record<string, string> = {
  created: 'warning',
  paid: 'success',
  failed: 'error',
}

const overview = ref<OrgOverview | null>(null)
const loadError = ref('')
const activeTab = ref('overview')
const actionError = ref('')
const togglingMemberId = ref<string | null>(null)
const togglingEntityId = ref<string | null>(null)

async function loadOverview() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!(authStore.isAdmin || authStore.staffArea === 'sales'))
      return
    overview.value = await $api<OrgOverview>(`/v1/admin/organizations/${route.params.organizationId}/overview`)
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load this customer.')
  }
}

async function onToggleMemberStatus(member: TeamMemberRow) {
  actionError.value = ''
  togglingMemberId.value = member.id
  const nextStatus = member.status === 'suspended' ? 'active' : 'suspended'
  try {
    const updated = await $api<{ status: string }>(`/v1/admin/users/${member.id}/status`, { method: 'PATCH', body: { status: nextStatus } })
    member.status = updated.status
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this member\'s status.')
  }
  finally {
    togglingMemberId.value = null
  }
}

async function onToggleEntityStatus(entity: EntityRow) {
  actionError.value = ''
  togglingEntityId.value = entity.id
  const nextStatus = entity.status === 'active' ? 'inactive' : 'active'
  try {
    const updated = await $api<{ status: string }>(`/v1/admin/entities/${entity.id}/status`, { method: 'PATCH', body: { status: nextStatus } })
    entity.status = updated.status
  }
  catch (error: any) {
    actionError.value = extractErrorMessage(error, 'Could not update this entity\'s status.')
  }
  finally {
    togglingEntityId.value = null
  }
}

onMounted(loadOverview)
</script>

<template>
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

  <VRow v-else-if="hasAccess && overview">
    <VCol cols="12" md="4">
      <VCard class="mb-6">
        <VCardText class="text-center">
          <VAvatar
            color="primary"
            variant="tonal"
            size="80"
            class="mb-4"
          >
            <span class="text-h4">{{ overview.organization_name.charAt(0) }}</span>
          </VAvatar>
          <h5 class="text-h5 mb-1">
            {{ overview.organization_name }}
          </h5>
          <div class="text-body-2 text-medium-emphasis mb-4">
            Member since {{ new Date(overview.created_at).toLocaleDateString('en-IN') }}
          </div>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex justify-space-around">
          <div class="text-center">
            <div class="text-h6">
              {{ overview.messages_sent.toLocaleString('en-IN') }}
            </div>
            <div class="text-body-2 text-medium-emphasis">
              Messages Sent
            </div>
          </div>
          <div class="text-center">
            <div class="text-h6">
              ₹{{ overview.total_recharged.toLocaleString('en-IN') }}
            </div>
            <div class="text-body-2 text-medium-emphasis">
              Total Recharged
            </div>
          </div>
        </VCardText>
      </VCard>

      <VCard>
        <VCardText>
          <h6 class="text-h6 mb-4">
            Details
          </h6>
          <div class="d-flex flex-column gap-y-3">
            <div>
              <span class="font-weight-medium">Primary Contact:</span>
              {{ overview.primary_contact_name || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">Email:</span>
              {{ overview.primary_contact_email || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">Mobile:</span>
              {{ overview.primary_contact_mobile || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">GSTIN:</span>
              {{ overview.gstin || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">PAN:</span>
              {{ overview.pan || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">Industry:</span>
              {{ overview.industry || '—' }}
            </div>
            <div>
              <span class="font-weight-medium">Address:</span>
              {{ overview.address || '—' }}
            </div>
          </div>
        </VCardText>
      </VCard>
    </VCol>

    <VCol cols="12" md="8">
      <VTabs v-model="activeTab" class="mb-6" show-arrows>
        <VTab value="overview">
          Overview
        </VTab>
        <VTab value="dlt">
          DLT Hierarchy
        </VTab>
        <VTab value="security">
          Security
        </VTab>
        <VTab value="billing">
          Billing & Invoices
        </VTab>
        <VTab value="recharges">
          Recharges
        </VTab>
        <VTab value="payments">
          Payments
        </VTab>
        <VTab value="team">
          Team
        </VTab>
      </VTabs>

      <VWindow v-model="activeTab">
        <VWindowItem value="overview">
          <VCard class="mb-6">
            <VCardText>
              <h6 class="text-h6 mb-2">
                Wallet Balance
              </h6>
              <div class="text-h4 mb-4">
                {{ overview.wallet_balance.toLocaleString('en-IN') }} SMS credits
              </div>
              <RouterLink :to="'/admin-wallet-credits'">
                Credit this customer's wallet →
              </RouterLink>
            </VCardText>
          </VCard>

          <VCard>
            <VCardText>
              <h6 class="text-h6 mb-4">
                Entities
              </h6>
              <VAlert
                v-if="actionError"
                type="error"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                {{ actionError }}
              </VAlert>
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Entity ID</th>
                    <th>Name</th>
                    <th>Status</th>
                    <th>PE IDs</th>
                    <th>Templates</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="entity in overview.entities"
                    :key="entity.id"
                  >
                    <td class="text-body-2">
                      {{ entity.id }}
                    </td>
                    <td>{{ entity.name }}</td>
                    <td>
                      <VChip
                        size="small"
                        :color="entity.status === 'active' ? 'success' : 'default'"
                        class="text-capitalize"
                      >
                        {{ entity.status }}
                      </VChip>
                    </td>
                    <td>{{ entity.pe_ids.length }}</td>
                    <td>{{ entity.templates.length }}</td>
                    <td>
                      <VBtn
                        size="small"
                        variant="text"
                        :color="entity.status === 'active' ? 'error' : 'success'"
                        :loading="togglingEntityId === entity.id"
                        @click="onToggleEntityStatus(entity)"
                      >
                        {{ entity.status === 'active' ? 'Deactivate' : 'Activate' }}
                      </VBtn>
                    </td>
                  </tr>
                  <tr v-if="!overview.entities.length">
                    <td colspan="6" class="text-center text-medium-emphasis">
                      No entities yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </VCardText>
          </VCard>
        </VWindowItem>

        <VWindowItem value="dlt">
          <VCard
            v-for="entity in overview.entities"
            :key="entity.id"
            class="mb-6"
          >
            <VCardTitle>{{ entity.name }}</VCardTitle>
            <VCardText>
              <h6 class="text-body-1 font-weight-medium mb-2">
                PE IDs & Headers
              </h6>
              <VTable density="compact" class="mb-4">
                <thead>
                  <tr>
                    <th>PE ID</th>
                    <th>Operator</th>
                    <th>Status</th>
                    <th>Header</th>
                    <th>Header Status</th>
                  </tr>
                </thead>
                <tbody>
                  <template
                    v-for="pe in entity.pe_ids"
                    :key="pe.id"
                  >
                    <tr v-if="!pe.headers.length">
                      <td>{{ pe.value }}</td>
                      <td class="text-capitalize">
                        {{ pe.operator }}
                      </td>
                      <td class="text-capitalize">
                        {{ pe.status }}
                      </td>
                      <td colspan="2" class="text-medium-emphasis">
                        No headers yet.
                      </td>
                    </tr>
                    <tr
                      v-for="(header, i) in pe.headers"
                      :key="header.id"
                    >
                      <td>{{ i === 0 ? pe.value : '' }}</td>
                      <td class="text-capitalize">
                        {{ i === 0 ? pe.operator : '' }}
                      </td>
                      <td class="text-capitalize">
                        {{ i === 0 ? pe.status : '' }}
                      </td>
                      <td>{{ header.value }} ({{ header.header_id }})</td>
                      <td class="text-capitalize">
                        {{ header.status }}
                      </td>
                    </tr>
                  </template>
                  <tr v-if="!entity.pe_ids.length">
                    <td colspan="5" class="text-center text-medium-emphasis">
                      No PE IDs yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>

              <h6 class="text-body-1 font-weight-medium mb-2">
                Templates
              </h6>
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Alias</th>
                    <th>DLT Template ID</th>
                    <th>Category</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="template in entity.templates"
                    :key="template.id"
                  >
                    <td>{{ template.alias }}</td>
                    <td>{{ template.dlt_template_id }}</td>
                    <td class="text-capitalize">
                      {{ template.category }}
                    </td>
                    <td class="text-capitalize">
                      {{ template.status }}
                    </td>
                  </tr>
                  <tr v-if="!entity.templates.length">
                    <td colspan="4" class="text-center text-medium-emphasis">
                      No templates yet.
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </VCardText>
          </VCard>
          <VAlert
            v-if="!overview.entities.length"
            type="info"
            variant="tonal"
          >
            This customer has no entities yet.
          </VAlert>
        </VWindowItem>

        <VWindowItem value="security">
          <VCard>
            <VCardText>
              <h6 class="text-h6 mb-4">
                Primary Contact Security
              </h6>
              <VChip
                :color="overview.primary_contact_two_factor_enabled ? 'success' : 'warning'"
                size="small"
              >
                2FA {{ overview.primary_contact_two_factor_enabled ? 'Enabled' : 'Disabled' }}
              </VChip>
            </VCardText>
          </VCard>
        </VWindowItem>

        <VWindowItem value="billing">
          <VCard>
            <VTable>
              <thead>
                <tr>
                  <th>Invoice #</th>
                  <th>Type</th>
                  <th>Total</th>
                  <th>Status</th>
                  <th>Issued</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="invoice in overview.invoices"
                  :key="invoice.id"
                >
                  <td>{{ invoice.invoice_number || '—' }}</td>
                  <td class="text-capitalize">
                    {{ invoice.type.replaceAll('_', ' ') }}
                  </td>
                  <td>₹{{ invoice.total_amount.toLocaleString('en-IN') }}</td>
                  <td>
                    <VChip
                      :color="invoice.status === 'issued' ? 'success' : 'warning'"
                      size="small"
                      class="text-capitalize"
                    >
                      {{ invoice.status }}
                    </VChip>
                  </td>
                  <td>{{ invoice.issued_at ? new Date(invoice.issued_at).toLocaleDateString('en-IN') : '—' }}</td>
                </tr>
                <tr v-if="!overview.invoices.length">
                  <td colspan="5" class="text-center text-medium-emphasis">
                    No invoices yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCard>
        </VWindowItem>

        <VWindowItem value="recharges">
          <VCard>
            <VTable>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Credits</th>
                  <th>Reference</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="recharge in overview.recharges"
                  :key="recharge.id"
                >
                  <td class="text-capitalize">
                    {{ recharge.type.replaceAll('_', ' ') }}
                  </td>
                  <td class="text-success">
                    +{{ recharge.amount.toLocaleString('en-IN') }}
                  </td>
                  <td>{{ recharge.reference ?? '—' }}</td>
                  <td>{{ new Date(recharge.created_at).toLocaleString('en-IN') }}</td>
                </tr>
                <tr v-if="!overview.recharges.length">
                  <td colspan="4" class="text-center text-medium-emphasis">
                    No recharges yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCard>
        </VWindowItem>

        <VWindowItem value="payments">
          <VCard>
            <VTable>
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Order ID</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="payment in overview.payments"
                  :key="payment.id"
                >
                  <td class="text-capitalize">
                    {{ payment.provider }}
                  </td>
                  <td>{{ payment.provider_order_id }}</td>
                  <td>₹{{ payment.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 }) }}</td>
                  <td>
                    <VChip
                      size="small"
                      :color="PAYMENT_STATUS_COLORS[payment.status] || 'default'"
                      class="text-capitalize"
                    >
                      {{ payment.status }}
                    </VChip>
                  </td>
                  <td>{{ new Date(payment.created_at).toLocaleString('en-IN') }}</td>
                </tr>
                <tr v-if="!overview.payments.length">
                  <td colspan="5" class="text-center text-medium-emphasis">
                    No payment orders yet.
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCard>
        </VWindowItem>

        <VWindowItem value="team">
          <VCard>
            <VCardText v-if="actionError">
              <VAlert
                type="error"
                variant="tonal"
                density="compact"
              >
                {{ actionError }}
              </VAlert>
            </VCardText>
            <VTable>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="member in overview.users"
                  :key="member.id"
                >
                  <td>{{ member.full_name }}</td>
                  <td>{{ member.email }}</td>
                  <td class="text-capitalize">
                    {{ member.role.replaceAll('_', ' ') }}
                  </td>
                  <td>
                    <VChip
                      size="small"
                      :color="member.status === 'suspended' ? 'error' : member.status === 'active' ? 'success' : 'warning'"
                      class="text-capitalize"
                    >
                      {{ member.status.replaceAll('_', ' ') }}
                    </VChip>
                  </td>
                  <td>
                    <VBtn
                      size="small"
                      variant="text"
                      :color="member.status === 'suspended' ? 'success' : 'error'"
                      :loading="togglingMemberId === member.id"
                      @click="onToggleMemberStatus(member)"
                    >
                      {{ member.status === 'suspended' ? 'Reactivate' : 'Suspend' }}
                    </VBtn>
                  </td>
                </tr>
              </tbody>
            </VTable>
          </VCard>
        </VWindowItem>
      </VWindow>
    </VCol>
  </VRow>
</template>
