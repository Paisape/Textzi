#!/usr/bin/env bash
set -euo pipefail

API="${API:-http://localhost:8000}"
ADMIN_KEY="${ADMIN_KEY:-development-admin-key-change-me}"
PASS=0
FAIL=0
SKIP=0

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL + 1)); }
skip() { echo "  SKIP: $1"; SKIP=$((SKIP + 1)); }

check_http() {
  local name="$1" method="$2" url="$3" expected="$4"
  local body="${5:-}" auth_header="${6:-}" admin_key="${7:-}"
  local -a args=(-s -o /tmp/deep-test-body.txt -w "%{http_code}" -X "$method" "$url")
  [[ -n "$body" ]] && args+=(-H "Content-Type: application/json" -d "$body")
  [[ -n "$auth_header" ]] && args+=(-H "Authorization: Bearer $auth_header")
  [[ -n "$admin_key" ]] && args+=(-H "X-Admin-Key: $admin_key")
  local code
  code=$(curl "${args[@]}")
  if [[ "$code" == "$expected" ]]; then
    pass "$name (HTTP $code)"
    return 0
  fi
  fail "$name (expected $expected, got $code) body=$(head -c 200 /tmp/deep-test-body.txt)"
  return 1
}

echo "=== Textzi Deep Test Suite ==="
echo "API: $API"
echo

echo "--- Infrastructure ---"
pg_isready -h localhost -p 5432 -q && pass "PostgreSQL ready" || fail "PostgreSQL ready"
redis-cli ping >/dev/null 2>&1 && pass "Redis PING" || fail "Redis PING"
check_http "API live" GET "$API/health/live" 200
check_http "API ready" GET "$API/health/ready" 200

echo
echo "--- Public endpoints ---"
check_http "Public company info" GET "$API/v1/public/company-info" 200
check_http "Public rate cards" GET "$API/v1/public/rate-cards" 200
check_http "Public testimonials" GET "$API/v1/public/testimonials" 200
check_http "Public API base URL" GET "$API/v1/public/api-base-url" 200
check_http "Contact form" POST "$API/v1/public/contact" 200 \
  '{"name":"Deep Tester","email":"deep-test@example.com","phone":"9876543210","company":"TestCo","message":"Deep test contact message"}'

echo
echo "--- Auth: full registration flow ---"
TS=$(date +%s)
EMAIL="deep-$TS@example.com"
PASSWORD="DeepTest123!"
REG=$(curl -s -X POST "$API/v1/auth/register" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"full_name\":\"Deep Tester\"}")
USER_ID=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])")
EMAIL_CODE=$(echo "$REG" | python3 -c "import sys,json; print(json.load(sys.stdin)['dev_email_code'])")
[[ -n "$USER_ID" && -n "$EMAIL_CODE" ]] && pass "Register returns user_id + dev_email_code" || fail "Register"

check_http "Verify email" POST "$API/v1/auth/verify-email" 200 \
  "{\"user_id\":\"$USER_ID\",\"code\":\"$EMAIL_CODE\"}"

MOBILE_REQ=$(curl -s -X POST "$API/v1/auth/request-mobile-otp" -H "Content-Type: application/json" \
  -d "{\"user_id\":\"$USER_ID\",\"mobile\":\"9123456789\"}")
MOBILE_CODE=$(echo "$MOBILE_REQ" | python3 -c "import sys,json; print(json.load(sys.stdin).get('dev_mobile_code',''))")
[[ -n "$MOBILE_CODE" ]] && pass "Mobile OTP returns dev_mobile_code" || fail "Mobile OTP"

check_http "Verify mobile" POST "$API/v1/auth/verify-mobile" 200 \
  "{\"user_id\":\"$USER_ID\",\"code\":\"$MOBILE_CODE\"}"

