<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})
</script>

<template>
  <div class="legal-page">
    <LandingHeader />

    <VContainer class="py-12">
      <VRow justify="center">
        <VCol
          cols="12"
          md="8"
        >
          <h1 class="text-h3 font-weight-bold mb-6">
            About Textzi
          </h1>

          <p class="text-body-1 mb-4">
            <strong>Textzi</strong> is a business messaging platform built for Indian businesses
            that need to reach customers reliably on WhatsApp and SMS. Sending messages at scale
            in India means navigating TRAI's DLT registration requirements, template approvals,
            and carrier routing — we handle that operational complexity so you can focus on your
            campaigns and customer conversations instead.
          </p>

          <p class="text-body-1 mb-4">
            Textzi is a brand owned and managed by <strong>Paisape Techfin Private Limited</strong>.
          </p>

          <p class="text-body-1 mb-4">
            Our platform gives you a single dashboard for WhatsApp Business API messaging,
            DLT-compliant bulk SMS, contact management, and transparent pay-as-you-go pricing —
            with no monthly plan lock-in and no hidden fees.
          </p>

          <p class="text-body-1 mb-4">
            We're a small, India-based team, and we handle support directly rather than through
            layers of ticketing. If you have questions about the product, pricing, or DLT
            compliance, reach out any time.
          </p>

          <VBtn
            color="primary"
            to="/#contact"
            class="mt-4"
          >
            Contact Us
          </VBtn>
        </VCol>
      </VRow>
    </VContainer>

    <LandingFooter />
  </div>
</template>

<style scoped lang="scss">
.legal-page {
  min-block-size: 100vh;
  background: rgb(var(--v-theme-background));
}
</style>
