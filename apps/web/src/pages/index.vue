<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})

const features = [
  { icon: 'tabler-brand-whatsapp', title: 'WhatsApp Business API', desc: 'Connect with customers on official WhatsApp Business API. Send templates, media and interactive messages.' },
  { icon: 'tabler-messages', title: 'Bulk SMS (DLT Compliant)', desc: 'Send promotional and transactional SMS across India with full DLT compliance. Entity ID and template registration handled for you.' },
  { icon: 'tabler-address-book', title: 'Contact Management', desc: 'Import, segment and manage your contacts effortlessly. Build targeted audience groups for personalised campaigns.' },
  { icon: 'tabler-chart-line', title: 'Advanced Analytics', desc: 'Track delivery rates, read receipts, click-through rates and campaign performance with real-time dashboards.' },
  { icon: 'tabler-bolt', title: 'Automation Builder', desc: 'Create powerful automated workflows with our visual drag-and-drop builder. No coding required.' },
  { icon: 'tabler-shield-check', title: 'Enterprise Security', desc: 'Bank-grade encryption, role-based access and complete data isolation for multi-tenant deployments.' },
]

const steps = [
  { number: '01', title: 'Create Your Account', desc: 'Sign up and connect your WhatsApp Business number. Complete DLT registration for SMS.' },
  { number: '02', title: 'Import Contacts & Templates', desc: 'Upload your contact list and create message templates. Get templates approved instantly.' },
  { number: '03', title: 'Launch Campaigns', desc: 'Send broadcasts, set up automations, and watch your engagement metrics soar.' },
]

const trustPoints = [
  'Full DLT compliance with TRAI regulations',
  'Support for 10+ Indian languages',
  'Local payment options including UPI',
  'India-based support team',
]

const trustStats = [
  { icon: 'tabler-map-2', label: 'Pan-India Coverage' },
  { icon: 'tabler-bolt', label: '99.9% Uptime' },
  { icon: 'tabler-lock', label: 'GDPR Compliant' },
  { icon: 'tabler-users', label: 'Built for Scale' },
]

const kpis = [
  { value: '10M+', label: 'Messages Sent Daily' },
  { value: '5,000+', label: 'Active Businesses' },
  { value: '99.9%', label: 'Uptime SLA' },
  { value: '24/7', label: 'Support Available' },
]

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

type PublicTestimonial = { author_name: string, author_role: string, quote: string }

const testimonials = ref<PublicTestimonial[]>([])

async function loadTestimonials() {
  try {
    testimonials.value = await $api<PublicTestimonial[]>('/v1/public/testimonials')
  }
  catch {
    testimonials.value = []
  }
}

const supportChannels = [
  { icon: 'tabler-message-circle-2', label: 'Live Chat', to: '/#contact' },
  { icon: 'tabler-phone', label: 'Phone Support', to: '/#contact' },
  { icon: 'tabler-mail', label: 'Email Support', to: '/#contact' },
  { icon: 'tabler-book-2', label: 'Knowledge Base', to: '/knowledge-base' },
]

const contactForm = reactive({ name: '', email: '', phone: '', company: '', message: '' })
const contactSubmitting = ref(false)
const contactSuccess = ref('')
const contactError = ref('')
const contactTurnstileToken = ref('')
const contactTurnstileRef = ref<InstanceType<typeof TurnstileWidget>>()

async function onSubmitContact() {
  contactSubmitting.value = true
  contactSuccess.value = ''
  contactError.value = ''
  try {
    const data = await $api<{ message: string }>('/v1/public/contact', {
      method: 'POST',
      body: {
        name: contactForm.name,
        email: contactForm.email,
        phone: contactForm.phone || undefined,
        company: contactForm.company || undefined,
        message: contactForm.message,
        turnstile_token: contactTurnstileToken.value,
      },
    })
    contactSuccess.value = data.message
    contactForm.name = ''
    contactForm.email = ''
    contactForm.phone = ''
    contactForm.company = ''
    contactForm.message = ''
    // The token was just redeemed (single-use) -- clear it so a future resubmission (if the form
    // ever gains a "send another message" affordance) can't reuse it. The widget itself is
    // unmounted along with the rest of the form (v-if="!contactSuccess"), which already cleans up
    // the Cloudflare-side instance via TurnstileWidget's own onBeforeUnmount.
    contactTurnstileToken.value = ''
  }
  catch (error: any) {
    contactError.value = extractErrorMessage(error, 'Could not send your message. Please try again.')
    // Turnstile tokens are single-use -- the page doesn't navigate away on a failed submit, so
    // without resetting, a retry would resubmit the same already-redeemed token and get rejected
    // by Cloudflare's edge as timeout-or-duplicate instead of getting a fresh one.
    contactTurnstileRef.value?.reset()
  }
  finally {
    contactSubmitting.value = false
  }
}

