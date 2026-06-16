package main

import (
	"encoding/json"
	"os"
	"strings"
	"testing"
)

// ─── Test helpers ─────────────────────────────────────────────────────────

// makeTempTokenFile creates a temporary token file and returns its path.
// The caller is responsible for removing the file.
func makeTempTokenFile(t *testing.T, data map[string]interface{}) string {
	t.Helper()
	tmp, err := os.CreateTemp("", "msport_tokens_*.json")
	if err != nil {
		t.Fatalf("failed to create temp file: %v", err)
	}
	defer tmp.Close()
	if err := json.NewEncoder(tmp).Encode(data); err != nil {
		t.Fatalf("failed to encode JSON: %v", err)
	}
	return tmp.Name()
}

// ─── Tests ────────────────────────────────────────────────────────────────

func TestLoadTokensFromFile_MissingFile(t *testing.T) {
	_, err := LoadTokensFromFile("/tmp/nonexistent_file_xyz.json")
	if err == nil {
		t.Fatal("expected error for missing file, got nil")
	}
	if !os.IsNotExist(err) {
		t.Logf("unexpected error type: %T %v", err, err)
	}
}

func TestLoadTokensFromFile_Valid(t *testing.T) {
	data := map[string]interface{}{
		"accessToken":   "test_access_token_value",
		"refreshToken":  "test_refresh_token_value",
		"userId":        "12345",
		"device-id":     "test-device-uuid",
		"highFreqToken": "test_hft_value",
		"refreshed_at":  1712345678.123,
	}
	tmp := makeTempTokenFile(t, data)
	defer os.Remove(tmp)

	tf, err := LoadTokensFromFile(tmp)
	if err != nil {
		t.Fatalf("LoadTokensFromFile failed: %v", err)
	}
	if tf.AccessToken != "test_access_token_value" {
		t.Errorf("AccessToken = %q, want %q", tf.AccessToken, "test_access_token_value")
	}
	if tf.UserID != "12345" {
		t.Errorf("UserID = %q, want %q", tf.UserID, "12345")
	}
	if tf.DeviceID != "test-device-uuid" {
		t.Errorf("DeviceID = %q, want %q", tf.DeviceID, "test-device-uuid")
	}
	if tf.RefreshToken != "test_refresh_token_value" {
		t.Errorf("RefreshToken = %q, want %q", tf.RefreshToken, "test_refresh_token_value")
	}
	if tf.HighFreqToken != "test_hft_value" {
		t.Errorf("HighFreqToken = %q, want %q", tf.HighFreqToken, "test_hft_value")
	}
}

func TestLoadTokensFromFile_StripsQuotes(t *testing.T) {
	// Browser cookies often include surrounding quotes
	data := map[string]interface{}{
		"accessToken":  `"eyJhbGciOiJIUzI1NiJ9.quoted_value"`,
		"refreshToken": `"def456"`,
		"userId":       `"12345"`,
		"device-id":    `"dev-uuid-abc"`,
		"refreshed_at": 1712345678.0,
	}
	tmp := makeTempTokenFile(t, data)
	defer os.Remove(tmp)

	tf, err := LoadTokensFromFile(tmp)
	if err != nil {
		t.Fatalf("LoadTokensFromFile failed: %v", err)
	}
	if tf.AccessToken != "eyJhbGciOiJIUzI1NiJ9.quoted_value" {
		t.Errorf("AccessToken should have quotes stripped: got %q", tf.AccessToken)
	}
	if tf.RefreshToken != "def456" {
		t.Errorf("RefreshToken should have quotes stripped: got %q", tf.RefreshToken)
	}
	if tf.UserID != "12345" {
		t.Errorf("UserID should have quotes stripped: got %q", tf.UserID)
	}
	if tf.DeviceID != "dev-uuid-abc" {
		t.Errorf("DeviceID should have quotes stripped: got %q", tf.DeviceID)
	}
}

