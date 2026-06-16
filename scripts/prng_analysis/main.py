#!/usr/bin/env python3
"""
main.py

ACADEMIC RNG ANALYSIS FRAMEWORK: CENTRAL ENTRY POINT AND ORCHESTRATOR

This is the central orchestrator for the academic PRNG and probability distribution analysis suite. It:
1. Generates 1000 snapshots of high-fidelity synthetic correct-score probabilities.
2. Injects a realistic engine parameter shift in the final batch (to demonstrate drift alerts).
3. Executes the full analytical pipeline: distribution fingerprinting, state-space dynamical analysis,
   lattice cryptanalysis, and predictive consistency scoring.
4. Outputs a premium, professional terminal report.
5. Saves a consolidated Markdown report to `/home/ubuntu/faith-workspace/vfl-empire/scripts/prng_analysis/prng_monitoring_report.md`.
"""

import os
import sys
import numpy as np

# Add current folder to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from distribution_fingerprint import generate_synthetic_cs_data
from prng_monitor import execute_monitoring_framework

def main():
    print("================================================================================")
    print("      ACADEMIC RNG ANALYSIS TOOLKIT FOR VIRTUAL FOOTBALL ODDS DATA")
    print("================================================================================\n")
    
    # 1. Dataset Generation
    print("[1/3] Generating synthetic correct-score probabilities (1000 snapshots)...")
    data = generate_synthetic_cs_data(1000)
    
    # 2. Injecting a Realistic Drift
    print("[2/3] Injecting artificial game-engine parameter shift in the final batch...")
    # Symmetrical 31 correct score outcomes
    from distribution_fingerprint import SCORES_31
    import math
    
    # Shift parameters: decrease goal rates to lower uncertainty and entropy
    l1, l2, l3 = 0.51, 0.42, 0.01
    for i in range(750, 1000):
        row = []
        for h, a in [ (int(s.split('-')[0]), int(s.split('-')[1])) for s in SCORES_31 ]:
            # Safe Bivariate Poisson PMF
            v = np.exp(-(l1+l2+l3)) * (l1**h / math.factorial(h)) * (l2**a / math.factorial(a))
            row.append(v)
        row = np.array(row) / sum(row)
        data[i] = row
        
    # 3. Pipeline Execution
    print("[3/3] Executing batch monitoring pipeline (batch_size = 250)...")
    report_md, alerts = execute_monitoring_framework(data, batch_size=250)
    
    # 4. Premium Console Outputs
    print("\n" + "="*80)
    print("                      CONSOLIDATED MONITORS AND ALERTS STATUS")
    print("="*80)
    if not alerts:
        print("  ✅ [ALL SYSTEMS NORMAL]: No statistically significant shifts detected.")
    else:
        print(f"  🚨 [ALERTS FLAGGED]: Detected {len(alerts)} system anomalies / parameter drifts!\n")
        for alert in alerts:
            badge = f"[{alert['severity']}]"
            print(f"  • {badge:<10} Batch {alert['batch']:<2} | Metric: {alert['metric']}")
            print(f"    Detail: {alert['details']}\n")
            
    print("="*80)
    print("                          EXECUTIVE BATCH SUMMARY")
    print("="*80)
    # Parse and display high-level metrics for each batch
    import re
    batches = re.split(r'### Batch ', report_md)[1:]
    for b_info in batches:
        lines = b_info.split("\n")
        title = lines[0].strip()
        print(f"\n⚡ Batch {title}:")
        
        # Pull key stats with simple regex / substring searches
        entropy = ""
        model = ""
        lle = ""
        hl_score = ""
        ece = ""
        brier = ""
        
        for l in lines:
            if "Mean Shannon Entropy" in l:
                entropy = re.search(r'`([\d\.]+)`', l).group(1)
            if "Parametric Family Fit" in l:
                model = re.search(r'\*\*([^*]+)\*\*', l).group(1)
            if "Largest Lyapunov Exponent" in l:
                lle = re.search(r'`([\-\d\.]+)`', l).group(1)
            if "Hidden Linearity Score" in l:
                hl_score = re.search(r'`([\d\.]+)`', l).group(1)
            if "Expected Calibration Error" in l:
                ece = re.search(r'`([\d\.\%]+)`', l).group(1)
            if "Multi-class Brier Score" in l:
                brier = re.search(r'`([\d\.]+)`', l).group(1)
                
        print(f"  • Uncertainty (Shannon Entropy)  : {entropy} bits")
        print(f"  • Dynamic Attractor (Lyapunov LLE): {lle}")
        print(f"  • Lattice Independence (LLL HL)  : {hl_score}")
        print(f"  • Predictive Calibration (ECE)   : {ece}")
        print(f"  • Implied Brier Score            : {brier}")
        print(f"  • Optimal Parametric Model       : {model}")
        
    print("\n" + "="*80)
    print("Report compiled successfully!")
    print(f"Full markdown report: /home/ubuntu/faith-workspace/vfl-empire/scripts/prng_analysis/prng_monitoring_report.md")
    print("================================================================================\n")

if __name__ == "__main__":
    main()