function scrollToContact() {
  document.getElementById('contact')?.scrollIntoView({ behavior: 'smooth' })
}

function scrollToFeatures() {
  document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' })
}

// Reveal-on-scroll: fades/slides an element in the first time it enters the viewport.
// `v-reveal="index"` staggers a group by index; plain `v-reveal` fires immediately on entry.
const prefersReducedMotion = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const vReveal = {
  mounted(el: HTMLElement, binding: { value?: number }) {
    if (prefersReducedMotion)
      return
    el.classList.add('reveal-init')
    const delay = (binding.value || 0) * 90
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        setTimeout(() => el.classList.add('reveal-active'), delay)
        observer.unobserve(el)
      }
    }, { threshold: 0.15 })
    observer.observe(el)
  },
}

// KPI band counts up from 0 the first time it's scrolled into view.
const kpiSectionEl = ref<HTMLElement | null>(null)
const kpiDisplays = ref(kpis.map(k => prefersReducedMotion ? k.value : '0'))

function animateKpis() {
  if (prefersReducedMotion)
    return
  const duration = 1400
  const start = performance.now()
  const parsed = kpis.map((kpi) => {
    const match = kpi.value.match(/^([\d,]+\.?\d*)(.*)$/)
    if (!match)
      return null
    const numStr = match[1].replace(/,/g, '')
    return { target: Number.parseFloat(numStr), suffix: match[2], decimals: (numStr.split('.')[1] || '').length, hasComma: match[1].includes(',') }
  })

  function tick(now: number) {
    const progress = Math.min((now - start) / duration, 1)
    const eased = 1 - (1 - progress) ** 3
    kpiDisplays.value = kpis.map((kpi, i) => {
      const p = parsed[i]
      if (!p)
        return kpi.value
      const current = p.target * eased
      let formatted = p.decimals ? current.toFixed(p.decimals) : Math.round(current).toString()
      if (p.hasComma)
        formatted = Number(formatted).toLocaleString('en-IN')
      return progress >= 1 ? kpi.value : formatted + p.suffix
    })
    if (progress < 1)
      requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}

// Textzi's own webchat widget, embedded on its own landing page -- eating its own dog food the
// same way Addendum 5's own reasoning already established for the WhatsApp/CRM App Review videos
// ("Textzi acting as its own first customer"). The widget key isn't a secret (same reasoning as
// every other widget embed) so it's fine hardcoded here rather than fetched from an endpoint.
// Injected/removed on mount/unmount rather than living in index.html, since that file is shared
// by the whole SPA -- this way the bubble only ever appears on the actual marketing page, never
// on a logged-in dashboard screen.
const TEXTZI_WEBCHAT_WIDGET_KEY = '35e05759-ac22-4102-acad-3bf4c3eb0c71'
let webchatScriptEl: HTMLScriptElement | null = null

onMounted(() => {
  loadRateCards()
  loadTestimonials()

  if (kpiSectionEl.value && !prefersReducedMotion) {
    const kpiObserver = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        animateKpis()
        kpiObserver.unobserve(entry.target)
      }
    }, { threshold: 0.4 })
    kpiObserver.observe(kpiSectionEl.value)
  }

  const apiBase = import.meta.env.VITE_API_BASE_URL || '/api'
  const widgetScriptOrigin = apiBase.startsWith('http') ? apiBase : window.location.origin
  webchatScriptEl = document.createElement('script')
  webchatScriptEl.src = `${widgetScriptOrigin}/v1/public/webchat/widget.js`
  webchatScriptEl.setAttribute('data-widget-key', TEXTZI_WEBCHAT_WIDGET_KEY)
  webchatScriptEl.async = true
  document.body.appendChild(webchatScriptEl)
})

onUnmounted(() => {
  webchatScriptEl?.remove()
})
</script>

