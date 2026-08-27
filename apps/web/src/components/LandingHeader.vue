<script setup lang="ts">
import logoFull from '@images/logo-full.svg?raw'

const mobileNavOpen = ref(false)
const headerScrolled = ref(false)
const mobileChannelsOpen = ref(false)

const channelLinks = [
  { to: '/products/sms', label: 'SMS', desc: 'DLT-compliant bulk & transactional', icon: 'tabler-messages', color: 'info' },
  { to: '/products/whatsapp', label: 'WhatsApp', desc: 'Business API, catalog & inbox', icon: 'tabler-brand-whatsapp', color: 'success' },
  { to: '/products/crm', label: 'CRM', desc: 'Pipeline, helpdesk & quotes', icon: 'tabler-users-group', color: 'primary' },
]

function onWindowScroll() {
  headerScrolled.value = window.scrollY > 24
}

function closeMobileNav() {
  mobileNavOpen.value = false
}

onMounted(() => {
  onWindowScroll()
  window.addEventListener('scroll', onWindowScroll, { passive: true })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onWindowScroll)
})
</script>

<template>
  <header
    class="landing-header"
    :class="{ 'landing-header-scrolled': headerScrolled }"
  >
    <VContainer class="d-flex align-center justify-space-between py-3">
      <RouterLink
        to="/"
        class="landing-logo-link"
      >
        <div
          class="landing-logo-full"
          v-html="logoFull"
        />
      </RouterLink>

      <nav class="d-none d-md-flex align-center gap-x-8 landing-nav">
        <VMenu open-on-hover>
          <template #activator="{ props: menuProps }">
            <a
              v-bind="menuProps"
              class="landing-nav-trigger"
            >
              Channels
              <VIcon
                icon="tabler-chevron-down"
                size="14"
              />
            </a>
          </template>
          <VList class="channel-menu-list">
            <VListItem
              v-for="channel in channelLinks"
              :key="channel.to"
              :to="channel.to"
              class="channel-menu-item"
            >
              <template #prepend>
                <VAvatar
                  :color="channel.color"
                  variant="tonal"
                  size="36"
                  rounded="lg"
                >
                  <VIcon
                    :icon="channel.icon"
                    size="18"
                  />
                </VAvatar>
              </template>
              <VListItemTitle class="font-weight-medium">
                {{ channel.label }}
              </VListItemTitle>
              <VListItemSubtitle>
                {{ channel.desc }}
              </VListItemSubtitle>
            </VListItem>
          </VList>
        </VMenu>
        <RouterLink to="/products/pricing">
          Pricing
        </RouterLink>
        <RouterLink to="/knowledge-base">
          Resources
        </RouterLink>
        <RouterLink to="/#contact">
          Contact
        </RouterLink>
      </nav>

      <div class="d-none d-md-flex align-center gap-4">
        <RouterLink
          to="/login"
          class="text-medium-emphasis"
        >
          Login
        </RouterLink>
        <VBtn
          color="primary"
          to="/register"
        >
          Get Started
        </VBtn>
      </div>

      <VBtn
        icon
        variant="text"
        class="d-md-none"
        @click="mobileNavOpen = !mobileNavOpen"
      >
        <VIcon icon="tabler-menu-2" />
      </VBtn>
    </VContainer>

    <VExpandTransition>
      <div
        v-if="mobileNavOpen"
        class="d-md-none px-4 pb-4"
      >
        <div class="d-flex flex-column gap-3">
          <button
            type="button"
            class="mobile-nav-toggle"
            @click="mobileChannelsOpen = !mobileChannelsOpen"
          >
            Channels
            <VIcon
              :icon="mobileChannelsOpen ? 'tabler-chevron-up' : 'tabler-chevron-down'"
              size="14"
            />
          </button>
          <VExpandTransition>
            <div
              v-if="mobileChannelsOpen"
              class="d-flex flex-column gap-3 pl-4"
            >
              <RouterLink
                v-for="channel in channelLinks"
                :key="channel.to"
                :to="channel.to"
                @click="closeMobileNav"
              >
                {{ channel.label }}
              </RouterLink>
            </div>
          </VExpandTransition>
          <RouterLink
            to="/products/pricing"
            @click="closeMobileNav"
          >
            Pricing
          </RouterLink>
          <RouterLink
            to="/knowledge-base"
            @click="closeMobileNav"
          >
            Resources
          </RouterLink>
          <RouterLink
            to="/#contact"
            @click="closeMobileNav"
          >
            Contact
          </RouterLink>
          <RouterLink
            to="/login"
            @click="closeMobileNav"
          >
            Login
          </RouterLink>
          <VBtn
            color="primary"
            to="/register"
            block
            @click="closeMobileNav"
          >
            Get Started
          </VBtn>
        </div>
      </div>
    </VExpandTransition>
  </header>
</template>

<style scoped lang="scss">
.landing-header {
  position: sticky;
  top: 0;
  z-index: 10;
  background: rgba(var(--v-theme-surface), 0.85);
  backdrop-filter: blur(10px);
  border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  transition: box-shadow 0.3s ease, border-color 0.3s ease;
}

.landing-header-scrolled {
  border-block-end-color: transparent;
  box-shadow: 0 4px 20px rgba(var(--v-theme-on-surface), 0.08);
}

.landing-logo-link {
  display: flex;
  align-items: center;
  text-decoration: none;
}

.landing-logo-full {
  display: inline-flex;
  line-height: 0;
  color: rgb(var(--v-theme-on-surface));
}

.landing-logo-full :deep(svg) {
  display: block;
  block-size: 30px;
  inline-size: auto;
}

.landing-nav a {
  position: relative;
  color: rgb(var(--v-theme-on-surface));
  text-decoration: none;
  font-weight: 500;
  transition: color 0.2s ease;
}

.landing-nav a::after {
  content: "";
  position: absolute;
  inset-block-end: -4px;
  inset-inline-start: 0;
  inline-size: 0%;
  block-size: 2px;
  background: rgb(var(--v-theme-primary));
  transition: inline-size 0.25s ease;
}

.landing-nav a:hover {
  color: rgb(var(--v-theme-primary));
}

.landing-nav a:hover::after {
  inline-size: 100%;
}

.landing-nav-trigger {
  display: flex;
  align-items: center;
  gap: 4px;
  color: rgb(var(--v-theme-on-surface));
  font-weight: 500;
  cursor: pointer;
  text-decoration: none;
}

.landing-nav-trigger:hover {
  color: rgb(var(--v-theme-primary));
}

.mobile-nav-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: rgb(var(--v-theme-on-surface));
  font-weight: 500;
  background: none;
  border: none;
  padding: 0;
  text-align: start;
}

.channel-menu-list {
  min-inline-size: 260px;
  padding-block: 8px;
}

.channel-menu-item {
  padding-block: 10px;
}
</style>
