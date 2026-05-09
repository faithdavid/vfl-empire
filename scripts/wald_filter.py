#!/usr/bin/env python3
"""
Wald Anti-Miss Filter — Screens every prediction through survivorship bias correction.
461 missed predictions analyzed → 15 anti-miss rules → applied before finalizing any pick.

Usage:
    from wald_filter import WaldFilter
    wf = WaldFilter()
    adjusted = wf.filter(home, away, odds_h, odds_d, odds_a, initial_prediction, confidence)

Returns adjusted (prediction, confidence, warnings) tuple.
"""

import json
import os
from typing import Dict, List, Tuple, Optional

class WaldFilter:
    """Apply survivorship-bias correction to VFL predictions."""
    
    # Trap teams with their miss rates and dominant patterns
    TRAP_TEAMS = {
        'Manchester Red':   {'miss_rate': 0.710, 'pattern': 'draw_surprise', 'draw_bias': 0.15},
        'Brighton':         {'miss_rate': 0.688, 'pattern': 'draw_machine', 'draw_bias': 0.25},
        'Everton':          {'miss_rate': 0.656, 'pattern': 'mixed', 'draw_bias': 0.15},
        'Tottenham':        {'miss_rate': 0.632, 'pattern': 'draw_surprise', 'draw_bias': 0.15},
        'Fulham':           {'miss_rate': 0.632, 'pattern': 'draw_specialist', 'draw_bias': 0.20},
        'West Ham':         {'miss_rate': 0.604, 'pattern': 'draw_surprise', 'draw_bias': 0.20},
    }
    
    # Teams that lose as home favorites most
    HOME_TRAP_TEAMS = {
        'Manchester Red': {'penalty': 0.20},
        'Everton': {'penalty': 0.15},
        'Aston Villa': {'penalty': 0.15},
    }
    
    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.warnings: List[str] = []
    
    def filter(self, home: str, away: str, 
               odds_h: float, odds_d: float, odds_a: float,
               prediction: str, confidence: float) -> Tuple[str, float, List[str]]:
        """
        Screen a prediction through all anti-miss rules.
        
        Returns:
            Tuple of (adjusted_prediction, adjusted_confidence, warnings_list)
        """
        self.warnings = []
        pred = prediction.upper()
        
        # Rule 1-3: DRAW SURPRISE check (home moderate fav, odds 1.5-3.0, draw odds < 3.5)
        if self._check_draw_surprise(home, away, odds_h, odds_d, odds_a, pred):
            self.warnings.append("DRAW_SURPRISE_RISK: Moderate favorite in draw-friendly odds range")
            if confidence > 60:
                confidence = 60
            # Shift toward DRAW
            if pred in ('H', 'A'):
                pred = 'D'
                confidence = min(confidence, 55)
                if self.verbose:
                    print(f"  ⚠️ Wald: DRAW SURPRISE — switched {prediction}→DRAW")
        
        # Rule 4: DRAW BROKEN — never predict DRAW when odds_d > 4.0
        if pred == 'D' and odds_d > 4.0:
            self.warnings.append("DRAW_BROKEN_RISK: Draw odds > 4.0, draw is unlikely to hold")
            # Switch to the match favorite
            fav = min([('H', odds_h), ('D', odds_d), ('A', odds_a)], key=lambda x: x[1])
            pred = fav[0]
            confidence = min(confidence, 50)
            if self.verbose:
                print(f"  ⚠️ Wald: DRAW BROKEN — odds_d={odds_d:.2f} > 4.0, switched to {pred}")
        
        # Rule 5: DRAW confidence cap — never exceed 60% on DRAW
        if pred == 'D' and confidence > 60:
            self.warnings.append("DRAW_CERTAINTY_CAP: Draw confidence capped at 60% (81% of broken draws were 60-80%)")
            confidence = 60
        
        # Rule 6: HOME bias in draw-uncertain matches
        if pred == 'D' and odds_h < odds_a:
            self.warnings.append("HOME_DRAW_BIAS: Home team stronger in draw-probable match — lean HOME")
            # Don't flip, but note it
            if self.verbose:
                print(f"  ℹ️ Wald: HOME team stronger in draw — keeping DRAW but noting home bias")
        
        # Rule 7-8: HOME FAVORITE LOSS — specific team traps
        if pred == 'H' and home in self.HOME_TRAP_TEAMS:
            trap = self.HOME_TRAP_TEAMS[home]
            if odds_h < 2.0:  # Only when they're actual favorites
                self.warnings.append(f"HOME_TRAP: {home} loses as home favorite ({int(trap['penalty']*100)}% miss rate)")
                confidence = confidence * (1 - trap['penalty'])
                if self.verbose:
                    print(f"  ⚠️ Wald: HOME TRAP — {home} home fav, conf reduced by {int(trap['penalty']*100)}%")
        
        # Rule 9: Heavy favorite discount
        if pred in ('H', 'A') and min(odds_h, odds_a) < 1.5:
            fav_odds = min(odds_h, odds_a)
            fav_team = home if odds_h < odds_a else away
            opp_team = away if odds_h < odds_a else home
            self.warnings.append(f"HEAVY_FAVORITE: {fav_team} at odds {fav_odds:.2f} — add upset discount")
            confidence = confidence * 0.85  # 15% confidence penalty
            if self.verbose:
                print(f"  ⚠️ Wald: HEAVY FAV — {fav_team} at {fav_odds:.2f}, confidence cut by 15%")
        
        # Rule 13: TRAP TEAM filter
        for team, info in self.TRAP_TEAMS.items():
            if team in (home, away):
                self.warnings.append(f"TRAP_TEAM: {team} involved ({int(info['miss_rate']*100)}% miss rate)")
                # Shift probability toward DRAW
                if info['draw_bias'] > 0 and pred in ('H', 'A'):
                    # Don't auto-flip to draw, but reduce confidence
                    confidence = confidence * (1 - info['draw_bias'] * 0.5)
                    if self.verbose:
                        print(f"  ⚠️ Wald: TRAP TEAM {team} — conf reduced (draw bias {int(info['draw_bias']*100)}%)")
        
        # Rule 15: Tight odds spread = high uncertainty
        spread = max(odds_h, odds_d, odds_a) - min(odds_h, odds_d, odds_a)
        if spread < 2.0:
            self.warnings.append(f"TIGHT_ODDS: Spread {spread:.2f} < 2.0 — high uncertainty")
            confidence = confidence * 0.9
        
        # Ensure confidence is in [0, 100]
        confidence = max(0, min(100, confidence))
        
        return pred, round(confidence, 1), self.warnings
    
    def _check_draw_surprise(self, home: str, away: str,
                              odds_h: float, odds_d: float, odds_a: float,
                              prediction: str) -> bool:
        """Check if this match has elevated DRAW SURPRISE risk."""
        pred = prediction.upper()
        
        # Only applies when we predict HOME or AWAY
        if pred not in ('H', 'A'):
            return False
        
        if pred == 'H':
            # HOME moderate favorite (1.5-3.0) + draw odds < 3.5
            if 1.5 <= odds_h <= 3.0 and odds_d < 3.5:
                return True
            # HOME heavy favorite but draw odds are suspiciously low
            if odds_h < 1.5 and odds_d < 3.0:
                return True
        elif pred == 'A':
            # AWAY moderate favorite (1.5-3.0) + draw odds < 3.5
            if 1.5 <= odds_a <= 3.0 and odds_d < 3.5:
                return True
            # AWAY heavy favorite but draw odds are suspiciously low
            if odds_a < 1.5 and odds_d < 3.0:
                return True
        
        return False
    
    def apply_batch(self, matches: List[Dict]) -> List[Dict]:
        """Apply filter to a batch of matches and return adjusted results."""
        results = []
        for m in matches:
            pred, conf, warns = self.filter(
                m['home'], m['away'],
                m['odds_h'], m['odds_d'], m['odds_a'],
                m.get('prediction', 'H'), m.get('confidence', 50)
            )
            results.append({
                **m,
                'adjusted_prediction': pred,
                'adjusted_confidence': conf,
                'warnings': warns,
                'changed': pred != m.get('prediction')
            })
        return results
    
    def backtest_from_ledger(self, ledger_path: str) -> dict:
        """
        Backtest the anti-miss filter against historical predictions.
        
        Returns improvement statistics.
        """
        with open(ledger_path) as f:
            ledger = json.load(f)
        
        predictions = [p for p in ledger.get('predictions', []) if p.get('settled')]
        
        original_correct = sum(1 for p in predictions if p.get('correct'))
        original_total = len(predictions)
        
        corrected = 0
        made_worse = 0
        no_change = 0
        
        for p in predictions:
            pred = p.get('prediction', '')
            actual = p.get('actual_outcome', '')
            conf = p.get('confidence', 50)
            
            if not pred or not actual:
                continue
            
            adj_pred, adj_conf, warns = self.filter(
                p.get('home', ''), p.get('away', ''),
                float(p.get('odds_h', 0) or 0),
                float(p.get('odds_d', 0) or 0),
                float(p.get('odds_a', 0) or 0),
                pred, conf
            )
            
            was_correct = pred == actual
            would_be_correct = adj_pred == actual
            
            if not was_correct and would_be_correct:
                corrected += 1
            elif was_correct and not would_be_correct:
                made_worse += 1
            else:
                no_change += 1
        
        return {
            'total': original_total,
            'original_correct': original_correct,
            'original_accuracy': f"{original_correct/original_total*100:.1f}%",
            'corrected_misses': corrected,
            'made_worse': made_worse,
            'new_correct': original_correct + corrected - made_worse,
            'new_accuracy': f"{(original_correct + corrected - made_worse)/original_total*100:.1f}%",
            'net_improvement': f"{((corrected - made_worse)/original_total*100):.1f}pp"
        }


