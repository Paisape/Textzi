export type RazorpayOrder = { order_id: string, key_id: string, amount_paise: number }
export type RazorpayPaymentResponse = { razorpay_order_id: string, razorpay_payment_id: string, razorpay_signature: string }

let scriptPromise: Promise<void> | null = null

function loadRazorpayScript(): Promise<void> {
  if ((window as any).Razorpay)
    return Promise.resolve()
  if (!scriptPromise) {
    scriptPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = 'https://checkout.razorpay.com/v1/checkout.js'
      script.onload = () => resolve()
      script.onerror = () => reject(new Error('Could not load Razorpay checkout script.'))
      document.head.appendChild(script)
    })
  }
  return scriptPromise
}

/** Opens Razorpay checkout for an order the backend already created. Resolves with the signed
 * payment response to send to the matching /verify endpoint; rejects if the user closes it. */
export async function openRazorpayCheckout(order: RazorpayOrder, description: string): Promise<RazorpayPaymentResponse> {
  await loadRazorpayScript()

  return new Promise((resolve, reject) => {
    const instance = new (window as any).Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: 'INR',
      name: 'Textzi',
      description,
      order_id: order.order_id,
      theme: { color: '#F1600D' },
      handler: (response: RazorpayPaymentResponse) => resolve(response),
      modal: { ondismiss: () => reject(new Error('Payment was not completed.')) },
    })

    instance.open()
  })
}
