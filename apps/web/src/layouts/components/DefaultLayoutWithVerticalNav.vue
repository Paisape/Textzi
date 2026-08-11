<script lang="ts" setup>
import { adminNav, customerNav, financeNav, salesNav, supportNav } from '@/navigation/vertical'
import { useAuthStore } from '@/stores/auth'
import { themeConfig } from '@themeConfig'

// Components
import Footer from '@/layouts/components/Footer.vue'
import NavbarThemeSwitcher from '@/layouts/components/NavbarThemeSwitcher.vue'
import UserProfile from '@/layouts/components/UserProfile.vue'
import NavBarI18n from '@core/components/I18n.vue'

// @layouts plugin
import { VerticalNavLayout } from '@layouts'

const authStore = useAuthStore()

onMounted(() => authStore.load())

// Admin, each scoped staff area, and customer all get entirely separate menus -- platform admins
// see zero tenant-facing items, tenants see zero platform-facing items, and a scoped staff role
// (finance_team/sales_team/support_team) sees only its own slice of the admin panel. Defaults to
// customerNav until the profile is confirmed loaded, so nobody sees a flash of the wrong menu.
const STAFF_AREA_NAV = { finance: financeNav, sales: salesNav, support: supportNav } as const
const navItems = computed(() => {
  if (authStore.isAdmin)
    return adminNav
  if (authStore.staffArea)
    return STAFF_AREA_NAV[authStore.staffArea]
  return customerNav({ wabaActive: authStore.wabaActive, crmActive: authStore.crmActive })
})
</script>

<template>
  <VerticalNavLayout :nav-items="navItems">
    <!-- 👉 navbar -->
    <template #navbar="{ toggleVerticalOverlayNavActive }">
      <div class="d-flex h-100 align-center">
        <IconBtn
          id="vertical-nav-toggle-btn"
          class="ms-n3 d-lg-none"
          @click="toggleVerticalOverlayNavActive(true)"
        >
          <VIcon
            size="26"
            icon="tabler-menu-2"
          />
        </IconBtn>

        <NavbarThemeSwitcher />

        <VSpacer />

        <NavBarI18n
          v-if="themeConfig.app.i18n.enable && themeConfig.app.i18n.langConfig?.length"
          :languages="themeConfig.app.i18n.langConfig"
        />
        <NavbarWalletBalance class="me-4" />
        <UserProfile />
      </div>
    </template>

    <!-- 👉 Pages -->
    <slot />

    <!-- 👉 Footer -->
    <template #footer>
      <Footer />
    </template>

    <!-- 👉 Customizer -->
    <!-- <TheCustomizer /> -->
  </VerticalNavLayout>
</template>
