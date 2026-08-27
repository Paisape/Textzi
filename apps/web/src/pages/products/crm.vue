<script setup lang="ts">
import { useHead } from '@unhead/vue'

definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

useHead({
  title: 'CRM for Indian SMEs - Pipeline, Helpdesk & Quotes - Textzi',
  meta: [
    { name: 'description', content: 'Pipeline, helpdesk, quotes, and live chat -- in one place, connected to the WhatsApp conversations you\'re already having. A complete CRM built for Indian SMEs.' },
    { property: 'og:title', content: 'CRM for Indian SMEs - Pipeline, Helpdesk & Quotes - Textzi' },
    { property: 'og:description', content: 'Pipelines, helpdesk, GST quotes, and live chat -- connected to your WhatsApp conversations.' },
    { property: 'og:url', content: 'https://textzi.in/products/crm' },
  ],
})

const features = [
  { icon: 'tabler-chart-funnel', title: 'Sales Pipeline', desc: 'Track leads and deals through a real pipeline — value, probability, expected close date, and forecasting built in.' },
  { icon: 'tabler-headset', title: 'Helpdesk & Tickets', desc: 'Turn any conversation into a ticket with priority, SLA timers, group routing, and canned responses.' },
  { icon: 'tabler-file-invoice', title: 'GST-Compliant Quotes', desc: 'Generate quotes with correct CGST/SGST/IGST splits and send them for e-signature — right from a deal.' },
  { icon: 'tabler-message-circle', title: 'Website Live Chat', desc: 'Embed a live chat widget on your own website, with full visitor telemetry and the same inbox your team already uses.' },
  { icon: 'tabler-calendar-event', title: 'Tasks & Meetings', desc: 'Log calls, schedule meetings, and share a public booking link so leads can pick their own slot.' },
  { icon: 'tabler-building', title: 'Companies & Contacts', desc: 'Organise contacts under companies, track every touchpoint, and see deal history in one place.' },
]

const useCases = [
  'Convert WhatsApp chats into tracked leads',
  'Run a real sales pipeline with forecasting',
  'GST-ready quotes without spreadsheets',
  'One inbox for tickets, chat, and email',
]
</script>

<template>
  <div class="landing-page">
    <LandingHeader />

    <LandingChannelHero
      eyebrow="CRM"
      title="A Complete CRM Built for Indian SMEs"
      subtitle="Pipeline, helpdesk, quotes, and live chat — in one place, connected to the WhatsApp conversations you're already having. Not a bolted-on contact list."
      icon="tabler-users-group"
      icon-color="primary"
    />

    <section class="section-py">
      <VContainer>
        <div class="text-center section-heading">
          <h2 class="text-h3 font-weight-bold mb-3">
            From First Contact to Closed Deal
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
                  color="primary"
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
              Why Textzi CRM Is Different
            </h2>
            <p class="text-medium-emphasis mb-5">
              Every other CRM treats WhatsApp as a bolt-on integration. Textzi's CRM is built on the
              same messaging platform your team already uses — so a lead created from a chat carries
              its full conversation history, not just a name and number.
            </p>
            <div
              v-for="point in useCases"
              :key="point"
              class="d-flex align-center gap-3 mb-3"
            >
              <VIcon
                icon="tabler-circle-check-filled"
                color="primary"
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
              class="pa-4"
            >
              <VCardText>
                <div class="text-h6 font-weight-bold mb-1">
                  CRM Plan
                </div>
                <p class="text-body-2 text-medium-emphasis mb-4">
                  Simple monthly or quarterly pricing, based on team seats — talk to us for current rates.
                </p>
                <VBtn
                  color="primary"
                  block
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
          Ready to run your pipeline from Textzi?
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

.cta-band {
  padding-block: 5rem;
  background: rgb(var(--v-theme-primary));
  color: white;
  text-align: center;
}
</style>
