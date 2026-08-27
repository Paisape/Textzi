<script setup lang="ts">
import { useHead } from '@unhead/vue'

definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

useHead({
  title: 'DLT-Compliant Bulk & Transactional SMS - Textzi',
  meta: [
    { name: 'description', content: 'Send OTPs, alerts, and campaigns across India with full TRAI/DLT compliance handled for you -- Entity ID, Sender Headers, and template approval, all in one dashboard.' },
    { property: 'og:title', content: 'DLT-Compliant Bulk & Transactional SMS - Textzi' },
    { property: 'og:description', content: 'DLT-compliant bulk & transactional SMS across India, pay-as-you-go.' },
    { property: 'og:url', content: 'https://textzi.in/products/sms' },
  ],
})

const features = [
  { icon: 'tabler-shield-check', title: 'Full DLT Compliance', desc: 'Entity ID, Sender Header, and template registration handled end-to-end — send transactional and promotional SMS without TRAI headaches.' },
  { icon: 'tabler-language', title: '10+ Indian Languages', desc: 'Reach customers in their own language, including Unicode support for regional-script messages.' },
  { icon: 'tabler-report-money', title: 'Pay-As-You-Go Pricing', desc: 'No monthly lock-in — top up your wallet and pay only for what you send, with transparent slab pricing.' },
  { icon: 'tabler-chart-bar', title: 'Delivery Analytics', desc: 'Real-time delivery reports, failure breakdowns, and volume trends so you always know what landed.' },
  { icon: 'tabler-address-book', title: 'Contact Management', desc: 'Import and segment your contact lists for targeted campaigns.' },
  { icon: 'tabler-plug', title: 'Simple REST API', desc: 'Drop-in HTTP API for transactional SMS from your own application, with the same DLT compliance built in.' },
]

const useCases = [
  'OTP & transactional alerts',
  'Order and delivery updates',
  'Promotional campaigns & offers',
  'Payment reminders and receipts',
]

type RateCardSlab = { id: string, min_amount: number, max_amount: number | null, price_per_sms: number }
type PublicRateCard = { name: string, channel: string, public_tagline: string | null, min_recharge_amount: number, slabs: RateCardSlab[] }

const publicRateCards = ref<PublicRateCard[]>([])
const smsCard = computed(() => publicRateCards.value.find(c => c.channel === 'sms') || null)

async function loadRateCards() {
  try {
    publicRateCards.value = await $api<PublicRateCard[]>('/v1/public/rate-cards')
  }
  catch {
    publicRateCards.value = []
  }
}

function slabLabel(slab: RateCardSlab): string {
  return slab.max_amount ? `₹${slab.min_amount.toLocaleString('en-IN')}–₹${slab.max_amount.toLocaleString('en-IN')}` : `₹${slab.min_amount.toLocaleString('en-IN')}+`
}

onMounted(() => {
  loadRateCards()
})
</script>

<template>
  <div class="landing-page">
    <LandingHeader />

    <LandingChannelHero
      eyebrow="SMS"
      title="DLT-Compliant Bulk & Transactional SMS"
      subtitle="Send OTPs, alerts, and campaigns across India with full TRAI/DLT compliance handled for you — Entity ID, Sender Headers, and template approval, all in one dashboard."
      icon="tabler-messages"
      icon-color="info"
    />

    <section class="section-py">
      <VContainer>
        <div class="text-center section-heading">
          <h2 class="text-h3 font-weight-bold mb-3">
            Everything You Need for SMS in India
          </h2>
        </div>
        <VRow>
          <VCol
            v-for="feature in features"
            :key="feature.title"
            cols="12"
            sm="6"
            md="4"
          >
            <VCard
              variant="outlined"
              height="100%"
            >
              <VCardText>
                <VAvatar
                  color="info"
                  variant="tonal"
                  size="48"
                  rounded="lg"
                  class="mb-4"
                >
                  <VIcon :icon="feature.icon" />
                </VAvatar>
                <h3 class="text-h6 font-weight-bold mb-2">
                  {{ feature.title }}
                </h3>
                <p class="text-medium-emphasis mb-0">
                  {{ feature.desc }}
                </p>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section class="section-py bg-surface">
      <VContainer>
        <VRow align="center">
          <VCol
            cols="12"
            md="6"
          >
            <h2 class="text-h3 font-weight-bold mb-4">
              Built for Every Use Case
            </h2>
            <div
              v-for="point in useCases"
              :key="point"
              class="d-flex align-center gap-3 mb-3"
            >
              <VIcon
                icon="tabler-circle-check-filled"
                color="info"
              />
              <span>{{ point }}</span>
            </div>
          </VCol>
          <VCol
            cols="12"
            md="6"
          >
            <VCard
              variant="outlined"
              class="pricing-card"
            >
              <VCardText>
                <div class="d-flex align-center justify-space-between mb-1">
                  <span class="text-h6 font-weight-bold">SMS Pricing</span>
                  <VChip
                    color="info"
                    size="small"
                  >
                    Pay per SMS
                  </VChip>
                </div>
                <p class="text-body-2 text-medium-emphasis mb-4">
                  {{ smsCard?.public_tagline || 'DLT-compliant bulk & transactional SMS across India.' }}
                </p>
                <template v-if="smsCard">
                  <p class="text-caption text-medium-emphasis mb-2">
                    Minimum top-up: ₹{{ smsCard.min_recharge_amount.toLocaleString('en-IN') }}. GST (18%) applies on top.
                  </p>
                  <VTable density="compact">
                    <thead>
                      <tr>
                        <th>Recharge amount</th>
                        <th>Price/SMS</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="slab in smsCard.slabs"
                        :key="slab.id"
                      >
                        <td>{{ slabLabel(slab) }}</td>
                        <td>₹{{ slab.price_per_sms.toFixed(2) }}</td>
                      </tr>
                    </tbody>
                  </VTable>
                </template>
                <VBtn
                  color="primary"
                  block
                  class="mt-6"
                  to="/register"
                >
                  Get Started
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section class="cta-band">
      <VContainer class="text-center">
        <h2 class="text-h3 font-weight-bold mb-4">
          Ready to send your first SMS campaign?
        </h2>
        <div class="d-flex flex-wrap justify-center gap-4">
          <VBtn
            size="large"
            color="white"
            variant="flat"
            to="/register"
          >
            Start Now
          </VBtn>
          <VBtn
            size="large"
            variant="outlined"
            color="white"
            to="/#contact"
          >
            Talk to Sales
          </VBtn>
        </div>
      </VContainer>
    </section>

    <LandingFooter />
  </div>
</template>

<style scoped lang="scss">
.landing-page {
  background: rgb(var(--v-theme-background));
}

.section-py {
  padding-block: 5rem;
}

.section-heading {
  max-inline-size: 640px;
  margin-inline: auto;
  margin-block-end: 3rem;
}

.pricing-card {
  max-inline-size: 480px;
  margin-inline: auto;
}

.cta-band {
  padding-block: 5rem;
  background: rgb(var(--v-theme-primary));
  color: white;
  text-align: center;
}
</style>
