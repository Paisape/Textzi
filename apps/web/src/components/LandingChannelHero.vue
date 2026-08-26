<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow: string
  title: string
  subtitle: string
  icon: string
  iconColor?: string
}>(), {
  iconColor: 'primary',
})
</script>

<template>
  <section class="channel-hero-section">
    <div class="channel-hero-blob" />
    <VContainer>
      <VRow align="center">
        <VCol
          cols="12"
          md="7"
        >
          <VChip
            :color="iconColor"
            variant="tonal"
            class="mb-4"
            size="small"
          >
            {{ eyebrow }}
          </VChip>
          <h1 class="channel-hero-title mb-4">
            {{ title }}
          </h1>
          <p class="channel-hero-subtitle mb-6">
            {{ subtitle }}
          </p>
          <div class="d-flex flex-wrap gap-4">
            <VBtn
              size="large"
              color="primary"
              to="/register"
              append-icon="tabler-arrow-right"
            >
              Start Now
            </VBtn>
            <VBtn
              size="large"
              variant="outlined"
              to="/pricing"
            >
              View Pricing
            </VBtn>
          </div>
        </VCol>
        <VCol
          cols="12"
          md="5"
          class="text-center"
        >
          <VAvatar
            :color="iconColor"
            variant="tonal"
            size="140"
            class="channel-hero-icon"
          >
            <VIcon
              :icon="icon"
              size="72"
            />
          </VAvatar>
        </VCol>
      </VRow>
    </VContainer>
  </section>
</template>

<style scoped lang="scss">
.channel-hero-section {
  position: relative;
  overflow: hidden;
  padding-block: 5rem 4rem;
  background: linear-gradient(180deg, rgba(var(--v-theme-primary), 0.08) 0%, rgba(var(--v-theme-primary), 0) 100%);
}

.channel-hero-blob {
  position: absolute;
  inline-size: 380px;
  block-size: 380px;
  inset-inline-end: -120px;
  inset-block-start: -80px;
  border-radius: 50%;
  filter: blur(60px);
  background: rgba(var(--v-theme-primary), 0.18);
  pointer-events: none;
}

.channel-hero-section > .v-container {
  position: relative;
  z-index: 1;
}

.channel-hero-title {
  font-size: 2.75rem;
  font-weight: 800;
  line-height: 1.15;
}

.channel-hero-subtitle {
  font-size: 1.125rem;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  max-inline-size: 34rem;
}

.channel-hero-icon {
  box-shadow: 0 20px 50px rgba(var(--v-theme-primary), 0.2);
}
</style>
