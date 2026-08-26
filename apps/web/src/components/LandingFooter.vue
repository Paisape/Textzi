<script setup lang="ts">
import logoFull from '@images/logo-full.svg?raw'

type CompanyInfo = { company_name: string, company_address: string, company_phone: string, support_email: string }

const companyInfo = ref<CompanyInfo | null>(null)

async function loadCompanyInfo() {
  try {
    companyInfo.value = await $api<CompanyInfo>('/v1/public/company-info')
  }
  catch {
    companyInfo.value = null
  }
}

onMounted(loadCompanyInfo)
</script>

<template>
  <footer class="landing-footer">
    <VContainer>
      <VRow>
        <VCol
          cols="12"
          md="4"
        >
          <div class="landing-logo-full landing-logo-full-footer mb-3">
            <div v-html="logoFull" />
          </div>
          <p class="text-medium-emphasis">
            WhatsApp, SMS &amp; CRM for Indian businesses.
          </p>
        </VCol>
        <VCol
          cols="6"
          md="2"
        >
          <div class="footer-heading">
            Product
          </div>
          <RouterLink
            to="/products/whatsapp"
            class="footer-link d-block"
          >
            WhatsApp API
          </RouterLink>
          <RouterLink
            to="/products/sms"
            class="footer-link d-block"
          >
            SMS Gateway
          </RouterLink>
          <RouterLink
            to="/products/crm"
            class="footer-link d-block"
          >
            CRM
          </RouterLink>
          <RouterLink
            to="/products/pricing"
            class="footer-link d-block"
          >
            Pricing
          </RouterLink>
        </VCol>
        <VCol
          cols="6"
          md="3"
        >
          <div class="footer-heading">
            Company
          </div>
          <RouterLink
            to="/about"
            class="footer-link d-block"
          >
            About Us
          </RouterLink>
          <RouterLink
            to="/#contact"
            class="footer-link d-block"
          >
            Contact
          </RouterLink>
          <RouterLink
            to="/knowledge-base"
            class="footer-link d-block"
          >
            Knowledge Base
          </RouterLink>
          <RouterLink
            to="/privacy-policy"
            class="footer-link d-block"
          >
            Privacy Policy
          </RouterLink>
          <RouterLink
            to="/terms-of-service"
            class="footer-link d-block"
          >
            Terms of Service
          </RouterLink>
          <RouterLink
            to="/refund-policy"
            class="footer-link d-block"
          >
            Refund Policy
          </RouterLink>
        </VCol>
        <VCol
          cols="12"
          md="3"
        >
          <div class="footer-heading">
            Contact
          </div>
          <a
            :href="`mailto:${companyInfo?.support_email ?? 'support@textzi.in'}`"
            class="footer-link d-block"
          >
            {{ companyInfo?.support_email ?? 'support@textzi.in' }}
          </a>
          <a
            v-if="companyInfo?.company_phone"
            :href="`tel:${companyInfo.company_phone}`"
            class="footer-link d-block"
          >
            {{ companyInfo.company_phone }}
          </a>
          <div
            v-if="companyInfo?.company_address"
            class="footer-link footer-address"
          >
            {{ companyInfo.company_address }}
          </div>
        </VCol>
      </VRow>
      <VDivider class="my-6 border-opacity-25" />
      <div class="text-center text-caption footer-copyright">
        © 2026 {{ companyInfo?.company_name ?? 'Textzi' }}. All rights reserved.
      </div>
    </VContainer>
  </footer>
</template>

<style scoped lang="scss">
.landing-footer {
  padding-block: 4rem 2rem;
  background: rgb(var(--v-theme-on-surface));
  color: rgba(var(--v-theme-surface), 0.85);
}

.landing-logo-full {
  display: inline-flex;
  line-height: 0;
}

.landing-logo-full :deep(svg) {
  display: block;
  block-size: 30px;
  inline-size: auto;
}

.landing-logo-full-footer {
  color: rgb(var(--v-theme-surface));
}

.footer-heading {
  font-weight: 700;
  margin-block-end: 1rem;
  color: rgb(var(--v-theme-surface));
}

.footer-link {
  color: rgba(var(--v-theme-surface), 0.7);
  margin-block-end: 0.6rem;
  text-decoration: none;

  &:hover {
    color: rgb(var(--v-theme-surface));
    text-decoration: underline;
  }
}

.footer-address {
  font-size: 0.8125rem;
  line-height: 1.4;
}

.footer-copyright {
  color: rgba(var(--v-theme-surface), 0.6);
}
</style>
