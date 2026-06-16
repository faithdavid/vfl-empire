package main

import (
	"encoding/json"
	"fmt"
	"log"
)

// Executor processes events and places bets
type Executor struct {
	client *MSportClient
	events <-chan *VflEvent
}

func NewExecutor(client *MSportClient, events <-chan *VflEvent) *Executor {
	return &Executor{
		client: client,
		events: events,
	}
}

func (e *Executor) Start(workerCount int) {
	for i := 0; i < workerCount; i++ {
		go e.worker(i)
	}
	log.Printf("Executor started: %d workers", workerCount)
}

func (e *Executor) worker(id int) {
	for ev := range e.events {
		log.Printf("[Worker %d] Processing: %s vs %s [%s]", id, ev.HomeTeam, ev.AwayTeam, ev.EventID)

		// Fetch detailed event info
		detail, err := e.client.GetEventDetail(ev.EventID)
		if err != nil {
			log.Printf("[Worker %d] Detail fetch error: %v", id, err)
			continue
		}

		// Parse and analyze the event
		analysis := e.analyzeEvent(detail, ev)

		// Check if we should bet
		if analysis.ShouldBet {
			e.executeBet(analysis)
		} else {
			log.Printf("[Worker %d] Skip: %s vs %s (SA=%d/13, reason=%s)",
				id, ev.HomeTeam, ev.AwayTeam, analysis.SAScore, analysis.SkipReason)
		}
	}
}

// EventAnalysis stores the analysis result for a fixture
type EventAnalysis struct {
	Event     *VflEvent
	SAScore   int
	SAMax     int
	SAPct     int
	OU15Odds  float64
	SweetSpot bool
	FP11      bool
	ShouldBet bool
	SkipReason string
	Verdict   string
	MarketOdds map[string]float64
}

func (e *Executor) analyzeEvent(raw []byte, ev *VflEvent) *EventAnalysis {
	// Parse the event detail JSON
	var detail struct {
		Data struct {
			Markets []struct {
				ID        int    `json:"id"`
				Name      string `json:"name"`
				Specifier string `json:"specifier,omitempty"`
				Outcomes  []struct {
					Description string  `json:"description"`
					Odds        string  `json:"odds"`
					ID          string  `json:"id"`
					IsActive    int     `json:"isActive"`
				} `json:"outcomes"`
			} `json:"markets"`
			Status int `json:"status"`
		} `json:"data"`
	}

	if err := json.Unmarshal(raw, &detail); err != nil {
		return &EventAnalysis{Event: ev, ShouldBet: false, SkipReason: fmt.Sprintf("parse error: %v", err)}
	}

	if detail.Data.Status != 0 {
		return &EventAnalysis{Event: ev, ShouldBet: false, SkipReason: "not prematch"}
	}

	// Extract market odds
	var o15, o25, homeO05, awayO05, gg, fhO05 float64
	var _, _ = "", ""

	for _, m := range detail.Data.Markets {
		for _, o := range m.Outcomes {
			if o.IsActive != 1 {
				continue
			}
			odds := parseOdds(o.Odds)
			if odds <= 0 {
				continue
			}

			switch m.ID {
			case 18:
				if o.Description == "Over 1.5" {
					o15 = odds
					_ = o.ID
					_ = "total=1.5"
				} else if o.Description == "Over 2.5" {
					o25 = odds
				}
			case 19:
				if o.Description == "Over 0.5" {
					homeO05 = odds
				}
			case 20:
				if o.Description == "Over 0.5" {
					awayO05 = odds
				}
			case 29:
				if o.Description == "Yes" {
					gg = odds
				}
			case 68:
				if o.Description == "Over 0.5" {
					fhO05 = odds
				}
			}
		}
	}

	// Compute Section A score (odds-based, same as Python Onimix engine)
	sa := 0
	if o15 > 0 {
		if o15 <= 1.60 {
			sa += 3
		} else if o15 <= 1.80 {
			sa += 1
		}
	}
	if o25 > 0 {
		if o25 <= 2.20 {
			sa += 2
		} else if o25 <= 2.80 {
			sa += 1
		}
	}
	if homeO05 > 0 {
		if homeO05 <= 1.40 {
			sa += 2
		} else if homeO05 <= 1.60 {
			sa += 1
		}
	}
	if awayO05 > 0 {
		if awayO05 <= 1.40 {
			sa += 2
		} else if awayO05 <= 1.60 {
			sa += 1
		}
	}
	if gg > 0 {
		if gg <= 1.80 {
			sa += 2
		} else if gg <= 2.20 {
			sa += 1
		}
	}
	if fhO05 > 0 {
		if fhO05 <= 1.50 {
			sa += 2
		} else if fhO05 <= 1.70 {
			sa += 1
		}
	}

	sweet := o15 >= 1.38 && o15 <= 1.60
	saPct := sa * 100 / 13

	// Determine verdict
	verdict := "SKIP"
	shouldBet := false
	skipReason := ""

	if sa >= 10 && sweet {
		verdict = "LOCK"
		shouldBet = true
	} else if sa >= 8 && sweet {
		verdict = "PICK"
		shouldBet = true
	} else if sa >= 6 {
		verdict = "CONSIDER"
		shouldBet = false
		skipReason = "below PICK threshold"
	} else {
		skipReason = fmt.Sprintf("SA=%d/13 too low", sa)
	}

	if !sweet && sa >= 8 {
		skipReason = "outside sweet spot"
		shouldBet = false
	}

	return &EventAnalysis{
		Event:     ev,
		SAScore:   sa,
		SAMax:     13,
		SAPct:     saPct,
		OU15Odds:  o15,
		SweetSpot: sweet,
		ShouldBet: shouldBet,
		SkipReason: skipReason,
		Verdict:   verdict,
		MarketOdds: map[string]float64{
			"o15": o15, "o25": o25,
			"homeO05": homeO05, "awayO05": awayO05,
			"gg": gg, "fhO05": fhO05,
		},
	}
}

func (e *Executor) executeBet(analysis *EventAnalysis) {
	// Use stored outcome ID and specifier from the analysis
	// For now, use a test bet with minimum stake
	resp, err := e.client.PlaceBet(
		true,
		10.0,                                        // min stake
		analysis.OU15Odds,                            // odds
		analysis.Event.EventID,                       // event ID
		"total=1.5",                                  // specifier
		"12",                                         // outcome ID (Over 1.5)
		18,                                           // market ID (O/U)
	)

	if err != nil {
		log.Printf("BET FAILED: %s vs %s: %v", analysis.Event.HomeTeam, analysis.Event.AwayTeam, err)
		return
	}

	if resp.IsSuccess() {
		log.Printf("✅ BET PLACED: %s vs %s @%.2f | bizCode=%d",
			analysis.Event.HomeTeam, analysis.Event.AwayTeam, analysis.OU15Odds, resp.BizCode)
	} else {
		log.Printf("❌ BET REJECTED: %s vs %s | %s",
			analysis.Event.HomeTeam, analysis.Event.AwayTeam, resp.String())
	}
}

func parseOdds(s string) float64 {
	var v float64
	fmt.Sscanf(s, "%f", &v)
	return v
}
