package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	fhttp "github.com/bogdanfinn/fhttp"
	tlsclient "github.com/bogdanfinn/tls-client"
	"github.com/bogdanfinn/tls-client/profiles"
)

// TokenFile represents the JSON structure of /tmp/msport_tokens.json
type TokenFile struct {
	AccessToken   string  `json:"accessToken"`
	RefreshToken  string  `json:"refreshToken"`
	UserID        string  `json:"userId"`
	DeviceID      string  `json:"device-id"`
	HighFreqToken string  `json:"highFreqToken,omitempty"`
	RefreshedAt   float64 `json:"refreshed_at"`
}

// LoadTokensFromFile reads and parses the tokens JSON file,
// stripping any surrounding quotes from values.
func LoadTokensFromFile(path string) (*TokenFile, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read token file %s: %w", path, err)
	}
	var tf TokenFile
	if err := json.Unmarshal(data, &tf); err != nil {
		return nil, fmt.Errorf("failed to parse token file: %w", err)
	}
	// Strip surrounding quotes if present (browser-style cookie storage)
	tf.AccessToken = strings.Trim(tf.AccessToken, `"`)
	tf.RefreshToken = strings.Trim(tf.RefreshToken, `"`)
	tf.UserID = strings.Trim(tf.UserID, `"`)
	tf.DeviceID = strings.Trim(tf.DeviceID, `"`)
	tf.HighFreqToken = strings.Trim(tf.HighFreqToken, `"`)
	return &tf, nil
}

// MSportClient wraps tls-client with Chrome 131 fingerprint
type MSportClient struct {
	client        tlsclient.HttpClient
	baseURL       string
	accessToken   string
	refreshToken  string
	userID        string
	deviceID      string
	highFreqToken string
}

func NewMSportClient(accessToken, refreshToken, userID, deviceID, highFreqToken string) (*MSportClient, error) {
	// Create a tls-client with Chrome 131 fingerprint
	client, err := tlsclient.NewHttpClient(tlsclient.NewNoopLogger(), []tlsclient.HttpClientOption{
		tlsclient.WithCookieJar(tlsclient.NewCookieJar()),
		tlsclient.WithClientProfile(profiles.Chrome_131),
		tlsclient.WithTimeout(10),
		tlsclient.WithInsecureSkipVerify(),
	}...)
	if err != nil {
		return nil, fmt.Errorf("failed to create tls client: %v", err)
	}

	return &MSportClient{
		client:        client,
		baseURL:       "https://www.msport.com",
		accessToken:   accessToken,
		refreshToken:  refreshToken,
		userID:        userID,
		deviceID:      deviceID,
		highFreqToken: highFreqToken,
	}, nil
}

// buildCookie constructs the cookie string with all required fields:
// accessToken, refreshToken, userId, deviceId, device-id, did, highFreqToken
func (m *MSportClient) buildCookie() string {
	parts := []string{
		fmt.Sprintf(`accessToken="%s"`, m.accessToken),
		fmt.Sprintf(`refreshToken="%s"`, m.refreshToken),
		fmt.Sprintf(`userId=%s`, m.userID),
		fmt.Sprintf(`deviceId=%s`, m.deviceID),
		fmt.Sprintf(`device-id=%s`, m.deviceID),
		fmt.Sprintf(`did=%s`, m.deviceID),
	}
	if m.highFreqToken != "" {
		parts = append(parts, fmt.Sprintf(`highFreqToken=%s`, m.highFreqToken))
	}
	return strings.Join(parts, "; ")
}

func (m *MSportClient) headers() map[string]string {
	return map[string]string{
		"Accept":             "application/json, text/plain, */*",
		"Accept-Language":    "en-GB,en;q=0.9",
		"Cache-Control":      "no-cache",
		"Connection":         "keep-alive",
		"Content-Type":       "application/json",
		"Cookie":             m.buildCookie(),
		"Origin":             "https://www.msport.com",
		"Pragma":             "no-cache",
		"Referer":            "https://www.msport.com/ng/web/virtual/details/vf:match:1402984202",
		"User-Agent":         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
		"clientid":           "WEB",
		"platform":           "WEB",
		"deviceid":           "",
		"devmem":             "16",
		"network":            "4g",
		"operId":             "2",
		"sec-ch-ua":          `"Chromium";v="131", "Not_A Brand";v="24"`,
		"sec-ch-ua-mobile":   "?0",
		"sec-ch-ua-platform": `"Windows"`,
		"sec-fetch-dest":     "empty",
		"sec-fetch-mode":     "cors",
		"sec-fetch-site":     "same-origin",
	}
}

