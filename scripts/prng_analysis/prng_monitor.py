#!/usr/bin/env python3
"""
prng_monitor.py

ACADEMIC RNG ANALYSIS FRAMEWORK: BATCH MONITORING AND DRIFT DETECTION

This script combines all four statistical, dynamical systems, lattice, and predictive models into a continuous
monitoring pipeline. It loads historical/current snapshots of correct-score distributions, divides them into temporal
sequential batches (rolling windows), and executes the comprehensive analytical suite on each block.
It compares successive statistical profiles to detect drifts, shifts, or changes in the game engine parameters
(such as game-engine updates or RNG revisions) and generates a structured statistical markdown report.
"""

import os
import sys
import json
import math
import numpy as np
from typing import Dict, Any, List, Tuple

# Ensure scripts directory is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from distribution_fingerprint import run_comprehensive_fingerprint, SCORES_31
from state_space_analyzer import run_state_space_analysis
from lattice_dimension_test import run_lattice_test
from predictive_consistency_model import run_predictive_analysis

class PRNGMonitor:
    """
    Rolling-window statistical monitor and drift detector for virtual football correct-score distributions.
    """
    
    def __init__(self, data: np.ndarray, batch_size: int = 250):
        """
        Args:
            data: NumPy array of shape (N, 31) containing historical CS probabilities.
            batch_size: Window size for each rolling evaluation batch.
        """
        self.data = data
        self.batch_size = batch_size
        self.N, self.C = data.shape
        self.num_batches = self.N // batch_size
        
    def execute_pipeline(self) -> List[Dict[str, Any]]:
        """
        Runs the full 4-script statistical analysis pipeline over all sequential batches.
        
        Returns:
            A list of dictionary profiles for each batch.
        """
        batch_profiles = []
        
        for b in range(self.num_batches):
            start_idx = b * self.batch_size
            end_idx = start_idx + self.batch_size
            batch_data = self.data[start_idx:end_idx]
            
            print(f"Processing Batch {b + 1}/{self.num_batches} (Indices: {start_idx} to {end_idx})...")
            
            # SCRIPT 1: Statistical Fingerprinting
            fingerprint = run_comprehensive_fingerprint(batch_data)
            
            # Extract Entropy series for dynamical and lattice tests
            # We compute entropy of each row in the batch
            entropies = np.array([-np.sum(row[row > 0] * np.log2(row[row > 0])) for row in batch_data])
            
            # SCRIPT 2: State Space Dynamical Analysis
            dynamical_profile = run_state_space_analysis(entropies)
            
            # SCRIPT 3: Lattice Dimension Test
            lattice_profile = run_lattice_test(entropies, dimension=5)
            
            # SCRIPT 4: Predictive Consistency & Calibration
            predictive_profile = run_predictive_analysis(batch_data)
            
            # Consolidate Batch Profile
            profile = {
                "batch_id": b + 1,
                "range": [start_idx, end_idx],
                "fingerprint": fingerprint,
                "dynamical": dynamical_profile,
                "lattice": lattice_profile,
                "predictive": predictive_profile
            }
            batch_profiles.append(profile)
            
        return batch_profiles

    def detect_drift_and_anomalies(self, profiles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyzes consecutive batch profiles to detect statistically significant drifts or shifts.
        
        Args:
            profiles: List of consolidated batch profiles.
            
        Returns:
            A list of flagged warnings/anomalies found.
        """
        alerts = []
        if len(profiles) < 2:
            return alerts
            
        for i in range(1, len(profiles)):
            prev = profiles[i - 1]
            curr = profiles[i]
            
            # Drift Check 1: Shannon Entropy shift (> 3x standard deviation of the previous batch)
            entropy_shift = abs(curr["fingerprint"]["mean_entropy"] - prev["fingerprint"]["mean_entropy"])
            prev_std = prev["fingerprint"]["std_entropy"]
            if entropy_shift > 3 * prev_std:
                alerts.append({
                    "batch": curr["batch_id"],
                    "severity": "CRITICAL",
                    "metric": "Entropy Drift",
                    "details": f"Mean Entropy shifted by {entropy_shift:.4f} bits (previous batch standard deviation: {prev_std:.4f}). This represents a massive change in game uncertainty."
                })
                
            # Drift Check 2: Transition of best parametric distribution model
            if curr["fingerprint"]["best_fit_model"] != prev["fingerprint"]["best_fit_model"]:
                alerts.append({
                    "batch": curr["batch_id"],
                    "severity": "WARNING",
                    "metric": "Distribution Family Shift",
                    "details": f"Fitted distribution family changed from '{prev['fingerprint']['best_fit_model']}' to '{curr['fingerprint']['best_fit_model']}'. This indicates a potential game engine algorithm swap."
                })
                
            # Drift Check 3: Large rise in Expected Calibration Error (ECE)
            ece_diff = curr["predictive"]["expected_calibration_error_ece"] - prev["predictive"]["expected_calibration_error_ece"]
            if ece_diff > 0.03:  # Increase in calibration error > 3%
                alerts.append({
                    "batch": curr["batch_id"],
                    "severity": "WARNING",
                    "metric": "Calibration Degradation",
                    "details": f"Expected Calibration Error increased by {ece_diff:.2%}. The odds distributions are losing predictive consistency against actual outcomes."
                })
                
            # Drift Check 4: LLE Lyapunov Exponent Sign Change (transition to chaos or periodic cycles)
            prev_lle = prev["dynamical"]["largest_lyapunov_exponent_lle"]
            curr_lle = curr["dynamical"]["largest_lyapunov_exponent_lle"]
            if (prev_lle > 0 and curr_lle <= 0) or (prev_lle <= 0 and curr_lle > 0):
                alerts.append({
                    "batch": curr["batch_id"],
                    "severity": "HIGH",
                    "metric": "Phase Space Attractor Shift",
                    "details": f"Largest Lyapunov Exponent flipped sign (from {prev_lle:.4f} to {curr_lle:.4f}), signifying a structural state transition between chaotic and periodic sequence characteristics."
                })
                
        return alerts

    def generate_markdown_report(self, profiles: List[Dict[str, Any]], alerts: List[Dict[str, Any]]) -> str:
        """
        Compiles the comprehensive, premium-formatted markdown statistical analysis report.
        """
        report = []
        report.append("# Academic RNG Analysis Framework - Consolidated Statistical Report")
        report.append("\nThis report compiles the results of four distinct advanced analytical scripts evaluating virtual football odds distributions.")
        
        # Alerts/Warnings section
        report.append("\n## 🚨 SYSTEM MONITORS AND DRIFT ALERTS")
        if not alerts:
            report.append("\n> [!NOTE]\n> **ALL SYSTEMS NORMAL**: No statistically significant drifts, anomalies, or game-engine parameter changes detected between batches.")
        else:
            for alert in alerts:
                severity_badge = f"**[{alert['severity']}]**"
                report.append(f"\n> [!WARNING]\n> {severity_badge} **{alert['metric']} in Batch {alert['batch']}**\n> {alert['details']}")
                
        # Sequential summary of batches
        report.append("\n## 📊 BATCH-BY-BATCH STATISTICAL PROFILES")
        for p in profiles:
            report.append(f"\n### Batch {p['batch_id']} (Snapshots {p['range'][0]} to {p['range'][1]})")
            
            # SCRIPT 1 metrics
            fp = p["fingerprint"]
            report.append(f"- **Statistical Fingerprint**:")
            report.append(f"  - Mean Shannon Entropy: `{fp['mean_entropy']:.4f}` bits (std: `{fp['std_entropy']:.4f}`)")
            report.append(f"  - Parametric Family Fit: Best match is **{fp['best_fit_model']}**")
            report.append(f"  - Bivariate Poisson lambda Home: `{fp['bivariate_poisson']['lambda_home']:.4f}`, Away: `{fp['bivariate_poisson']['lambda_away']:.4f}`, Cov: `{fp['bivariate_poisson']['lambda_cov']:.4f}` (KL-Divergence: `{fp['bivariate_poisson']['kl_divergence']:.6f}`)")
            
            # NIST tests summary
            nist_ent = fp["nist_tests_entropy"]
            report.append(f"  - NIST SP 800-22 tests (Entropy series): Monobit: `{'PASS' if nist_ent['monobit']['passed'] else 'FAIL'}` (p={nist_ent['monobit']['p_value']:.4f}) | Runs: `{'PASS' if nist_ent['runs']['passed'] else 'FAIL'}` (p={nist_ent['runs']['p_value']:.4f}) | Spectral: `{'PASS' if nist_ent['spectral']['passed'] else 'FAIL'}` (p={nist_ent['spectral']['p_value']:.4f})")
            
            # SCRIPT 2 metrics
            dyn = p["dynamical"]
            report.append(f"- **State-Space Dynamics (Takens' Reconstruction)**:")
            report.append(f"  - Embedding dimension $m$: `{dyn['embedding_dimension_m']}`, Time delay $\\tau$: `{dyn['time_delay_tau']}`")
            report.append(f"  - Correlation Dimension $D_2$: `{dyn['correlation_dimension_d2']:.4f}`")
            report.append(f"  - Largest Lyapunov Exponent (LLE): `{dyn['largest_lyapunov_exponent_lle']:.4f}`")
            report.append(f"  - Recurrence Plot: RR = `{dyn['recurrence_rate_rr']:.4%}`, DET = `{dyn['determinism_det']:.4%}`")
            report.append(f"  - Verdict: *{dyn['determinism_verdict']}*")
            
            # SCRIPT 3 metrics
            lat = p["lattice"]
            report.append(f"- **Lattice Cryptanalysis (LLL reduction)**:")
            report.append(f"  - Observed Shortest Basis Vector Norm: `{lat['shortest_vector_norm']:.4f}`")
            report.append(f"  - Expected Gaussian Heuristic Bound: `{lat['gaussian_heuristic_bound']:.4f}`")
            report.append(f"  - Hidden Linearity Score: `{lat['hidden_linearity_score']:.4f}`")
            report.append(f"  - Verdict: *{lat['independence_verdict']}*")
            
            # SCRIPT 4 metrics
            pred = p["predictive"]
            report.append(f"- **Predictive Odds Consistency and Calibration**:")
            report.append(f"  - Out-of-sample Mean Absolute Error: `{pred['out_of_sample_mae']:.6f}`")
            report.append(f"  - Multi-class Brier Score: `{pred['brier_score']:.6f}` (vs Uniform baseline `{pred['uniform_baseline_brier']:.6f}`)")
            report.append(f"  - Expected Calibration Error (ECE): `{pred['expected_calibration_error_ece']:.4%}`")
            report.append(f"  - Verdict: *{pred['consistency_verdict']}*")
            report.append("\n---")
            
        return "\n".join(report)


def execute_monitoring_framework(data: np.ndarray, batch_size: int = 250) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Main orchestration function to run the monitoring pipeline.
    """
    monitor = PRNGMonitor(data, batch_size)
    profiles = monitor.execute_pipeline()
    alerts = monitor.detect_drift_and_anomalies(profiles)
    report = monitor.generate_markdown_report(profiles, alerts)
    return report, alerts


if __name__ == "__main__":
    print("=== SCRIPT 5: PRNG MONITOR PIPELINE (Academic RNG Framework) ===")
    from distribution_fingerprint import generate_synthetic_cs_data
    
    # Generate 1000 snapshots of synthetic data
    print("Generating rolling synthetic correct-score probabilities (1000 snapshots)...")
    synthetic_data = generate_synthetic_cs_data(1000)
    
    # Introduce an artificial engine shift in the last 250 snapshots to test drift detection!
    print("Injecting an artificial statistical drift/shift in the final batch to test alert triggers...")
    # Shift: drastically decrease Poisson rates (e.g. fewer goals, less entropy)
    fingerprinter = run_comprehensive_fingerprint(synthetic_data)
    for i in range(750, 1000):
        # Generate much lower-uncertainty probabilities (extreme 0-0/1-0 bias)
        l1, l2, l3 = 0.5, 0.4, 0.01
        row = []
        for h, a in [ (int(s.split('-')[0]), int(s.split('-')[1])) for s in SCORES_31 ]:
            v = np.exp(-(l1+l2+l3)) * (l1**h / math.factorial(h)) * (l2**a / math.factorial(a))
            row.append(v)
        row = np.array(row) / sum(row)
        synthetic_data[i] = row
        
    print("Executing batch monitoring loop...")
    report, alerts = execute_monitoring_framework(synthetic_data, batch_size=250)
    
    # Print summary report
    print("\n" + "="*60)
    print("PRNG MONITOR REPORT PREVIEW:")
    print("="*60)
    print("\n".join(report.split("\n")[:40]))  # Print first 40 lines
    print("...\n[Report truncated, written to file]")
    
    # Write report to markdown file in scripts folder
    report_path = "/home/ubuntu/faith-workspace/vfl-empire/scripts/prng_analysis/prng_monitoring_report.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nFull report written to: {report_path}")
