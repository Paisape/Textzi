/** FastAPI returns `detail` as a plain string for our own errors, but as a list of Pydantic
 * validation-error objects for automatic 422s (e.g. invalid email format). Only the string case
 * is meant for end users; the validation-error array is technical and falls back to a friendly
 * generic message instead of being shown as-is. */
export function extractErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as any)?.data?.detail
  return typeof detail === 'string' ? detail : fallback
}
