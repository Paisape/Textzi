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

  <VRow class="align-stretch">
    <VCol
      cols="12"
      sm="6"
      lg="4"
      class="d-flex"
    >
      <VCard class="h-100 d-flex flex-column flex-grow-1">
        <VCardText class="flex-grow-1">
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
          <p class="text-body-2 text-medium-emphasis mb-0">
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
      class="d-flex"
    >
      <VCard class="h-100 d-flex flex-column flex-grow-1">
        <VCardText class="flex-grow-1">
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
              color="info"
              size="small"
            >
              Connect
            </VChip>
          </div>
          <p class="text-body-2 text-medium-emphasis mb-0">
            Connect your own WhatsApp Business number through Meta and start messaging customers.
          </p>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex gap-4">
          <RouterLink
            to="/channels-whatsapp"
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
      class="d-flex"
    >
      <VCard class="h-100 d-flex flex-column flex-grow-1">
        <VCardText class="flex-grow-1">
          <div class="d-flex align-center justify-space-between mb-4">
            <div class="d-flex align-center gap-2">
              <VIcon
                icon="tabler-address-book"
                color="primary"
                size="24"
              />
              <span class="text-h6">CRM</span>
            </div>
            <VChip
              color="success"
              size="small"
            >
              Active
            </VChip>
          </div>
          <p class="text-body-2 text-medium-emphasis mb-0">
            Convert WhatsApp conversations into leads and customers, and track them through your
            own sales pipeline.
          </p>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex gap-4">
          <RouterLink
            to="/channels-crm"
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
      class="d-flex"
    >
      <VCard class="h-100 d-flex flex-column flex-grow-1">
        <VCardText class="flex-grow-1">
          <div class="d-flex align-center justify-space-between mb-4">
            <div class="d-flex align-center gap-2">
              <VIcon
                icon="tabler-message-circle"
                color="primary"
                size="24"
              />
              <span class="text-h6">Website Chat</span>
            </div>
            <VChip
              color="info"
              size="small"
            >
              Connect
            </VChip>
          </div>
          <p class="text-body-2 text-medium-emphasis mb-0">
            Embed a live chat widget on your own website — visitor messages land right in this inbox.
          </p>
        </VCardText>
        <VDivider />
        <VCardText class="d-flex gap-4">
          <RouterLink
            to="/channels-webchat"
            class="font-weight-medium"
          >
            Manage
          </RouterLink>
        </VCardText>
      </VCard>
    </VCol>
  </VRow>
</template>
