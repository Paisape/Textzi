<script setup lang="ts">
// Explicit rendering (turnstile.render()), not implicit (class="cf-turnstile" + data-* attrs).
// Confirmed live and per Cloudflare's own docs: implicit rendering only picks up elements already
// in the DOM when api.js first runs -- it does NOT reliably catch a container added later, which
// is exactly what happens here (the div only exists once the async /v1/public/turnstile-config
// fetch below resolves). Implicit mode silently never rendered anything, leaving every submission
// with an empty token. Explicit mode is Cloudflare's documented fix for SPA-injected containers.
declare global {
  interface Window {
    turnstile?: {
      render: (container: HTMLElement, options: Record<string, unknown>) => string
      reset: (widgetId: string) => void
      remove: (widgetId: string) => void
    }
  }
}

const props = defineProps<{ id: string, modelValue: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const el = ref<HTMLElement>()
let widgetId = ''
let pollInterval: ReturnType<typeof setInterval> | undefined

// Bounded (10s) so a blocked/failed-to-load Cloudflare script (ad-blocker, privacy extension,
// network issue) can't leave a setInterval polling forever -- tracked at component scope, not
// just inside this function's closure, so onBeforeUnmount can always clear it.
function waitForTurnstile(): Promise<boolean> {
  return new Promise(resolve => {
    if (window.turnstile)
      return resolve(true)
    let elapsed = 0
    pollInterval = setInterval(() => {
      if (window.turnstile) {
        clearInterval(pollInterval)
        pollInterval = undefined
        resolve(true)
        return
      }
      elapsed += 50
      if (elapsed >= 10000) {
        clearInterval(pollInterval)
        pollInterval = undefined
        resolve(false)
      }
    }, 50)
  })
}

onMounted(async () => {
  // Fetched at runtime rather than hardcoded -- admins can change the sitekey from Platform
  // Settings > Turnstile Setting without a frontend rebuild/redeploy.
  let siteKey = ''
  try {
    const result = await $api<{ site_key: string }>('/v1/public/turnstile-config')
    siteKey = result.site_key
  }
  catch {
    // No sitekey -- leave the widget unrendered. turnstile_token then stays empty, and the
    // backend's own posture (turnstile.py -- fail-open in development, fail-closed otherwise)
    // decides what happens to the submission, same as if Turnstile were never wired up.
    return
  }
  const ready = await waitForTurnstile()
  if (!ready || !el.value)
    return
  widgetId = window.turnstile!.render(el.value, {
    sitekey: siteKey,
    action: 'turnstile-spin-v2',
    callback: (token: string) => emit('update:modelValue', token),
    'expired-callback': () => emit('update:modelValue', ''),
    'error-callback': () => emit('update:modelValue', ''),
  })
})

onBeforeUnmount(() => {
  if (pollInterval)
    clearInterval(pollInterval)
  if (widgetId)
    window.turnstile?.remove(widgetId)
})

function reset() {
  if (widgetId)
    window.turnstile?.reset(widgetId)
  emit('update:modelValue', '')
}

defineExpose({ reset })
</script>

<template>
  <div :id="id" ref="el" />
</template>
