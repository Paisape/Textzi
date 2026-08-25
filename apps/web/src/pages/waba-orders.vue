<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
    channel: 'waba',
  },
})

type OrderItem = {
  product_retailer_id: string
  product_name: string | null
  quantity: number
  item_price: number | null
  currency: string | null
}
type Order = {
  id: string
  contact_id: string
  contact_name: string | null
  conversation_id: string
  status: string
  total_amount: number | null
  currency: string | null
  created_at: string
  status_updated_at: string | null
  items: OrderItem[]
}

const STATUSES = ['new', 'confirmed', 'shipped', 'delivered', 'cancelled'] as const

const statusColor: Record<string, string> = {
  new: 'info',
  confirmed: 'primary',
  shipped: 'warning',
  delivered: 'success',
  cancelled: 'error',
}

const orders = ref<Order[]>([])
const loading = ref(false)
const loadError = ref('')
const statusFilter = ref<string | null>(null)
const expandedId = ref<string | null>(null)
const updatingId = ref<string | null>(null)
const updateError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    orders.value = await $api<Order[]>('/v1/waba/orders', { params: statusFilter.value ? { status: statusFilter.value } : {} })
  }
  catch (error: any) {
    loadError.value = extractErrorMessage(error, 'Could not load orders.')
  }
  finally {
    loading.value = false
  }
}

function toggleExpand(orderId: string) {
  expandedId.value = expandedId.value === orderId ? null : orderId
}

async function setStatus(order: Order, status: string) {
  updatingId.value = order.id
  updateError.value = ''
  try {
    const updated = await $api<Order>(`/v1/waba/orders/${order.id}/status`, { method: 'PATCH', body: { status } })
    const index = orders.value.findIndex(o => o.id === order.id)
    if (index !== -1)
      orders.value[index] = updated
  }
  catch (error: any) {
    updateError.value = extractErrorMessage(error, 'Could not update this order.')
  }
  finally {
    updatingId.value = null
  }
}

watch(statusFilter, load)
onMounted(load)
</script>

<template>
  <div class="d-flex align-center justify-space-between mb-1 flex-wrap ga-3">
    <h1 class="text-h4">
      WhatsApp Orders
    </h1>
    <VSelect
      v-model="statusFilter"
      :items="[{ title: 'All statuses', value: null }, ...STATUSES.map(s => ({ title: s, value: s }))]"
      density="compact"
      variant="outlined"
      style="max-width: 200px;"
    />
  </div>
  <p class="text-medium-emphasis mb-6">
    Orders customers place through your WhatsApp catalog -- move them through confirmed, shipped, and delivered as you fulfil them.
  </p>

  <VAlert v-if="loadError" type="error" variant="tonal" class="mb-4">
    {{ loadError }}
  </VAlert>
  <VAlert v-if="updateError" type="error" variant="tonal" class="mb-4" closable @click:close="updateError = ''">
    {{ updateError }}
  </VAlert>

  <VProgressLinear v-if="loading" indeterminate color="primary" class="mb-4" />

  <VCard v-if="orders.length">
    <VTable>
      <thead>
        <tr>
          <th />
          <th>Customer</th>
          <th>Items</th>
          <th>Total</th>
          <th>Status</th>
          <th>Placed</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <template v-for="order in orders" :key="order.id">
          <tr style="cursor: pointer;" @click="toggleExpand(order.id)">
            <td style="width: 32px;">
              <VIcon :icon="expandedId === order.id ? 'tabler-chevron-down' : 'tabler-chevron-right'" size="18" />
            </td>
            <td>{{ order.contact_name || 'Unknown' }}</td>
            <td>{{ order.items.length }} item{{ order.items.length === 1 ? '' : 's' }}</td>
            <td>
              <span v-if="order.total_amount != null">{{ order.currency }} {{ order.total_amount.toFixed(2) }}</span>
              <span v-else class="text-medium-emphasis">—</span>
            </td>
            <td>
              <VChip :color="statusColor[order.status]" size="small">
                {{ order.status }}
              </VChip>
            </td>
            <td>{{ new Date(order.created_at).toLocaleString('en-IN') }}</td>
            <td @click.stop>
              <VSelect
                :model-value="order.status"
                :items="STATUSES"
                density="compact"
                variant="outlined"
                hide-details
                style="max-width: 150px;"
                :loading="updatingId === order.id"
                @update:model-value="(status: string) => setStatus(order, status)"
              />
            </td>
          </tr>
          <tr v-if="expandedId === order.id">
            <td />
            <td colspan="6" class="pb-4">
              <VTable density="compact">
                <thead>
                  <tr>
                    <th>Product</th>
                    <th>Qty</th>
                    <th>Price</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(item, i) in order.items" :key="i">
                    <td>{{ item.product_name || item.product_retailer_id }}</td>
                    <td>{{ item.quantity }}</td>
                    <td>
                      <span v-if="item.item_price != null">{{ item.currency }} {{ item.item_price.toFixed(2) }}</span>
                      <span v-else class="text-medium-emphasis">—</span>
                    </td>
                  </tr>
                </tbody>
              </VTable>
            </td>
          </tr>
        </template>
      </tbody>
    </VTable>
  </VCard>
  <p v-else-if="!loading" class="text-medium-emphasis text-center pa-8">
    No orders yet.
  </p>
</template>
