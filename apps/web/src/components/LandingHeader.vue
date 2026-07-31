<script setup lang="ts">
import logoFull from '@images/logo-full.svg?raw'

const mobileNavOpen = ref(false)
const headerScrolled = ref(false)

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
        <RouterLink to="/#features">
          Features
        </RouterLink>
        <RouterLink to="/#pricing">
          Pricing
        </RouterLink>
        <RouterLink to="/#testimonials">
          Testimonials
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
          <RouterLink
            to="/#features"
            @click="closeMobileNav"
          >
            Features
          </RouterLink>
          <RouterLink
            to="/#pricing"
            @click="closeMobileNav"
          >
            Pricing
          </RouterLink>
          <RouterLink
            to="/#testimonials"
            @click="closeMobileNav"
          >
            Testimonials
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
  background: rgb(var(--v-theme-surface));
  border-block-end: 1px solid rgba(var(--v-border-color), var(--v-border-opacity));
  transition: box-shadow 0.3s ease;
}

.landing-header-scrolled {
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
</style>
