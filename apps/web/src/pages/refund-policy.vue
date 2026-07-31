<script setup lang="ts">
definePage({
  meta: {
    layout: 'blank',
    public: true,
  },
})
</script>

<template>
  <div class="legal-page">
    <LandingHeader />

    <VContainer class="py-12">
      <VRow justify="center">
        <VCol
          cols="12"
          md="8"
        >
          <h1 class="text-h3 font-weight-bold mb-2">
            Refund Policy
          </h1>
          <p class="text-medium-emphasis mb-8">
            Last updated: 31 July 2026
          </p>

          <p class="text-body-1 mb-6">
            This Refund Policy applies to all payments made to Textzi, operated by
            <strong>Paisape Techfin Private Limited</strong>, for wallet recharges, DLT
            registration fees, and channel subscription fees. It should be read together with our
            <RouterLink to="/terms-of-service">
              Terms of Service
            </RouterLink>.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            1. General Policy
          </h2>
          <p class="text-body-1 mb-6">
            Textzi operates on a prepaid wallet model. Amounts you recharge are converted into
            SMS or WhatsApp credits at the rate applicable to your account and consumed as you
            send messages. Because credits are billed per message segment at the time of sending,
            <strong>SMS/WhatsApp credits already consumed by messages you have sent are
            non-refundable</strong> — the underlying cost of carrier delivery has already been
            incurred and cannot be reversed.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            2. What Can Be Refunded
          </h2>
          <p class="text-body-1 mb-2">
            You are eligible for a refund in the following situations:
          </p>
          <ul class="text-body-1 mb-6 legal-list">
            <li><strong>Duplicate payment</strong> — you were charged more than once for the same recharge due to a payment gateway or technical error;</li>
            <li><strong>Payment debited but wallet not credited</strong> — your bank/UPI account was debited but the corresponding credits never reflected in your Textzi wallet after a reasonable reconciliation window;</li>
            <li><strong>Unused wallet balance on account closure</strong> — if you close your account with a genuine, unused prepaid balance remaining (see Section 4); and</li>
            <li><strong>Fee charged for a service we failed to deliver</strong> — for example, a DLT registration fee charged where we were unable to complete the registration due to an error on our end (not due to incorrect/incomplete information you provided, or rejection by the telecom operator/DLT registry for reasons outside our control).</li>
          </ul>

          <h2 class="text-h5 font-weight-bold mb-3">
            3. What Is Not Refundable
          </h2>
          <ul class="text-body-1 mb-6 legal-list">
            <li>SMS/WhatsApp credits already consumed by messages submitted for delivery, regardless of whether the recipient's carrier or handset ultimately delivered them (delivery depends on third-party telecom/WhatsApp infrastructure outside our control — see our Terms of Service, Section 6);</li>
            <li>DLT registration fees once your registration request has been submitted to the telecom operator/DLT registry, except as described in Section 2;</li>
            <li>Channel subscription fees for the period already elapsed;</li>
            <li>GST already collected and remitted to the government on any non-refundable amount; and</li>
            <li>Amounts credited to your wallet by an admin as a goodwill/manual credit (these were never paid by you, so there's nothing to refund).</li>
          </ul>

          <h2 class="text-h5 font-weight-bold mb-3">
            4. Unused Balance on Account Closure
          </h2>
          <p class="text-body-1 mb-6">
            If you close your Textzi account with a genuine unused prepaid balance (funds you
            actually paid for that haven't been converted into consumed message credits), you may
            request a refund of that balance within 30 days of closure. We reserve the right to
            deduct any outstanding dues, applicable bank/payment gateway charges, and GST
            adjustments from the refunded amount, and to verify the account and payment history
            before processing.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            5. How to Request a Refund
          </h2>
          <p class="text-body-1 mb-6">
            Email <a href="mailto:info@paisape.in">info@paisape.in</a> or call 022-68833223 within
            30 days of the transaction, with your registered email address, the transaction/
            invoice reference, and the reason for the request. We may ask for supporting
            information (such as your bank statement showing the debit) to verify a duplicate-
            payment or payment-not-credited claim.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            6. Refund Timeline
          </h2>
          <p class="text-body-1 mb-6">
            Once a refund is approved, we process it within 7–14 business days to the original
            payment method used (bank account, card, or UPI ID), via our payment gateway. The
            actual time for the amount to reflect in your account after that depends on your
            bank or payment provider, and is outside our control.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            7. Chargebacks
          </h2>
          <p class="text-body-1 mb-6">
            Please contact us before initiating a chargeback with your bank or card issuer — most
            billing questions can be resolved directly and faster this way. Raising a chargeback
            for a legitimately consumed service (e.g. credits already used to send messages)
            without first contacting us may result in suspension of your account pending
            resolution.
          </p>

          <h2 class="text-h5 font-weight-bold mb-3">
            8. Changes to This Policy
          </h2>
          <p class="text-body-1 mb-6">
            We may update this Refund Policy from time to time. Changes will be posted here with
            an updated "Last updated" date and will apply to payments made after the change takes
            effect.
          </p>

          <VBtn
            color="primary"
            to="/#contact"
            class="mt-4"
          >
            Contact Us
          </VBtn>
        </VCol>
      </VRow>
    </VContainer>

    <LandingFooter />
  </div>
</template>

<style scoped lang="scss">
.legal-page {
  min-block-size: 100vh;
  background: rgb(var(--v-theme-background));
}

.legal-list {
  padding-inline-start: 1.25rem;

  li {
    margin-block-end: 0.5rem;
  }
}
</style>
