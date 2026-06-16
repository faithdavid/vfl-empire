package main

import (
	"encoding/json"
	"fmt"
	"log"
	"os"
	"time"
)

func main() {
	log.SetFlags(log.Ltime | log.Lmicroseconds)
	log.SetOutput(os.Stdout)

	log.Println("=== MSport Go Agent ===")

	// Load tokens from file (written by the token refresher)
	client, err := createClientFromTokens()
	if err != nil {
		log.Fatalf("Failed to create client: %v", err)
	}

	log.Println("Client created with Chrome 131 TLS fingerprint")

	// Test authentication
	log.Println("Testing authentication...")
	time.Sleep(500 * time.Millisecond)

	// First test: try to get event list (should work with auth)
	log.Println("Fetching event list...")
	raw, err := client.GetEventList()
	if err != nil {
		log.Printf("Event list error: %v", err)
	} else {
		var listResp EventListResponse
		if err := json.Unmarshal(raw, &listResp); err != nil {
			log.Printf("Parse error: %v", err)
			log.Printf("Raw: %s", string(raw[:min(500, len(raw))]))
		} else {
			totalEvents := 0
			for _, md := range listResp.Data.MatchDays {
				totalEvents += len(md.Events)
				log.Printf("  %s MD%d: %d events",
					md.SeasonName, md.MatchDay, len(md.Events))
			}
			log.Printf("Total: %d events across %d matchdays",
				totalEvents, len(listResp.Data.MatchDays))
		}
	}

	// Test auth by trying to place a bet (will likely fail but tells us auth status)
	log.Println("Testing bet placement API auth...")
	authResp, err := client.TestAuth()
	if err != nil {
		log.Printf("Auth test request failed: %v", err)
	} else {
		log.Printf("Auth test: %s", authResp.String())
		if authResp.IsAuthed() {
			log.Println("✅ AUTHENTICATION WORKING!")
			log.Printf("Response: %s", string(authResp.Data))
		} else {
			log.Printf("❌ Auth failed: %s", authResp.InnerMsg)
		}
	}

	log.Println()
	log.Println("=== Starting listener-worker architecture ===")

	// Create event channel (buffered)
	events := make(chan *VflEvent, 100)

	// Start executor workers
	executor := NewExecutor(client, events)
	executor.Start(4) // 4 concurrent workers

	// Start monitor (5 second poll interval)
	monitor := NewMonitor(client, 5*time.Second, events)
	monitor.Start() // blocks forever
}

// createClientFromTokens loads tokens from /tmp/msport_tokens.json (primary)
// or falls back to environment variables (no hardcoded defaults).
func createClientFromTokens() (*MSportClient, error) {
	// Primary: load from token refresher file
	tf, err := LoadTokensFromFile("/home/ubuntu/faith-workspace/vfl-empire/data/msport_tokens.json")
	if err == nil {
		log.Printf("Tokens loaded from /home/ubuntu/faith-workspace/vfl-empire/data/msport_tokens.json (accessToken=%.40s..., userId=%s, deviceId=%s)",
			tf.AccessToken, tf.UserID, tf.DeviceID)
		return NewMSportClient(tf.AccessToken, tf.RefreshToken, tf.UserID, tf.DeviceID, tf.HighFreqToken)
	}

	log.Printf("Token file not available (%v); falling back to env vars", err)

	// Fallback: environment variables (no hardcoded defaults)
	accessToken := os.Getenv("MSPORT_ACCESS_TOKEN")
	refreshToken := os.Getenv("MSPORT_REFRESH_TOKEN")
	userID := os.Getenv("MSPORT_USER_ID")
	deviceID := os.Getenv("MSPORT_DEVICE_ID")
	highFreqToken := os.Getenv("MSPORT_HIGH_FREQ_TOKEN")

	if accessToken == "" || userID == "" {
		return nil, fmt.Errorf("no tokens available — set MSPORT_ACCESS_TOKEN and MSPORT_USER_ID env vars, or ensure token refresher writes to /tmp/msport_tokens.json")
	}

	log.Printf("Using env vars: accessToken=%.40s..., userId=%s, deviceId=%s",
		accessToken, userID, deviceID)
	return NewMSportClient(accessToken, refreshToken, userID, deviceID, highFreqToken)
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

func init() {
	// Print banner
	fmt.Println(`
  __  __ ____   ___    ____    _    ___  
 |  \/  / ___| / _ \  / ___|  / \  | _| 
 | |\/| \___ \| | | | \___ \ / _ \ | |  
 | |  | |___) | |_| |  ___) / ___ \| |  
 |_|  |_|____/ \___/  |____/_/   \_\_\_| 
  MSport Go Agent - Low Latency Betting Engine
	`)
}
