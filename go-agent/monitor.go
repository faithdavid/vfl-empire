package main

import (
	"encoding/json"
	"log"
	"time"
)

// Monitor polls the MSport event list and detects new events
type Monitor struct {
	client   *MSportClient
	interval time.Duration
	events   chan<- *VflEvent
	quit     chan struct{}
}

type VflEvent struct {
	EventID   string  `json:"eventId"`
	HomeTeam  string  `json:"homeTeam"`
	AwayTeam  string  `json:"awayTeam"`
	StartTime int64   `json:"startTime"`
	Status    int     `json:"status"`
	SeasonID  string  `json:"seasonId"`
	SeasonName string `json:"seasonName"`
	MatchDay  int     `json:"matchDay"`
	Category  string  `json:"category"`
}

type EventListResponse struct {
	Data struct {
		MatchDays []struct {
			SeasonID    string      `json:"seasonId"`
			SeasonName  string      `json:"seasonName"`
			MatchDay    int         `json:"matchDay"`
			Events      []*VflEvent `json:"events"`
		} `json:"matchDays"`
	} `json:"data"`
}

func NewMonitor(client *MSportClient, interval time.Duration, events chan<- *VflEvent) *Monitor {
	return &Monitor{
		client:   client,
		interval: interval,
		events:   events,
		quit:     make(chan struct{}),
	}
}

func (m *Monitor) Start() {
	log.Printf("Monitor started: polling every %v", m.interval)
	ticker := time.NewTicker(m.interval)
	defer ticker.Stop()

	// Track seen event IDs to detect new ones
	seen := make(map[string]bool)

	// Do first poll immediately
	m.poll(seen)

	for {
		select {
		case <-ticker.C:
			m.poll(seen)
		case <-m.quit:
			log.Println("Monitor stopped")
			return
		}
	}
}

func (m *Monitor) Stop() {
	close(m.quit)
}

func (m *Monitor) poll(seen map[string]bool) {
	raw, err := m.client.GetEventList()
	if err != nil {
		log.Printf("Monitor: poll error: %v", err)
		return
	}

	var resp EventListResponse
	if err := json.Unmarshal(raw, &resp); err != nil {
		log.Printf("Monitor: parse error: %v", err)
		return
	}

	newCount := 0
	for _, md := range resp.Data.MatchDays {
		for _, ev := range md.Events {
			// Fill in season info from parent
			if ev.SeasonID == "" {
				ev.SeasonID = md.SeasonID
				ev.SeasonName = md.SeasonName
				ev.MatchDay = md.MatchDay
			}

			// Only process pre-match events
			if ev.Status != 0 {
				continue
			}

			// Check if this is new
			if !seen[ev.EventID] {
				seen[ev.EventID] = true
				select {
				case m.events <- ev:
					newCount++
				default:
					// Channel full, skip
				}
			}
		}
	}

	if newCount > 0 {
		log.Printf("Monitor: %d new events detected (total tracked: %d)", newCount, len(seen))
	}
}
