#!/usr/bin/env python3
import sqlite3
import math
import logging
from pathlib import Path

logger = logging.getLogger("[WIN_QUOTA]")

RESULTS_DB = Path("/home/ubuntu/faith-workspace/vfl-complete-data/databases/vfl_results.db")

# Historical Win Distribution (Avg Wins per Season)
# Based on analysis of ~82 seasons
HISTORICAL_QUOTAS = {
    "Manchester Blue": {"avg": 16.0, "min": 2, "max": 24, "std": 4.5},
    "Liverpool": {"avg": 15.7, "min": 3, "max": 22, "std": 4.2},
    "Manchester Red": {"avg": 15.6, "min": 2, "max": 21, "std": 4.0},
    "Chelsea": {"avg": 15.3, "min": 3, "max": 22, "std": 4.1},
    "London Guns": {"avg": 13.6, "min": 3, "max": 21, "std": 3.8},
    "Aston Villa": {"avg": 13.4, "min": 3, "max": 19, "std": 3.5},
    "Tottenham": {"avg": 12.9, "min": 2, "max": 21, "std": 3.7},
    "West Ham": {"avg": 10.5, "min": 4, "max": 16, "std": 3.0},
    "Everton": {"avg": 9.8, "min": 1, "max": 18, "std": 3.2},
    "Brighton": {"avg": 9.2, "min": 1, "max": 16, "std": 3.0},
    "Wolverhampton": {"avg": 9.1, "min": 0, "max": 14, "std": 2.8},
    "Newcastle": {"avg": 7.1, "min": 2, "max": 13, "std": 2.5},
    "Leeds": {"avg": 7.1, "min": 1, "max": 13, "std": 2.4},
    "Crystal Palace": {"avg": 6.6, "min": 2, "max": 11, "std": 2.2},
    "Fulham": {"avg": 6.4, "min": 2, "max": 12, "std": 2.1},
    "Bournemouth": {"avg": 6.0, "min": 1, "max": 13, "std": 2.3},
}

class WinQuotaAnalyst:
    def __init__(self):
        self.quotas = HISTORICAL_QUOTAS

    def calculate_win_pressure(self, team, current_wins, match_day):
        """
        Calculate win pressure score (-1.0 to +1.0).
        - Negative: Over-performing (Due for regression/loss)
        - Positive: Under-performing (Due for correction/win)
        """
        if team not in self.quotas:
            return 0.0
        
        q = self.quotas[team]
        avg_total = q["avg"]
        
        # Predicted wins by end of season based on current trajectory
        # trajectory_wins = (current_wins / match_day) * 30 if match_day > 0 else 0
        
        # Expected wins at current match day
        expected_at_md = (avg_total / 30.0) * match_day
        
        # Difference from expectation
        diff = expected_at_md - current_wins
        
        # Normalize by standard deviation (roughly)
        # Higher pressure late in the season
        phase_multiplier = (match_day / 30.0) ** 2  # Exponential pressure increase
        
        pressure = (diff / q["std"]) * phase_multiplier
        
        # Cap at [-1.0, 1.0]
        return max(-1.0, min(1.0, pressure))

    def get_quota_report(self, team, current_wins, match_day):
        pressure = self.calculate_win_pressure(team, current_wins, match_day)
        q = self.quotas.get(team, {})
        
        status = "NORMAL"
        if pressure < -0.5: status = "DANGEROUSLY OVER-PERFORMING (Regression Likely)"
        elif pressure < -0.2: status = "OVER-PERFORMING"
        elif pressure > 0.5: status = "UNDER-PERFORMING (Win Due)"
        elif pressure > 0.2: status = "SLIGHTLY UNDER-PERFORMING"
        
        return {
            "team": team,
            "current_wins": current_wins,
            "match_day": match_day,
            "avg_quota": q.get("avg"),
            "pressure_score": round(pressure, 3),
            "status": status
        }

if __name__ == "__main__":
    # Test Fulham MD25 scenario
    analyst = WinQuotaAnalyst()
    report = analyst.get_quota_report("Fulham", 5, 25)
    print(f"Scenario: Fulham MD25 with 5 wins")
    print(f"Pressure Score: {report['pressure_score']}")
    print(f"Status: {report['status']}")
    
    # Test Manchester Blue MD25 with 20 wins
    report = analyst.get_quota_report("Manchester Blue", 20, 25)
    print(f"\nScenario: Man Blue MD25 with 20 wins")
    print(f"Pressure Score: {report['pressure_score']}")
    print(f"Status: {report['status']}")
