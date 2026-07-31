<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})

const activeTab = ref('sms')
const channelActive = ref<boolean | null>(null)

async function loadChannelStatus() {
  try {
    const status = await $api<{ channel_active: boolean }>('/v1/channels/sms/status')
    channelActive.value = status.channel_active
  }
  catch {
    channelActive.value = null
  }
}

onMounted(loadChannelStatus)
</script>

<template>
  <h1 class="text-h4 mb-1">
    Wallet & Billing
  </h1>
  <p class="text-medium-emphasis mb-6">
    Track your balance, add funds, and review every credit and debit on your account — SMS and WhatsApp are billed from separate wallets.
  </p>

  <VTabs v-model="activeTab" class="mb-6">
    <VTab value="sms">
      SMS Wallet
    </VTab>
    <VTab value="waba">
      WhatsApp Wallet
    </VTab>
  </VTabs>

  <VWindow v-model="activeTab">
    <VWindowItem value="sms">
      <WalletPanel
        title="SMS Wallet"
        balance-endpoint="/v1/wallet"
        recharge-endpoint="/v1/wallet/recharge"
        :credits-based="true"
        :channel-active="channelActive"
      />
    </VWindowItem>
    <VWindowItem value="waba">
      <WalletPanel
        title="WhatsApp Wallet"
        balance-endpoint="/v1/wallet/waba"
        recharge-endpoint="/v1/wallet/waba/recharge"
      />
    </VWindowItem>
  </VWindow>
</template>
