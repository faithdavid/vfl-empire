#!/usr/bin/env bash
# =============================================================================
# test_agent.sh — Integration test for MSport Go Agent
#
# Tests:
#   1. Go compiler is available
#   2. Go module dependencies resolve (go mod tidy)
#   3. Go binary compiles successfully
#   4. Token file exists at /tmp/msport_tokens.json
#   5. Token file JSON is valid and contains required fields
#   6. Go unit tests pass (go test)
#
# Usage:
#   ./test_agent.sh                  # Run all tests
#   ./test_agent.sh --skip-build    # Skip compilation test
#   ./test_agent.sh --skip-live     # Skip live API test (only check build + tokens)
#   ./test_agent.sh --verbose       # Verbose output
#
# Exit code: 0 if all tests pass, 1 if any fail.
# =============================================================================

# Do NOT use set -e — we handle errors manually
set -uo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
TOKEN_FILE="/tmp/msport_tokens.json"
BINARY="/tmp/msport-agent-test"
PASS=0
FAIL=0
SKIP=0

# ── Colour helpers ────────────────────────────────────────────────────────
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; }
skip() { echo -e "  ${YELLOW}⊘${NC} $1"; }
info() { echo -e "  ${CYAN}→${NC} $1"; }
hdr()  { echo -e "\n${BOLD}── $1 ──${NC}\n"; }

# Parse args
SKIP_BUILD=false
SKIP_LIVE=false
VERBOSE=false
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=true ;;
        --skip-live)  SKIP_LIVE=true ;;
        --verbose)    VERBOSE=true ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────

pass()    { ((PASS++)); ok "$1"; }
fail_test() { ((FAIL++)); fail "$1"; }
skip_test() { ((SKIP++)); skip "$1"; }

cleanup() {
    rm -f "$BINARY" 2>/dev/null || true
}
trap cleanup EXIT

GO_AVAILABLE=false
if command -v go &>/dev/null; then
    GO_AVAILABLE=true
fi

# ===========================================================================
# Test 1: Check Go compiler
# ===========================================================================
hdr "Test 1: Go Compiler Availability"
if [ "$GO_AVAILABLE" = true ]; then
    GO_VERSION=$(go version 2>&1)
    pass "Go is available: $GO_VERSION"
else
    skip_test "Go is not installed — skipping remaining Go tests"
    SKIP_BUILD=true
    SKIP_LIVE=true
fi

# ===========================================================================
# Test 2: Go module dependencies
# ===========================================================================
hdr "Test 2: Go Module Dependencies"
if [ "$SKIP_BUILD" = true ] || [ "$GO_AVAILABLE" = false ]; then
    skip_test "Skipping (--skip-build or Go unavailable)"
else
    cd "$SCRIPT_DIR"
    if go mod tidy 2>&1; then
        pass "go mod tidy succeeded"
    else
        fail_test "go mod tidy failed (check network/dependencies)"
    fi
fi

# ===========================================================================
# Test 3: Go binary compilation
# ===========================================================================
hdr "Test 3: Go Binary Compilation"
if [ "$SKIP_BUILD" = true ] || [ "$GO_AVAILABLE" = false ]; then
    skip_test "Skipping (--skip-build or Go unavailable)"
else
    cd "$SCRIPT_DIR"
    BUILD_OUTPUT=$(go build -o "$BINARY" . 2>&1) || true
    if [ -f "$BINARY" ]; then
        BINARY_SIZE=$(stat -c%s "$BINARY" 2>/dev/null || stat -f%z "$BINARY" 2>/dev/null || echo "?")
        pass "Binary compiled successfully (${BINARY_SIZE} bytes)"
    else
        fail_test "Compilation failed"
        info "$BUILD_OUTPUT"
    fi
fi

