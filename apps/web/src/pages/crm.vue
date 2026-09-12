<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    channel: 'crm',
  },
})

const router = useRouter()

onMounted(() => router.replace({ name: 'crm-home' }))
</script>

<template>
  <div class="d-flex align-center justify-center" style="height: 100vh;">
    <VProgressCircular indeterminate color="primary" />
  </div>
</template>