if __name__ == '__main__':
    # Test against live ledger
    wf = WaldFilter(verbose=False)
    
    # Test the filter
    test_cases = [
        # (home, away, odds_h, odds_d, odds_a, prediction, confidence, expected_issue)
        ('Brighton', 'Chelsea', 2.5, 3.3, 2.8, 'H', 65),      # Draw surprise candidate
        ('Manchester Red', 'Everton', 1.4, 4.5, 7.0, 'H', 80), # Heavy fav + Man Red trap
        ('Fulham', 'Leeds', 2.8, 3.2, 2.5, 'D', 70),           # Draw broken candidate
        ('Liverpool', 'Crystal Palace', 1.6, 3.8, 5.5, 'A', 60), # Away fav
        ('Tottenham', 'Brighton', 1.9, 3.5, 4.0, 'H', 55),     # Two trap teams
    ]
    
    print("=== WALD FILTER TEST CASES ===")
    for h, a, oh, od, oa, pred, conf in test_cases:
        result_pred, result_conf, warns = wf.filter(h, a, oh, od, oa, pred, conf)
        status = "✅ CHANGED" if result_pred != pred else "═ KEPT"
        print(f"\n{h:20s} vs {a:20s}")
        print(f"  Original: {pred} @ {conf}%")
        print(f"  Adjusted: {result_pred} @ {result_conf}%  {status}")
        for w in warns:
            print(f"    ⚠️ {w}")
    
    # Backtest on live ledger
    print(f"\n\n=== BACKTEST ON LIVE LEDGER ===")
    result = wf.backtest_from_ledger('/home/faith/.hermes/cron/state/vfl_ledger.json')
    for k, v in result.items():
        print(f"  {k}: {v}")
