<script setup lang="ts">
defineProps<{
  label: string
  value: string
  subtext?: string
  color?: string
}>()
</script>

<template>
  <VCard>
    <VCardText>
      <p class="text-caption text-medium-emphasis mb-1">
        {{ label }}
      </p>
      <p
        class="text-h5 mb-0"
        :class="color ? `text-${color}` : undefined"
      >
        {{ value }}
      </p>
      <p
        v-if="subtext"
        class="text-caption text-medium-emphasis mb-0 mt-1"
      >
        {{ subtext }}
      </p>
    </VCardText>
  </VCard>
</template>
