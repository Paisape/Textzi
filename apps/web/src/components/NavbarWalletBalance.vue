<script setup lang="ts">
const balance = ref<number | null>(null)
const showDialog = ref(false)

async function loadBalance() {
  try {
    const wallet = await $api<{ available_balance: number }>('/v1/wallet')
    balance.value = wallet.available_balance
  }
  catch {
    balance.value = null
  }
}

onMounted(loadBalance)
</script>

<template>
  <div>
    <div
      v-if="balance !== null"
      class="d-flex align-center gap-1 border rounded px-3 py-1"
    >
      <span class="text-body-2">
        Balance: <span class="font-weight-medium">{{ balance.toLocaleString('en-IN', { maximumFractionDigits: 2 }) }} SMS</span>
      </span>
      <IconBtn
        size="small"
        @click="showDialog = true"
      >
        <VIcon
          icon="tabler-circle-plus"
          size="20"
        />
      </IconBtn>
    </div>

    <AddCreditsDialog
      v-model:is-dialog-visible="showDialog"
      :current-balance="balance ?? 0"
      @recharged="loadBalance"
    />
  </div>
</template>
