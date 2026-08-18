<script lang="ts" setup>
import { adminNav, channelFocusedNav, customerNav, financeNav, salesNav, supportNav } from '@/navigation/horizontal'
import { useAuthStore } from '@/stores/auth'

import { themeConfig } from '@themeConfig'

// Components
import Footer from '@/layouts/components/Footer.vue'
import GlobalSearch from '@/layouts/components/GlobalSearch.vue'
import NavBarNotifications from '@/layouts/components/NavBarNotifications.vue'
import NavbarThemeSwitcher from '@/layouts/components/NavbarThemeSwitcher.vue'
import UserProfile from '@/layouts/components/UserProfile.vue'
import NavBarI18n from '@core/components/I18n.vue'
import { HorizontalNavLayout } from '@layouts'
import { VNodeRenderer } from '@layouts/components/VNodeRenderer'

const authStore = useAuthStore()
const route = useRoute()

onMounted(() => authStore.load())

const STAFF_AREA_NAV = { finance: financeNav, sales: salesNav, support: supportNav } as const
const navItems = computed(() => {
  if (authStore.isAdmin)
    return adminNav
  if (authStore.staffArea)
    return STAFF_AREA_NAV[authStore.staffArea]
  if (route.meta.channel)
    return channelFocusedNav(route.meta.channel, !authStore.channelScope, authStore.pageScope)
  return customerNav({ wabaActive: authStore.wabaActive, crmActive: authStore.crmActive }, { minimal: route.name === 'dashboard' })
})
</script>

<template>
  <HorizontalNavLayout :nav-items="navItems">
    <!-- 👉 navbar -->
    <template #navbar>
      <RouterLink
        to="/"
        class="app-logo d-flex align-center gap-x-3"
      >
        <VNodeRenderer :nodes="themeConfig.app.logo" />

        <h1 class="app-title font-weight-bold leading-normal text-xl text-capitalize">
          {{ themeConfig.app.title }}
        </h1>
      </RouterLink>
      <GlobalSearch v-if="route.meta.channel === 'crm' || route.name === 'dashboard'" class="me-4" />

      <VSpacer />

      <NavBarI18n
        v-if="themeConfig.app.i18n.enable && themeConfig.app.i18n.langConfig?.length"
        :languages="themeConfig.app.i18n.langConfig"
      />

      <NavbarThemeSwitcher class="me-2" />
      <NavbarWalletBalance class="me-4" />
      <NavBarNotifications class="me-2" />
      <UserProfile />
    </template>

    <!-- 👉 Pages -->
    <slot />

    <!-- 👉 Footer -->
    <template #footer>
      <Footer />
    </template>

    <!-- 👉 Customizer -->
    <!-- <TheCustomizer /> -->
  </HorizontalNavLayout>
</template>