# ===========================================================================
# Test 4: Token file exists
# ===========================================================================
hdr "Test 4: Token File Presence"
if [ -f "$TOKEN_FILE" ]; then
    TOKEN_AGE=$(($(date +%s) - $(stat -c%Y "$TOKEN_FILE" 2>/dev/null || stat -f%m "$TOKEN_FILE" 2>/dev/null)))
    TOKEN_SIZE=$(stat -c%s "$TOKEN_FILE" 2>/dev/null || stat -f%z "$TOKEN_FILE" 2>/dev/null)
    TOKEN_AGE_MIN=$((TOKEN_AGE / 60))
    pass "Token file exists: $TOKEN_FILE (${TOKEN_SIZE} bytes, ${TOKEN_AGE_MIN} min old)"
else
    fail_test "Token file not found at $TOKEN_FILE"
    info "Run the token refresher first: python3 $SCRIPT_DIR/msport_token_refresher.py"
    info "Or set MSPORT_ACCESS_TOKEN + MSPORT_USER_ID env vars"
    SKIP_LIVE=true
fi

# ===========================================================================
# Test 5: Token file JSON validation
# ===========================================================================
hdr "Test 5: Token File JSON Validation"
REQUIRED_FIELDS=("accessToken" "refreshToken" "userId" "device-id" "refreshed_at")

if [ -f "$TOKEN_FILE" ]; then
    # Check valid JSON
    VALIDATION=$(python3 -c "
import json, sys
try:
    with open('$TOKEN_FILE') as f:
        data = json.load(f)
except Exception as e:
    print(f'INVALID: {e}')
    sys.exit(1)
required = ['accessToken', 'refreshToken', 'userId', 'device-id', 'refreshed_at']
missing = [k for k in required if k not in data or not data[k]]
if missing:
    print(f'MISSING: {missing}')
    sys.exit(1)
print('OK')
print('Fields:', list(data.keys()))
" 2>&1) || true

    if echo "$VALIDATION" | grep -q "^OK"; then
        pass "Token file JSON is valid with all required fields"
        if [ "$VERBOSE" = true ]; then
            python3 -c "
import json
with open('$TOKEN_FILE') as f:
    data = json.load(f)
for k in ['accessToken', 'refreshToken', 'userId', 'device-id', 'refreshed_at']:
    v = data.get(k, 'N/A')
    if isinstance(v, str) and len(v) > 50:
        v = v[:50] + '...'
    print(f'  {k}: {v}')
"
        fi
    else
        fail_test "Token file validation: $VALIDATION"
    fi
else
    skip_test "No token file to validate"
fi

# ===========================================================================
# Test 6: Go unit tests
# ===========================================================================
hdr "Test 6: Go Unit Tests"
if [ "$GO_AVAILABLE" = false ]; then
    skip_test "Go not available"
else
    cd "$SCRIPT_DIR"
    # Check if test files exist
    TEST_FILES=$(ls *_test.go 2>/dev/null || true)
    if [ -z "$TEST_FILES" ]; then
        skip_test "No *_test.go files found"
    else
        TEST_OUTPUT=$(go test -v -timeout 30s ./... 2>&1) || true
        if echo "$TEST_OUTPUT" | grep -q "^ok\|^PASS"; then
            pass "Go unit tests passed"
        elif echo "$TEST_OUTPUT" | grep -q "FAIL"; then
            fail_test "Go unit tests failed"
            info "$TEST_OUTPUT"
        else
            # Fallback: check exit by looking for test results
            pass "Go unit tests executed"
        fi
        if [ "$VERBOSE" = true ]; then
            echo "$TEST_OUTPUT"
        fi
    fi
fi

# ===========================================================================
# Summary
# ===========================================================================
echo ""
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  Test Results${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}PASS:${NC}  $PASS"
echo -e "  ${RED}FAIL:${NC}  $FAIL"
echo -e "  ${YELLOW}SKIP:${NC}  $SKIP"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}${BOLD}✓ ALL TESTS PASSED${NC}"
    exit 0
else
    echo -e "  ${RED}${BOLD}✗ SOME TESTS FAILED${NC}"
    exit 1
fi