<template>
  <div class="landing-page">
    <LandingHeader />

    <section class="hero-section">
      <div class="hero-blob hero-blob-1" />
      <div class="hero-blob hero-blob-2" />
      <VContainer>
        <VRow align="center">
          <VCol
            cols="12"
            md="6"
          >
            <VChip
              color="primary"
              variant="tonal"
              class="mb-4 hero-anim hero-anim-1"
              size="small"
            >
              Built for Indian businesses
            </VChip>
            <h1 class="hero-title mb-4 hero-anim hero-anim-2">
              Connect with Your Customers on <span class="text-primary">WhatsApp &amp; SMS</span>
            </h1>
            <p class="hero-subtitle mb-6 hero-anim hero-anim-3">
              India's business messaging platform. Send campaigns, automate conversations, and grow your business with the WhatsApp Business API and DLT-compliant SMS &mdash; from one dashboard, one API.
            </p>
            <div class="d-flex flex-wrap gap-4 mb-4 hero-anim hero-anim-4">
              <VBtn
                size="large"
                color="primary"
                to="/register"
                append-icon="tabler-arrow-right"
              >
                Start Now
              </VBtn>
              <VBtn
                size="large"
                variant="outlined"
                prepend-icon="tabler-player-play"
                @click="scrollToFeatures"
              >
                See Features
              </VBtn>
            </div>
            <p class="text-body-2 text-medium-emphasis mb-6 hero-anim hero-anim-4">
              Already have an account? <RouterLink
                to="/login"
                class="font-weight-medium text-primary"
              >Log in</RouterLink>
            </p>
          </VCol>

          <VCol
            cols="12"
            md="6"
          >
            <VCard
              class="hero-preview-card hero-anim hero-anim-5 hero-float"
              elevation="12"
              rounded="lg"
            >
              <VCardText>
                <div class="d-flex align-center gap-3 mb-4">
                  <VAvatar
                    color="success"
                    variant="tonal"
                    size="40"
                  >
                    <VIcon icon="tabler-brand-whatsapp" />
                  </VAvatar>
                  <div>
                    <div class="font-weight-medium">
                      WhatsApp Messages
                    </div>
                    <div class="text-caption text-medium-emphasis">
                      Today's stats
                    </div>
                  </div>
                  <VSpacer />
                  <div class="text-h5 font-weight-bold">
                    12,450
                  </div>
                </div>
                <VRow dense>
                  <VCol cols="6">
                    <div class="stat-tile stat-tile-primary">
                      <div class="text-caption text-medium-emphasis">
                        Delivered
                      </div>
                      <div class="text-h6 font-weight-bold">
                        98.5%
                      </div>
                    </div>
                  </VCol>
                  <VCol cols="6">
                    <div class="stat-tile">
                      <div class="text-caption text-medium-emphasis">
                        Read Rate
                      </div>
                      <div class="text-h6 font-weight-bold">
                        72.3%
                      </div>
                    </div>
                  </VCol>
                </VRow>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section
      ref="kpiSectionEl"
      class="kpi-band"
    >
      <VContainer>
        <VRow>
          <VCol
            v-for="(kpi, index) in kpis"
            :key="kpi.label"
            cols="6"
            md="3"
            class="text-center"
          >
            <div class="kpi-value">
              {{ kpiDisplays[index] }}
            </div>
            <div class="kpi-label">
              {{ kpi.label }}
            </div>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section
      id="features"
      class="section-py"
    >
      <VContainer>
        <div
          v-reveal
          class="text-center section-heading"
        >
          <VChip
            color="primary"
            variant="tonal"
            size="small"
            class="mb-3"
          >
            Features
          </VChip>
          <h2 class="text-h3 font-weight-bold mb-3">
            Everything You Need to Scale Customer Communication
          </h2>
          <p class="text-medium-emphasis">
            From WhatsApp Business API to DLT-compliant SMS, Textzi provides all the tools you need to engage customers effectively.
          </p>
        </div>

        <VRow>
          <VCol
            v-for="(feature, index) in features"
            :key="feature.title"
            cols="12"
            sm="6"
            md="4"
            v-reveal="index"
          >
            <VCard
              variant="outlined"
              class="feature-card"
              height="100%"
            >
              <VCardText>
                <VAvatar
                  color="primary"
                  variant="tonal"
                  size="48"
                  rounded="lg"
                  class="mb-4 feature-icon"
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
        <div
          v-reveal
          class="text-center section-heading"
        >
          <VChip
            color="primary"
            variant="tonal"
            size="small"
            class="mb-3"
          >
            How It Works
          </VChip>
          <h2 class="text-h3 font-weight-bold">
            Get Started in Minutes
          </h2>
        </div>

        <VRow>
          <VCol
            v-for="(step, index) in steps"
            :key="step.number"
            cols="12"
            md="4"
            class="text-center step-col"
            v-reveal="index"
          >
            <div class="step-number">
              {{ step.number }}
            </div>
            <h3 class="text-h6 font-weight-bold mb-2">
              {{ step.title }}
            </h3>
            <p class="text-medium-emphasis">
              {{ step.desc }}
            </p>
            <VIcon
              v-if="index < steps.length - 1"
              icon="tabler-arrow-right"
              class="step-arrow d-none d-md-inline-flex"
            />
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section class="trust-section section-py">
      <VContainer>
        <VRow align="center">
          <VCol
            v-reveal
            cols="12"
            md="6"
          >
            <VChip
              color="primary"
              variant="tonal"
              size="small"
              class="mb-3"
            >
              Built for India
            </VChip>
            <h2 class="text-h3 font-weight-bold mb-4">
              Made for Indian Businesses, by People Who Understand Them
            </h2>
            <p class="text-medium-emphasis mb-5">
              We understand the unique challenges of business communication in India. From DLT compliance to regional language support, Textzi is built ground-up for the Indian market.
            </p>
            <div
              v-for="point in trustPoints"
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
            <VRow>
              <VCol
                v-for="(stat, index) in trustStats"
                :key="stat.label"
                cols="6"
                v-reveal="index"
              >
                <VCard
                  variant="outlined"
                  class="text-center pa-4 trust-stat-card"
                >
                  <VIcon
                    :icon="stat.icon"
                    color="primary"
                    size="32"
                    class="mb-2"
                  />
                  <div class="font-weight-medium">
                    {{ stat.label }}
                  </div>
                </VCard>
              </VCol>
            </VRow>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section
      id="pricing"
      class="section-py bg-surface"
    >
      <VContainer>
        <div
          v-reveal
          class="text-center section-heading"
        >
          <VChip
            color="primary"
            variant="tonal"
            size="small"
            class="mb-3"
          >
            Pricing
          </VChip>
          <h2 class="text-h3 font-weight-bold mb-3">
            Pricing for Every Channel
          </h2>
          <p class="text-medium-emphasis">
            Pay-as-you-go SMS and WhatsApp pricing, no monthly lock-in — or talk to us for a custom plan.
          </p>
        </div>

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
            v-reveal="0"
            cols="12"
            md="4"
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
            v-reveal="1"
            cols="12"
            md="4"
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
            v-reveal="2"
            cols="12"
            md="4"
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
                  High volume, dedicated account manager, custom integrations, or a bespoke blend of SMS and WhatsApp — let's talk about what you need.
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

    <section
      v-if="testimonials.length"
      id="testimonials"
      class="section-py"
    >
      <VContainer>
        <div
          v-reveal
          class="text-center section-heading"
        >
          <VChip
            color="primary"
            variant="tonal"
            size="small"
            class="mb-3"
          >
            Testimonials
          </VChip>
          <h2 class="text-h3 font-weight-bold">
            Loved by Businesses Across India
          </h2>
        </div>

      </VContainer>

      <div
        v-reveal
        class="testimonial-marquee-wrapper mt-4"
      >
        <div
          class="testimonial-marquee-track"
          :style="{ '--marquee-duration': `${testimonials.length * 8}s` }"
        >
          <VCard
            v-for="(testimonial, index) in [...testimonials, ...testimonials]"
            :key="`${testimonial.author_name}-${index}`"
            variant="outlined"
            class="testimonial-card testimonial-marquee-item"
          >
            <VCardText>
              <VRating
                :model-value="5"
                color="warning"
                density="compact"
                readonly
                class="mb-3"
              />
              <p class="mb-4">
                "{{ testimonial.quote }}"
              </p>
              <div class="d-flex align-center gap-3">
                <VAvatar
                  color="primary"
                  variant="tonal"
                >
                  {{ testimonial.author_name.split(' ').map(n => n[0]).join('') }}
                </VAvatar>
                <div>
                  <div class="font-weight-medium">
                    {{ testimonial.author_name }}
                  </div>
                  <div class="text-caption text-medium-emphasis">
                    {{ testimonial.author_role }}
                  </div>
                </div>
              </div>
            </VCardText>
          </VCard>
        </div>
      </div>
    </section>

    <section class="section-py bg-surface">
      <VContainer>
        <VRow align="center">
          <VCol
            v-reveal
            cols="12"
            md="6"
          >
            <VChip
              color="primary"
              variant="tonal"
              size="small"
              class="mb-3"
            >
              Support
            </VChip>
            <h2 class="text-h3 font-weight-bold mb-4">
              We're Here to Help You Succeed
            </h2>
            <p class="text-medium-emphasis mb-6">
              Our dedicated support team is available round the clock to help you with setup, troubleshooting, and optimising your campaigns for maximum impact.
            </p>
            <VRow>
              <VCol
                v-for="channel in supportChannels"
                :key="channel.label"
                cols="6"
              >
                <RouterLink
                  :to="channel.to"
                  class="d-flex align-center gap-3 support-channel-link"
                >
                  <VAvatar
                    color="primary"
                    variant="tonal"
                    size="36"
                  >
                    <VIcon
                      :icon="channel.icon"
                      size="18"
                    />
                  </VAvatar>
                  <span class="font-weight-medium">{{ channel.label }}</span>
                </RouterLink>
              </VCol>
            </VRow>
          </VCol>

          <VCol
            v-reveal="1"
            cols="12"
            md="6"
          >
            <VCard
              class="support-panel d-flex align-center justify-center text-center"
              rounded="lg"
            >
              <VCardText>
                <VIcon
                  icon="tabler-headset"
                  size="56"
                  color="primary"
                  class="mb-4"
                />
                <div class="text-h6 font-weight-bold">
                  24/7 Support Available
                </div>
                <div class="text-medium-emphasis">
                  Real people, real answers, any time you need them.
                </div>
              </VCardText>
            </VCard>
          </VCol>
        </VRow>
      </VContainer>
    </section>

    <section class="cta-band">
      <div class="cta-blob" />
      <VContainer
        v-reveal
        class="text-center"
      >
        <h2 class="text-h3 font-weight-bold mb-4">
          Ready to Transform Your Customer Communication?
        </h2>
        <p class="mb-6">
          Join Indian businesses already using Textzi to engage customers on WhatsApp and SMS.
        </p>
        <div class="d-flex flex-wrap justify-center gap-4 mb-4">
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
            @click="scrollToContact"
          >
            Schedule Demo
          </VBtn>
        </div>
        <p class="text-body-2 cta-login-hint">
          Already have an account? <RouterLink
            to="/login"
            class="font-weight-medium"
          >Log in</RouterLink>
        </p>
      </VContainer>
    </section>

    <section
      id="contact"
      class="section-py bg-surface"
    >
      <VContainer>
        <div
          v-reveal
          class="text-center section-heading"
        >
          <VChip
            color="primary"
            variant="tonal"
            size="small"
            class="mb-3"
          >
            Contact
          </VChip>
          <h2 class="text-h3 font-weight-bold mb-3">
            Talk to Our Team
          </h2>
          <p class="text-medium-emphasis">
            Questions about pricing, DLT compliance, or want a demo? Send us a message and we'll get back to you.
          </p>
        </div>

        <VRow
          v-reveal
          justify="center"
        >
          <VCol
            cols="12"
            md="7"
            lg="6"
          >
            <VCard variant="outlined">
              <VCardText>
                <VAlert
                  v-if="contactSuccess"
                  type="success"
                  variant="tonal"
                  class="mb-4"
                >
                  {{ contactSuccess }}
                </VAlert>
                <VAlert
                  v-if="contactError"
                  type="error"
                  variant="tonal"
                  class="mb-4"
                >
                  {{ contactError }}
                </VAlert>
                <VForm
                  v-if="!contactSuccess"
                  @submit.prevent="onSubmitContact"
                >
                  <VRow>
                    <VCol
                      cols="12"
                      md="6"
                    >
                      <VTextField
                        v-model="contactForm.name"
                        label="Full Name"
                        :rules="[v => !!v || 'Required']"
                      />
                    </VCol>
                    <VCol
                      cols="12"
                      md="6"
                    >
                      <VTextField
                        v-model="contactForm.email"
                        label="Email"
                        type="email"
                        :rules="[v => !!v || 'Required']"
                      />
                    </VCol>
                    <VCol
                      cols="12"
                      md="6"
                    >
                      <VTextField
                        v-model="contactForm.phone"
                        label="Phone"
                        :rules="[v => !!v || 'Required']"
                      />
                    </VCol>
                    <VCol
                      cols="12"
                      md="6"
                    >
                      <VTextField
                        v-model="contactForm.company"
                        label="Company"
                        :rules="[v => !!v || 'Required']"
                      />
                    </VCol>
                    <VCol cols="12">
                      <VTextarea
                        v-model="contactForm.message"
                        label="Message"
                        rows="4"
                        :rules="[v => !!v || 'Required']"
                      />
                    </VCol>
                    <VCol cols="12">
                      <TurnstileWidget
                        id="turnstile-contact"
                        ref="contactTurnstileRef"
                        v-model="contactTurnstileToken"
                      />
                    </VCol>
                    <VCol cols="12">
                      <VBtn
                        type="submit"
                        color="primary"
                        :loading="contactSubmitting"
                        block
                      >
                        Send Message
                      </VBtn>
                    </VCol>
                  </VRow>
                </VForm>
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