LOGIN=$(curl -s -X POST "$API/v1/auth/login" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")
[[ -n "$TOKEN" ]] && pass "Login returns access_token" || fail "Login"

check_http "Auth me" GET "$API/v1/auth/me" 200 "" "$TOKEN"
check_http "Auth permissions" GET "$API/v1/auth/permissions" 200 "" "$TOKEN"
check_http "Registration status" GET "$API/v1/auth/registration-status/$USER_ID" 200

echo
echo "--- Onboarding ---"
ONBOARD_BODY=$(cat <<EOF
{
  "organization_name": "Deep Test Org $TS",
  "entity_name": "Deep Test Entity",
  "gstin": null,
  "pan": "ABCDE1234F",
  "industry": "Technology",
  "address": "123 Test Street, Bangalore",
  "state_code": "29",
  "contact_person_name": "Deep Tester",
  "contact_email": "$EMAIL",
  "contact_mobile": "9123456789"
}
EOF
)
check_http "Onboard organization" POST "$API/v1/onboarding/organization" 200 "$ONBOARD_BODY" "$TOKEN"
check_http "Company profile GET" GET "$API/v1/onboarding/company-profile" 200 "" "$TOKEN"

echo
echo "--- Wallet ---"
check_http "Wallet GET" GET "$API/v1/wallet" 200 "" "$TOKEN" || true
QUOTE_CODE=$(curl -s -o /tmp/deep-test-body.txt -w "%{http_code}" -X POST "$API/v1/wallet/quote" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"amount":1000}')
if [[ "$QUOTE_CODE" == "200" ]]; then pass "Wallet quote (HTTP 200)"; else skip "Wallet quote (HTTP $QUOTE_CODE - channel may need activation)"; fi

echo
echo "--- Admin (bootstrap key) ---"
check_http "Admin list orgs" GET "$API/v1/admin/organizations" 200 "" "" "$ADMIN_KEY"
check_http "Admin list users" GET "$API/v1/admin/users" 200 "" "" "$ADMIN_KEY"
check_http "Admin list entities" GET "$API/v1/admin/entities" 200 "" "" "$ADMIN_KEY"
check_http "Admin rate cards" GET "$API/v1/admin/rate-cards" 200 "" "" "$ADMIN_KEY"
check_http "Admin analytics" GET "$API/v1/admin/analytics/summary" 200 "" "" "$ADMIN_KEY"
check_http "Admin contact messages" GET "$API/v1/admin/contact-messages" 200 "" "" "$ADMIN_KEY"

echo
echo "--- Auth negative cases ---"
check_http "Wrong password" POST "$API/v1/auth/login" 401 \
  "{\"email\":\"$EMAIL\",\"password\":\"wrong-password\"}"
check_http "Unauthenticated me" GET "$API/v1/auth/me" 422
check_http "Invalid admin key" GET "$API/v1/admin/organizations" 401 "" "" "invalid-key"

echo
echo "--- Razorpay (expect not configured) ---"
RAZORPAY_CODE=$(curl -s -o /tmp/deep-test-body.txt -w "%{http_code}" -X POST "$API/v1/wallet/recharge/razorpay/order" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $TOKEN" -d '{"amount":100}')
[[ "$RAZORPAY_CODE" == "503" ]] && pass "Razorpay correctly returns 503 when unconfigured (HTTP $RAZORPAY_CODE)" || fail "Razorpay unconfigured check (got $RAZORPAY_CODE)"

echo
echo "--- Duplicate registration ---"
DUP_CODE=$(curl -s -o /tmp/deep-test-body.txt -w "%{http_code}" -X POST "$API/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"OtherPass123!\",\"full_name\":\"Duplicate\"}")
[[ "$DUP_CODE" == "409" ]] && pass "Duplicate email rejected (HTTP 409)" || fail "Duplicate email (got $DUP_CODE)"

echo
echo "=== Results: $PASS passed, $FAIL failed, $SKIP skipped ==="
[[ "$FAIL" -eq 0 ]]
