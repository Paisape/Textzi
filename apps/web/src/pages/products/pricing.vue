<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

type RateCardSlab = { id: string, min_amount: number, max_amount: number | null, price_per_sms: number }
type PublicRateCard = { name: string, channel: string, public_tagline: string | null, min_recharge_amount: number, slabs: RateCardSlab[] }

const publicRateCards = ref<PublicRateCard[]>([])
const rateCardError = ref('')
const smsCard = computed(() => publicRateCards.value.find(c => c.channel === 'sms') || null)
const whatsappCard = computed(() => publicRateCards.value.find(c => c.channel === 'whatsapp') || null)

async function loadRateCards() {
  try {
    publicRateCards.value = await $api<PublicRateCard[]>('/v1/public/rate-cards')
  }
  catch (error: any) {
    rateCardError.value = extractErrorMessage(error, 'Pricing is temporarily unavailable.')
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

    <section class="pricing-hero">
      <VContainer class="text-center">
        <VChip
          color="primary"
          variant="tonal"
          size="small"
          class="mb-3"
        >
          Pricing
        </VChip>
        <h1 class="text-h3 font-weight-bold mb-3">
          Pricing for Every Channel
        </h1>
        <p class="text-medium-emphasis">
          Pay-as-you-go SMS and WhatsApp pricing, no monthly lock-in. CRM is priced per seat. Talk to us for a custom plan.
        </p>
      </VContainer>
    </section>

    <section class="section-py">
      <VContainer>
        <VAlert
          v-if="rateCardError"
          type="error"
          variant="tonal"
          max-width="480"
          class="mx-auto"
        >
          {{ rateCardError }}
        </VAlert>

        <VRow
          v-else
          justify="center"
        >
          <VCol
            cols="12"
            md="3"
          >
            <VCard
              variant="outlined"
              class="pricing-card d-flex flex-column"
              height="100%"
            >
              <VCardText class="d-flex flex-column h-100">
                <div class="d-flex align-center justify-space-between mb-1">
                  <span class="text-h6 font-weight-bold">SMS</span>
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
                <p
                  v-else
                  class="text-body-2 text-medium-emphasis"
                >
                  Reach out and we'll share current SMS rates for your volume.
                </p>

                <VSpacer />
                <VBtn
                  color="primary"
                  block
                  class="mt-6"
                  :to="smsCard ? '/register' : '/#contact'"
                >
                  {{ smsCard ? 'Get Started' : 'Contact Us' }}
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>

          <VCol
            cols="12"
            md="3"
          >
            <VCard
              variant="outlined"
              class="pricing-card d-flex flex-column"
              height="100%"
            >
              <VCardText class="d-flex flex-column h-100">
                <div class="d-flex align-center justify-space-between mb-1">
                  <span class="text-h6 font-weight-bold">WhatsApp</span>
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
                <p
                  v-else
                  class="text-body-2 text-medium-emphasis"
                >
                  Reach out and we'll share current WhatsApp conversation rates for your volume.
                </p>

                <VSpacer />
                <VBtn
                  color="primary"
                  block
                  class="mt-6"
                  :to="whatsappCard ? '/register' : '/#contact'"
                >
                  {{ whatsappCard ? 'Get Started' : 'Contact Us' }}
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>

          <VCol
            cols="12"
            md="3"
          >
            <VCard
              variant="outlined"
              class="pricing-card d-flex flex-column"
              height="100%"
            >
              <VCardText class="d-flex flex-column h-100">
                <div class="d-flex align-center justify-space-between mb-1">
                  <span class="text-h6 font-weight-bold">CRM</span>
                  <VChip
                    color="primary"
                    size="small"
                  >
                    Per seat
                  </VChip>
                </div>
                <p class="text-body-2 text-medium-emphasis mb-4">
                  Pipelines, helpdesk, quotes, and live chat — priced per team seat, monthly or quarterly.
                </p>
                <p class="text-body-2 text-medium-emphasis">
                  Reach out and we'll share current CRM plan pricing for your team size.
                </p>

                <VSpacer />
                <VBtn
                  color="primary"
                  block
                  class="mt-6"
                  to="/#contact"
                >
                  Contact Us
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>

          <VCol
            cols="12"
            md="3"
          >
            <VCard
              variant="outlined"
              class="pricing-card pricing-card-popular d-flex flex-column"
              height="100%"
            >
              <VChip
                color="primary"
                size="small"
                class="pricing-popular-badge"
              >
                Custom
              </VChip>
              <VCardText class="d-flex flex-column h-100">
                <div class="text-h6 font-weight-bold mb-1">
                  Enterprise
                </div>
                <p class="text-body-2 text-medium-emphasis mb-4">
                  High volume, dedicated account manager, custom integrations, or a bespoke blend of channels — let's talk about what you need.
                </p>
                <div class="d-flex align-center gap-2 mb-2">
                  <VIcon
                    icon="tabler-check"
                    color="success"
                    size="18"
                  />
                  <span class="text-body-2">Volume-based custom rates</span>
                </div>
                <div class="d-flex align-center gap-2 mb-2">
                  <VIcon
                    icon="tabler-check"
                    color="success"
                    size="18"
                  />
                  <span class="text-body-2">Dedicated account manager</span>
                </div>
                <div class="d-flex align-center gap-2 mb-2">
                  <VIcon
                    icon="tabler-check"
                    color="success"
                    size="18"
                  />
                  <span class="text-body-2">SLA & custom integrations</span>
                </div>

                <VSpacer />
                <VBtn
                  color="primary"
                  variant="flat"
                  block
                  class="mt-6"
                  to="/#contact"
                >
                  Talk to Sales
                </VBtn>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <LandingFooter />
  </div>
</template>

<style scoped lang="scss">
.landing-page {
  background: rgb(var(--v-theme-background));
}

.pricing-hero {
  padding-block: 4rem 2rem;
  background: linear-gradient(180deg, rgba(var(--v-theme-primary), 0.08) 0%, rgba(var(--v-theme-primary), 0) 100%);
}

.section-py {
  padding-block: 3rem 5rem;
}

.pricing-card {
  position: relative;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.pricing-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 28px rgba(var(--v-theme-on-surface), 0.12);
}

.pricing-card-popular {
  border: 2px solid rgb(var(--v-theme-primary));
  overflow: visible;
}

.pricing-popular-badge {
  position: absolute;
  inset-block-start: -10px;
  inset-inline-start: 50%;
  transform: translate(-50%, -100%);
}
</style>
