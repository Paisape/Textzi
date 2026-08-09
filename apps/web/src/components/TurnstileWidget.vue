<script setup lang="ts">
// Wraps a Cloudflare Turnstile widget for SPA forms that submit via fetch (not a native form
// POST), so implicit auto-render's usual approach (a hidden cf-turnstile-response input injected
// into the surrounding <form>) isn't picked up automatically. data-callback bridges the token back
// into this component's v-model instead. `id` must be unique per page -- it's both the DOM id
// Turnstile's MutationObserver-based auto-render keys off of and the container argument
// window.turnstile.reset(id) needs to reset this specific widget (tokens are single-use; a caller
// must reset before letting the user retry after a failed submit).
const props = defineProps<{ id: string, modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const callbackName = `__turnstileCallback_${props.id.replace(/-/g, '_')}`

// Fetched at runtime rather than hardcoded -- admins can change the sitekey from Platform
// Settings > Turnstile Setting without a frontend rebuild/redeploy. The div below only enters the
// DOM once this is set (v-if), since the callback must already exist on `window` before
// Turnstile's MutationObserver-based auto-render discovers it.
const siteKey = ref('')

onMounted(async () => {
  ;(window as any)[callbackName] = (token?: string) => emit('update:modelValue', token ?? '')
  try {
    const result = await $api<{ site_key: string }>('/v1/public/turnstile-config')
    siteKey.value = result.site_key
  }
  catch {
    // Leave the widget unrendered rather than guess a sitekey. turnstile_token then stays empty,
    // and the backend's own posture (turnstile.py -- fail-open in development, fail-closed
    // otherwise) decides what happens to the submission, same as if Turnstile were never wired up.
  }
})

onBeforeUnmount(() => {
  delete (window as any)[callbackName]
})

function reset() {
  ;(window as any).turnstile?.reset(props.id)
  emit('update:modelValue', '')
}

defineExpose({ reset })
</script>

<template>
  <div
    v-if="siteKey"
    :id="id"
    class="cf-turnstile"
    :data-sitekey="siteKey"
    data-action="turnstile-spin-v2"
    :data-callback="callbackName"
    :data-expired-callback="callbackName"
  />
</template>