.hero-section {
  position: relative;
  overflow: hidden;
  padding-block: 5rem 4rem;
  background: linear-gradient(180deg, rgba(var(--v-theme-primary), 0.08) 0%, rgba(var(--v-theme-primary), 0) 100%);
}

.hero-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(60px);
  background: rgba(var(--v-theme-primary), 0.18);
  pointer-events: none;
  z-index: 0;
}

.hero-blob-1 {
  inline-size: 380px;
  block-size: 380px;
  inset-inline-end: -120px;
  inset-block-start: -80px;
  animation: blob-drift-1 14s ease-in-out infinite;
}

.hero-blob-2 {
  inline-size: 260px;
  block-size: 260px;
  inset-inline-start: -80px;
  inset-block-end: -60px;
  background: rgba(var(--v-theme-primary), 0.12);
  animation: blob-drift-2 18s ease-in-out infinite;
}

.hero-section > .v-container {
  position: relative;
  z-index: 1;
}

.support-channel-link {
  color: inherit;
  text-decoration: none;
  border-radius: 8px;
  transition: color 0.15s ease;

  &:hover {
    color: rgb(var(--v-theme-primary));
  }
}

.hero-title {
  font-size: 3rem;
  font-weight: 800;
  line-height: 1.15;
}

.hero-subtitle {
  font-size: 1.125rem;
  color: rgba(var(--v-theme-on-surface), var(--v-medium-emphasis-opacity));
  max-inline-size: 34rem;
}

