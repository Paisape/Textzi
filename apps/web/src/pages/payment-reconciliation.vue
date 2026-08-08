<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

definePage({
  meta: {
    layout: 'default',
    requiresAdmin: true,
  },
})

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.loaded ? authStore.isAdmin : null)

type OrderRow = {
  id: string
  entity_name: string
  organization_name: string
  provider: string
  provider_order_id: string
  amount: number
  purpose: string
  status: string
  created_at: string
}

const orders = ref<OrderRow[]>([])
const loadError = ref('')
const reconcilingId = ref<string | null>(null)
const reconcileResults = ref<Record<string, { our_status_before: string, razorpay_status: string, action_taken: string }>>({})

async function loadOrders() {
  loadError.value = ''
  try {
    await authStore.load()
    if (!authStore.isAdmin)
      return
    orders.value = await $api<OrderRow[]>('/v1/admin/payment-orders')
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load payment orders.')
  }
}

async function onReconcile(order: OrderRow) {
  reconcilingId.value = order.id
  try {
    const result = await $api(`/v1/admin/payment-orders/${order.id}/reconcile`, { method: 'POST' })
    reconcileResults.value[order.id] = result
    await loadOrders()
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not reconcile this order with Razorpay.')
  }
  finally {
    reconcilingId.value = null
  }
}

function statusColor(status: string): string {
  if (status === 'paid')
    return 'success'
  if (status === 'suspicious')
    return 'deep-orange'
  if (status === 'failed')
    return 'error'
  return 'warning'
}

onMounted(loadOrders)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Payment Reconciliation
  </h1>
  <p class="text-medium-emphasis mb-6">
    Orders stuck at "created" mean the customer never completed checkout, or Razorpay's
    confirmation never reached us. Check each one against Razorpay's own record to see the real
    status and reconcile it.
  </p>

  <VAlert
    v-if="isAdmin === false"
    type="warning"
    variant="tonal"
  >
    This page is restricted to Super Admin and Operator Admin roles.
  </VAlert>

  <VAlert
    v-else-if="loadError"
    type="error"
    variant="tonal"
  >
    {{ loadError }}
  </VAlert>

  <VCard v-else-if="isAdmin">
    <VTable>
      <thead>
        <tr>
          <th>Customer</th>
          <th>Provider Order</th>
          <th>Amount</th>
          <th>Purpose</th>
          <th>Status</th>
          <th>Created</th>
          <th>Reconciliation</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="order in orders"
          :key="order.id"
        >
          <td>
            <div>{{ order.organization_name }}</div>
            <div class="text-body-2 text-medium-emphasis">
              {{ order.entity_name }}
            </div>
          </td>
          <td><code>{{ order.provider_order_id }}</code></td>
          <td>₹{{ order.amount.toLocaleString('en-IN') }}</td>
          <td class="text-capitalize">
            {{ order.purpose.replaceAll('_', ' ') }}
          </td>
          <td>
            <VChip
              :color="statusColor(order.status)"
              size="small"
              class="text-capitalize"
            >
              {{ order.status }}
            </VChip>
          </td>
          <td>{{ new Date(order.created_at).toLocaleString('en-IN') }}</td>
          <td style="min-inline-size: 220px;">
            <div v-if="reconcileResults[order.id]" class="text-body-2">
              Razorpay: {{ reconcileResults[order.id].razorpay_status }}<br>
              Action: {{ reconcileResults[order.id].action_taken.replaceAll('_', ' ') }}
            </div>
          </td>
          <td>
            <VBtn
              size="small"
              :loading="reconcilingId === order.id"
              @click="onReconcile(order)"
            >
              Check with Razorpay
            </VBtn>
          </td>
        </tr>
        <tr v-if="!orders.length">
          <td
            colspan="8"
            class="text-center text-medium-emphasis"
          >
            No payment orders yet.
          </td>
        </tr>
      </tbody>
    </VTable>
  </VCard>
</template>