// PlaceBet sends a bet to the MSport orders API
func (m *MSportClient) PlaceBet(single bool, stake float64, odds float64,
	eventID, specifier, outcomeID string, marketID int) (*MSportResponse, error) {

	payload := map[string]interface{}{
		"stake":    stake,
		"odds":     odds,
		"currency": "NGN",
		"type":     "SINGLE",
		"transId":  fmt.Sprintf("bet_%d", time.Now().UnixNano()),
		"selections": []map[string]interface{}{
			{
				"eventId":   eventID,
				"marketId":  marketID,
				"outcomeId": outcomeID,
				"specifier": specifier,
				"odds":      odds,
			},
		},
	}

	body, _ := json.Marshal(payload)
	reqBody := strings.NewReader(string(body))

	req, err := fhttp.NewRequest("POST", m.baseURL+"/api/ng/orders/order", reqBody)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %v", err)
	}

	// Set all headers in browser order
	for k, v := range m.headers() {
		req.Header.Set(k, v)
	}

	resp, err := m.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %v", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	var msResp MSportResponse
	json.Unmarshal(respBody, &msResp)
	msResp.HTTPStatus = resp.StatusCode

	return &msResp, nil
}

// GetEventList fetches the current event list
func (m *MSportClient) GetEventList() ([]byte, error) {
	req, err := fhttp.NewRequest("GET", m.baseURL+"/api/ng/facts-center/query/frontend/virtual/event/list?sportId=vf:sport:1&pageSize=200&pageNum=1", nil)
	if err != nil {
		return nil, err
	}
	for k, v := range m.headers() {
		req.Header.Set(k, v)
	}
	// Remove content-type for GET
	req.Header.Del("Content-Type")

	resp, err := m.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

// GetEventDetail fetches detailed info for a specific event
func (m *MSportClient) GetEventDetail(eventID string) ([]byte, error) {
	req, err := fhttp.NewRequest("GET",
		m.baseURL+"/api/ng/facts-center/query/frontend/virtual/event/detail?eventId="+eventID, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range m.headers() {
		req.Header.Set(k, v)
	}
	req.Header.Del("Content-Type")

	resp, err := m.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

// GetResults fetches results for a season/matchday
func (m *MSportClient) GetResults(seasonID string, matchDay int) ([]byte, error) {
	url := fmt.Sprintf("%s/api/ng/facts-center/query/frontend/virtual/result?seasonId=%s&matchDay=%d&pageSize=50&pageNum=1",
		m.baseURL, seasonID, matchDay)
	req, err := fhttp.NewRequest("GET", url, nil)
	if err != nil {
		return nil, err
	}
	for k, v := range m.headers() {
		req.Header.Set(k, v)
	}
	req.Header.Del("Content-Type")
	resp, err := m.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	return io.ReadAll(resp.Body)
}

// TestAuth checks if our authentication is working
func (m *MSportClient) TestAuth() (*MSportResponse, error) {
	return m.PlaceBet(true, 10, 1.5, "vf:match:1402984202", "total=1.5", "12", 18)
}

type MSportResponse struct {
	BizCode    int             `json:"bizCode"`
	Message    string          `json:"message"`
	InnerMsg   string          `json:"innerMsg"`
	Data       json.RawMessage `json:"data"`
	HTTPStatus int             `json:"-"`
}

func (r *MSportResponse) IsAuthed() bool {
	return r.BizCode != 19000
}

func (r *MSportResponse) IsSuccess() bool {
	return r.BizCode == 10000
}

func (r *MSportResponse) String() string {
	return fmt.Sprintf("HTTP %d | bizCode=%d | msg=%s | inner=%s",
		r.HTTPStatus, r.BizCode, r.Message, r.InnerMsg)
}