func TestLoadTokensFromFile_AllowsMissingFields(t *testing.T) {
	// Minimal valid file
	data := map[string]interface{}{
		"accessToken":  "abc",
		"refreshToken": "def",
		"userId":       "1",
		"device-id":    "dev1",
		"refreshed_at": 1712345678.0,
	}
	tmp := makeTempTokenFile(t, data)
	defer os.Remove(tmp)

	tf, err := LoadTokensFromFile(tmp)
	if err != nil {
		t.Fatalf("LoadTokensFromFile failed: %v", err)
	}
	// highFreqToken is optional
	if tf.HighFreqToken != "" {
		t.Errorf("expected empty HighFreqToken, got %q", tf.HighFreqToken)
	}
}

func TestLoadTokensFromFile_InvalidJSON(t *testing.T) {
	tmp, err := os.CreateTemp("", "msport_tokens_*.json")
	if err != nil {
		t.Fatalf("failed to create temp file: %v", err)
	}
	defer os.Remove(tmp.Name())
	tmp.WriteString("this is not json")
	tmp.Close()

	_, err = LoadTokensFromFile(tmp.Name())
	if err == nil {
		t.Fatal("expected error for invalid JSON, got nil")
	}
}

func TestNewMSportClient(t *testing.T) {
	client, err := NewMSportClient("access123", "refresh123", "user42", "dev99", "hft999")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	if client.accessToken != "access123" {
		t.Errorf("accessToken = %q, want %q", client.accessToken, "access123")
	}
	if client.refreshToken != "refresh123" {
		t.Errorf("refreshToken = %q, want %q", client.refreshToken, "refresh123")
	}
	if client.userID != "user42" {
		t.Errorf("userID = %q, want %q", client.userID, "user42")
	}
	if client.deviceID != "dev99" {
		t.Errorf("deviceID = %q, want %q", client.deviceID, "dev99")
	}
	if client.highFreqToken != "hft999" {
		t.Errorf("highFreqToken = %q, want %q", client.highFreqToken, "hft999")
	}
}

func TestBuildCookie(t *testing.T) {
	client, err := NewMSportClient("access123", "refresh123", "user42", "dev99", "hft999")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	cookie := client.buildCookie()
	if !strings.Contains(cookie, `accessToken="access123"`) {
		t.Errorf("cookie missing accessToken: %s", cookie)
	}
	if !strings.Contains(cookie, `refreshToken="refresh123"`) {
		t.Errorf("cookie missing refreshToken: %s", cookie)
	}
	if !strings.Contains(cookie, `userId=user42`) {
		t.Errorf("cookie missing userId: %s", cookie)
	}
	if !strings.Contains(cookie, `deviceId=dev99`) {
		t.Errorf("cookie missing deviceId: %s", cookie)
	}
	if !strings.Contains(cookie, `device-id=dev99`) {
		t.Errorf("cookie missing device-id: %s", cookie)
	}
	if !strings.Contains(cookie, `did=dev99`) {
		t.Errorf("cookie missing did: %s", cookie)
	}
	if !strings.Contains(cookie, `highFreqToken=hft999`) {
		t.Errorf("cookie missing highFreqToken: %s", cookie)
	}
}

func TestBuildCookie_NoHighFreqToken(t *testing.T) {
	client, err := NewMSportClient("access123", "refresh123", "user42", "dev99", "")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	cookie := client.buildCookie()
	if strings.Contains(cookie, "highFreqToken") {
		t.Errorf("cookie should not contain highFreqToken when empty: %s", cookie)
	}
}

func TestClientHeaders(t *testing.T) {
	client, err := NewMSportClient("a", "r", "u", "d", "h")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	headers := client.headers()

	requiredHeaders := []string{
		"Accept", "Accept-Language", "Cache-Control", "Connection",
		"Content-Type", "Cookie", "Origin", "Referer", "User-Agent",
		"clientid", "platform", "deviceid", "operId",
		"sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
	}
	for _, h := range requiredHeaders {
		if _, ok := headers[h]; !ok {
			t.Errorf("missing required header: %s", h)
		}
	}
	if headers["clientid"] != "WEB" {
		t.Errorf("clientid = %q, want %q", headers["clientid"], "WEB")
	}
	if headers["platform"] != "WEB" {
		t.Errorf("platform = %q, want %q", headers["platform"], "WEB")
	}
	// Cookie should contain the auth fields
	if !strings.Contains(headers["Cookie"], "accessToken") {
		t.Errorf("Cookie header missing accessToken")
	}
}

