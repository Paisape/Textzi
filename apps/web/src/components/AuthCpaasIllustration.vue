<script setup lang="ts">
type ChannelIcon = {
  icon: string
  color: string
  size: number
  top: string
  left: string
  duration: number
  delay: number
}

const channels: ChannelIcon[] = [
  { icon: 'tabler-message-2', color: '#F1600D', size: 64, top: '6%', left: '46%', duration: 6, delay: 0 },
  { icon: 'tabler-brand-whatsapp', color: '#25D366', size: 56, top: '20%', left: '8%', duration: 7, delay: 0.6 },
  { icon: 'tabler-mail', color: '#3B82F6', size: 52, top: '18%', left: '78%', duration: 6.5, delay: 1.1 },
  { icon: 'tabler-phone', color: '#8B5CF6', size: 48, top: '52%', left: '4%', duration: 8, delay: 0.3 },
  { icon: 'tabler-bell', color: '#F59E0B', size: 46, top: '58%', left: '84%', duration: 7.5, delay: 0.9 },
  { icon: 'tabler-api', color: '#0EA5A4', size: 50, top: '80%', left: '20%', duration: 6.8, delay: 1.4 },
  { icon: 'tabler-send-2', color: '#EC4899', size: 44, top: '82%', left: '66%', duration: 7.2, delay: 0.2 },
]
</script>

<template>
  <div class="cpaas-illustration">
    <div class="cpaas-blob cpaas-blob-1" />
    <div class="cpaas-blob cpaas-blob-2" />

    <svg class="cpaas-links" viewBox="0 0 100 100" preserveAspectRatio="none">
      <line
        v-for="(c, i) in channels"
        :key="i"
        x1="50"
        y1="50"
        :x2="c.left"
        :y2="c.top"
        class="cpaas-link-line"
      />
    </svg>

    <div class="cpaas-hub">
      <VIcon icon="tabler-message-circle-2-filled" size="40" color="white" />
    </div>

    <div
      v-for="(c, i) in channels"
      :key="i"
      class="cpaas-node"
      :style="{
        top: c.top,
        left: c.left,
        inlineSize: `${c.size}px`,
        blockSize: `${c.size}px`,
        '--node-color': c.color,
        '--float-duration': `${c.duration}s`,
        '--float-delay': `${c.delay}s`,
      }"
    >
      <VIcon :icon="c.icon" :size="c.size * 0.46" :color="c.color" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.cpaas-illustration {
  position: relative;
  inline-size: 100%;
  max-inline-size: 560px;
  aspect-ratio: 1 / 0.85;
}

.cpaas-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(50px);
  pointer-events: none;
}

.cpaas-blob-1 {
  inline-size: 260px;
  block-size: 260px;
  inset-block-start: 0;
  inset-inline-start: 30%;
  background: rgba(var(--v-theme-primary), 0.14);
  animation: cpaas-blob-drift 16s ease-in-out infinite;
}

.cpaas-blob-2 {
  inline-size: 200px;
  block-size: 200px;
  inset-block-end: 5%;
  inset-inline-start: 10%;
  background: rgba(37, 211, 102, 0.12);
  animation: cpaas-blob-drift 20s ease-in-out infinite reverse;
}

.cpaas-links {
  position: absolute;
  inset: 0;
  inline-size: 100%;
  block-size: 100%;
  overflow: visible;
}

.cpaas-link-line {
  stroke: rgba(var(--v-theme-on-surface), 0.14);
  stroke-width: 0.4;
  stroke-dasharray: 2 2;
}

.cpaas-hub {
  position: absolute;
  inset-block-start: 50%;
  inset-inline-start: 50%;
  inline-size: 92px;
  block-size: 92px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(145deg, rgb(var(--v-theme-primary)), #D84F06);
  box-shadow: 0 12px 32px -8px rgba(var(--v-theme-primary), 0.55);
  transform: translate(-50%, -50%);
  z-index: 2;
  animation: cpaas-hub-pulse 4s ease-in-out infinite;
}

.cpaas-node {
  position: absolute;
  transform: translate(-50%, -50%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgb(var(--v-theme-surface));
  box-shadow: 0 8px 20px -6px rgba(var(--v-theme-on-surface), 0.25), 0 0 0 1px color-mix(in srgb, var(--node-color) 30%, transparent);
  z-index: 1;
  animation: cpaas-float var(--float-duration) ease-in-out infinite;
  animation-delay: var(--float-delay);
}

@keyframes cpaas-float {
  0%, 100% { transform: translate(-50%, -50%) translateY(0); }
  50% { transform: translate(-50%, -50%) translateY(-14px); }
}

@keyframes cpaas-blob-drift {
  0%, 100% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(20px, -16px) scale(1.08); }
}

@keyframes cpaas-hub-pulse {
  0%, 100% { box-shadow: 0 12px 32px -8px rgba(var(--v-theme-primary), 0.55); }
  50% { box-shadow: 0 12px 40px -4px rgba(var(--v-theme-primary), 0.75); }
}

@media (prefers-reduced-motion: reduce) {
  .cpaas-blob, .cpaas-hub, .cpaas-node {
    animation: none;
  }
}
</style>
