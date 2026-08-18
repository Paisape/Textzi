<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    channel: 'waba',
  },
})

const router = useRouter()

onMounted(() => router.replace({ name: 'inbox' }))
</script>

<template>
  <div class="d-flex align-center justify-center" style="height: 100vh;">
    <VProgressCircular indeterminate color="primary" />
  </div>
</template>
