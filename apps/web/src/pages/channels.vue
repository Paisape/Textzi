<script setup lang="ts">
definePage({
  meta: {
    layout: 'default',
  },
})
</script>

<template>
  <h1 class="text-h4 mb-1">
    Channels
  </h1>
  <p class="text-medium-emphasis mb-6">
    Manage the messaging channels connected to your account.
  </p>

  <VRow>
    <VCol
      cols="12"
      sm="6"
      lg="4"
    >
      <VCard>
        <VCardText>
          <div class="d-flex align-center justify-space-between mb-4">
            <div class="d-flex align-center gap-2">
              <VIcon
                icon="tabler-message-2"
                color="primary"
                size="24"
              />
              <span class="text-h6">SMS</span>
            </div>
            <VChip
              color="success"
              size="small"
            >
              Active
            </VChip>
          </div>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Send DLT-compliant transactional, OTP, and promotional SMS across India.
          </p>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex gap-4">
          <RouterLink
            to="/channels-sms"
            class="font-weight-medium"
          >
            Manage
          </RouterLink>
          <RouterLink
            to="/pricing"
            class="font-weight-medium"
          >
            Pricing
          </RouterLink>
        </VCardText>
      </VCard>
    </VCol>

    <VCol
      cols="12"
      sm="6"
      lg="4"
    >
      <VCard>
        <VCardText>
          <div class="d-flex align-center justify-space-between mb-4">
            <div class="d-flex align-center gap-2">
              <VIcon
                icon="tabler-brand-whatsapp"
                color="success"
                size="24"
              />
              <span class="text-h6">WhatsApp</span>
            </div>
            <VChip
              color="default"
              size="small"
            >
              Inactive
            </VChip>
          </div>
          <p class="text-body-2 text-medium-emphasis mb-4">
            Unlock the WhatsApp Business Platform to deliver conversational experiences at scale.
          </p>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex gap-4">
          <span class="text-disabled">Try Demo</span>
          <span class="text-disabled">Plan</span>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