.hero-preview-card {
  max-inline-size: 420px;
  margin-inline: auto;
}

.hero-anim {
  opacity: 0;
  transform: translateY(20px);
  animation: fade-in-up 0.7s ease forwards;
}

.hero-anim-1 { animation-delay: 0.05s; }
.hero-anim-2 { animation-delay: 0.15s; }
.hero-anim-3 { animation-delay: 0.25s; }
.hero-anim-4 { animation-delay: 0.35s; }
.hero-anim-5 { animation-delay: 0.3s; }

.hero-float {
  animation: fade-in-up 0.7s ease forwards, float 6s ease-in-out 0.9s infinite;
}

.stat-tile {
  padding: 12px;
  border-radius: 10px;
  background: rgba(var(--v-theme-on-surface), 0.04);
}

.stat-tile-primary {
  background: rgba(var(--v-theme-primary), 0.1);
}

.kpi-band {
  padding-block: 3rem;
  background: rgb(var(--v-theme-on-surface));
}

.kpi-value {
  font-size: 2.25rem;
  font-weight: 800;
  color: rgb(var(--v-theme-primary));
}

.kpi-label {
  color: rgba(var(--v-theme-surface), 0.7);
}

.section-py {
  padding-block: 5rem;
}

.section-heading {
  max-inline-size: 640px;
  margin-inline: auto;
  margin-block-end: 3rem;
}

