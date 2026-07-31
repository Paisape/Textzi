/** Shared handler for the `step_up_required` error a settings endpoint returns when the
 * caller's token lacks a recent-enough 2FA verification (auth.py's require_recent_2fa /
 * require_admin_recent_2fa). Wrap any $api call that might hit one of those endpoints in
 * withStepUp(...) -- on a step-up error it opens a code-entry dialog, exchanges the code for a
 * freshly-stamped token via POST /v1/auth/step-up-2fa, then retries the original call once. */
export function useStepUpAuth() {
  const dialogOpen = ref(false)
  const code = ref('')
  const error = ref('')
  const submitting = ref(false)
  let resolver: ((ok: boolean) => void) | null = null

  function isStepUpError(err: unknown): boolean {
    return (err as any)?.data?.detail === 'step_up_required'
  }

  function requestStepUp(): Promise<boolean> {
    error.value = ''
    code.value = ''
    dialogOpen.value = true
    return new Promise(resolve => { resolver = resolve })
  }

  async function submit() {
    submitting.value = true
    error.value = ''
    try {
      const data = await $api<{ access_token: string }>('/v1/auth/step-up-2fa', {
        method: 'POST',
        body: { code: code.value },
      })
      useCookie('accessToken').value = data.access_token
      dialogOpen.value = false
      resolver?.(true)
    }
    catch (err: any) {
      error.value = extractErrorMessage(err, 'Incorrect authenticator code.')
    }
    finally {
      submitting.value = false
    }
  }

  function cancel() {
    dialogOpen.value = false
    resolver?.(false)
  }

  async function withStepUp<T>(action: () => Promise<T>): Promise<T> {
    try {
      return await action()
    }
    catch (err) {
      if (!isStepUpError(err))
        throw err
      const ok = await requestStepUp()
      if (!ok)
        throw err
      return await action()
    }
  }

  return { dialogOpen, code, error, submitting, submit, cancel, withStepUp }
}
