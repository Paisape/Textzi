<script setup lang="ts">
import { useHead } from '@unhead/vue'

definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

useHead({
  title: 'WhatsApp Business API - Messaging, Commerce & Support - Textzi',
  meta: [
    { name: 'description', content: 'Connect your official WhatsApp Business number, sell through your product catalog, and support customers -- all from one shared team inbox with templates, automation, and analytics built in.' },
    { property: 'og:title', content: 'WhatsApp Business API - Messaging, Commerce & Support - Textzi' },
    { property: 'og:description', content: 'Templates, catalog & commerce, and a shared team inbox on the official WhatsApp Cloud API.' },
    { property: 'og:url', content: 'https://textzi.in/products/whatsapp' },
  ],
})

const features = [
  { icon: 'tabler-template', title: 'Approved Templates', desc: 'Create and manage WhatsApp Business templates with rich media, buttons, and interactive lists.' },
  { icon: 'tabler-shopping-cart', title: 'Catalog & Commerce', desc: 'Share your product catalog in-chat, receive cart orders, and collect payment — right inside WhatsApp.' },
  { icon: 'tabler-messages', title: 'Shared Team Inbox', desc: 'Assign conversations, add private notes, and reply as a team from one shared WhatsApp inbox.' },
  { icon: 'tabler-bolt', title: 'Automation & Bots', desc: 'Menu-driven conversation flows and keyword-based automation rules — no AI black box, fully predictable.' },
  { icon: 'tabler-report', title: 'Delivery & Read Analytics', desc: 'Track delivery, read rates, and campaign performance in real time.' },
  { icon: 'tabler-plug', title: 'Official Cloud API', desc: 'Direct integration with Meta\'s WhatsApp Business Cloud API via Embedded Signup — no third-party BSP in between.' },
]

type RateCardSlab = { id: string, min_amount: number, max_amount: number | null, price_per_sms: number }
type PublicRateCard = { name: string, channel: string, public_tagline: string | null, min_recharge_amount: number, slabs: RateCardSlab[] }

const publicRateCards = ref<PublicRateCard[]>([])
const whatsappCard = computed(() => publicRateCards.value.find(c => c.channel === 'whatsapp') || null)

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
      eyebrow="WhatsApp Business API"
      title="WhatsApp Messaging, Commerce & Support in One Inbox"
      subtitle="Connect your official WhatsApp Business number, sell through your product catalog, and support customers — all from one shared team inbox with templates, automation, and analytics built in."
      icon="tabler-brand-whatsapp"
      icon-color="success"
    />

    <section class="section-py">
      <VContainer>
        <div class="text-center section-heading">
          <h2 class="text-h3 font-weight-bold mb-3">
            More Than Messaging
          </h2>
          <p class="text-medium-emphasis">
            From first message to closed sale, Textzi covers the full WhatsApp Business workflow.
          </p>
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
                  color="success"
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
        <VRow justify="center">
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
                  <span class="text-h6 font-weight-bold">WhatsApp Pricing</span>
                  <VChip
                    color="success"
                    size="small"
                  >
                    Pay per message
                  </VChip>
                </div>
                <p class="text-body-2 text-medium-emphasis mb-4">
                  {{ whatsappCard?.public_tagline || 'Official WhatsApp Business API messaging with templates & media.' }}
                </p>
                <template v-if="whatsappCard">
                  <p class="text-caption text-medium-emphasis mb-2">
                    Minimum top-up: ₹{{ whatsappCard.min_recharge_amount.toLocaleString('en-IN') }}. GST (18%) applies on top.
                  </p>
                  <VTable density="compact">
                    <thead>
                      <tr>
                        <th>Recharge amount</th>
                        <th>Price/message</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr
                        v-for="slab in whatsappCard.slabs"
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
          Ready to connect your WhatsApp Business number?
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