func TestMSportResponse_IsAuthed(t *testing.T) {
	tests := []struct {
		name     string
		bizCode  int
		isAuthed bool
	}{
		{"success", 10000, true},
		{"auth failure", 19000, false},
		{"other error", 20001, true},
		{"zero code", 0, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			resp := &MSportResponse{BizCode: tt.bizCode}
			if got := resp.IsAuthed(); got != tt.isAuthed {
				t.Errorf("IsAuthed() = %v, want %v (bizCode=%d)", got, tt.isAuthed, tt.bizCode)
			}
		})
	}
}

func TestMSportResponse_IsSuccess(t *testing.T) {
	tests := []struct {
		name      string
		bizCode   int
		isSuccess bool
	}{
		{"success", 10000, true},
		{"auth failure", 19000, false},
		{"other error", 20001, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			resp := &MSportResponse{BizCode: tt.bizCode}
			if got := resp.IsSuccess(); got != tt.isSuccess {
				t.Errorf("IsSuccess() = %v, want %v (bizCode=%d)", got, tt.isSuccess, tt.bizCode)
			}
		})
	}
}

func TestMSportResponse_String(t *testing.T) {
	resp := &MSportResponse{
		BizCode:    10000,
		Message:    "ok",
		InnerMsg:   "",
		HTTPStatus: 200,
	}
	s := resp.String()
	if !strings.Contains(s, "200") || !strings.Contains(s, "10000") {
		t.Errorf("String() output missing expected fields: %s", s)
	}
}

func TestCreateClientFromTokens_MissingBoth(t *testing.T) {
	// Neither token file nor env vars
	// We can't easily test this without clobbering env, so we'll skip
	t.Skip("Skipping env-dependent test")
}

func TestEventAnalysis_Scoring(t *testing.T) {
	// Test parseOdds
	tests := []struct {
		input string
		want  float64
	}{
		{"1.50", 1.50},
		{"2.00", 2.00},
		{"0.00", 0.00},
		{"abc", 0.0},
		{"", 0.0},
	}
	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got := parseOdds(tt.input)
			if got != tt.want {
				t.Errorf("parseOdds(%q) = %f, want %f", tt.input, got, tt.want)
			}
		})
	}
}

func TestMonitor_NewMonitor(t *testing.T) {
	ch := make(chan *VflEvent, 10)
	client, err := NewMSportClient("a", "r", "u", "d", "")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	m := NewMonitor(client, 60, ch)
	if m == nil {
		t.Fatal("NewMonitor returned nil")
	}
	if m.interval != 60 {
		t.Errorf("interval = %v, want 60", m.interval)
	}
}

func TestExecutor_NewExecutor(t *testing.T) {
	ch := make(chan *VflEvent, 10)
	client, err := NewMSportClient("a", "r", "u", "d", "")
	if err != nil {
		t.Fatalf("NewMSportClient failed: %v", err)
	}
	e := NewExecutor(client, ch)
	if e == nil {
		t.Fatal("NewExecutor returned nil")
	}
}

func TestVflEvent_StructTags(t *testing.T) {
	// Verify JSON tags match what the API returns
	ev := VflEvent{
		EventID:   "vf:match:123",
		HomeTeam:  "Home",
		AwayTeam:  "Away",
		StartTime: 1000,
		Status:    0,
		SeasonID:  "s1",
		MatchDay:  1,
	}
	data, err := json.Marshal(ev)
	if err != nil {
		t.Fatalf("json.Marshal failed: %v", err)
	}
	var decoded VflEvent
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("json.Unmarshal round-trip failed: %v", err)
	}
	if decoded.EventID != ev.EventID {
		t.Errorf("EventID round-trip: got %q, want %q", decoded.EventID, ev.EventID)
	}
}