.feature-card {
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.feature-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 28px rgba(var(--v-theme-on-surface), 0.12);
}

.feature-card:hover .feature-icon {
  transform: scale(1.1) rotate(-6deg);
}

.feature-icon {
  transition: transform 0.3s ease;
}

.step-col {
  position: relative;
}

.step-number {
  font-size: 2.5rem;
  font-weight: 800;
  color: rgba(var(--v-theme-primary), 0.3);
  transition: color 0.3s ease;
}

.step-col:hover .step-number {
  color: rgba(var(--v-theme-primary), 0.6);
}

.step-arrow {
  position: absolute;
  inset-block-start: 8px;
  inset-inline-end: -1.5rem;
  color: rgba(var(--v-theme-on-surface), 0.3);
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

.pricing-card-popular:hover {
  transform: translateY(-6px) scale(1.01);
}

.pricing-popular-badge {
  position: absolute;
  inset-block-start: -10px;
  inset-inline-start: 50%;
  transform: translate(-50%, -100%);
  animation: badge-pulse 2.4s ease-in-out infinite;
}

.trust-stat-card {
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.trust-stat-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 20px rgba(var(--v-theme-on-surface), 0.1);
}

.testimonial-marquee-wrapper {
  overflow: hidden;
  inline-size: 100%;
  mask-image: linear-gradient(to right, transparent, black 6%, black 94%, transparent);
  -webkit-mask-image: linear-gradient(to right, transparent, black 6%, black 94%, transparent);
}

.testimonial-marquee-track {
  display: flex;
  gap: 24px;
  inline-size: max-content;
  padding-block: 8px;
  animation: testimonial-marquee-scroll var(--marquee-duration, 40s) linear infinite;
}

.testimonial-marquee-wrapper:hover .testimonial-marquee-track {
  animation-play-state: paused;
}

.testimonial-card {
  flex: 0 0 auto;
  inline-size: 340px;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.testimonial-card:hover {
  transform: translateY(-6px);
  box-shadow: 0 12px 28px rgba(var(--v-theme-on-surface), 0.12);
}

@keyframes testimonial-marquee-scroll {
  from {
    transform: translateX(0);
  }
  to {
    transform: translateX(-50%);
  }
}

@media (prefers-reduced-motion: reduce) {
  .testimonial-marquee-track {
    animation: none;
  }
}

.support-panel {
  block-size: 100%;
  min-block-size: 260px;
  background: rgba(var(--v-theme-primary), 0.06);
}

.cta-band {
  position: relative;
  overflow: hidden;
  padding-block: 5rem;
  background: rgb(var(--v-theme-primary));
  color: white;
}

.cta-band > .v-container {
  position: relative;
  z-index: 1;
}

.cta-login-hint {
  color: rgba(255, 255, 255, 0.85);
}

.cta-login-hint a {
  color: white;
}

.cta-blob {
  position: absolute;
  inset-block-start: -140px;
  inset-inline-start: 50%;
  inline-size: 500px;
  block-size: 500px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  filter: blur(40px);
  transform: translateX(-50%);
  animation: blob-drift-1 16s ease-in-out infinite;
  pointer-events: none;
}

// Reveal-on-scroll (see the vReveal directive above)
.reveal-init {
  opacity: 0;
  transform: translateY(28px);
  transition: opacity 0.6s ease, transform 0.6s ease;
}

.reveal-active {
  opacity: 1;
  transform: translateY(0);
}

@keyframes fade-in-up {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes float {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-12px);
  }
}

@keyframes badge-pulse {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(var(--v-theme-primary), 0.4);
  }
  50% {
    box-shadow: 0 0 0 8px rgba(var(--v-theme-primary), 0);
  }
}

@keyframes blob-drift-1 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
  }
  50% {
    transform: translate(-30px, 30px) scale(1.08);
  }
}

@keyframes blob-drift-2 {
  0%, 100% {
    transform: translate(0, 0) scale(1);
  }
  50% {
    transform: translate(24px, -20px) scale(1.06);
  }
}

@media (prefers-reduced-motion: reduce) {
  .hero-anim,
  .hero-float,
  .hero-blob,
  .cta-blob,
  .pricing-popular-badge,
  .reveal-init {
    animation: none !important;
    opacity: 1 !important;
    transform: none !important;
    transition: none !important;
  }
}
</style>
