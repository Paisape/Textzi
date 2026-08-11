<script setup lang="ts">
import InboxPage from './inbox.vue'

definePage({
  meta: {
    layout: 'default',
    layoutWrapperClasses: 'layout-content-width-fluid',
  },
})
</script>

<template>
  <InboxPage tickets-mode />
</template>
