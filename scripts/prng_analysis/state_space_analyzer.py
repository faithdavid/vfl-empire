#!/usr/bin/env python3
"""
state_space_analyzer.py

ACADEMIC RNG ANALYSIS FRAMEWORK: DYNAMICAL SYSTEMS AND CHAOS ANALYSIS

This script applies state-space reconstruction and dynamical systems analysis to the time series of implied
probabilities. It utilizes Takens' Embedding Theorem to reconstruct multi-dimensional phase spaces from a 1D
probability signal, and computes chaos-theoretic diagnostics: Correlation Dimension (Grassberger-Procaccia),
Largest Lyapunov Exponent (Rosenstein's algorithm), and Recurrence Quantitative Analysis (RQA).

References:
1. Takens, F. (1981). "Detecting strange attractors in turbulence." Dynamical Systems and Turbulence, 366-381.
2. Grassberger, P. and Procaccia, I. (1983). "Measuring the strangeness of strange attractors." Physica D, 9(1-2), 189-208.
3. Rosenstein, M. T., Collins, J. J., and De Luca, C. J. (1993). "A practical method for calculating largest
   Lyapunov exponents from small data sets." Physica D, 65(1-2), 117-134.
"""

import numpy as np
import scipy.stats as stats
import scipy.spatial.distance as dist
from typing import Dict, Any, List, Tuple

class StateSpaceAnalyzer:
    """
    Analyzes 1D time series using dynamical systems theory, phase space reconstruction, and chaos metrics.
    """
    
    def __init__(self, time_series: np.ndarray):
        self.series = (time_series - np.mean(time_series)) / (np.std(time_series) + 1e-12)
        self.N = len(self.series)

    def estimate_time_delay(self, max_delay: int = 50) -> int:
        """
        Estimates the optimal embedding time delay (tau) using the first zero-crossing or
        first local minimum of the autocorrelation function (ACF).
        
        Args:
            max_delay: Maximum delay to search.
            
        Returns:
            The estimated time delay tau (positive integer).
        """
        acf = np.zeros(max_delay)
        for t in range(max_delay):
            if self.N - t > 0:
                acf[t] = np.corrcoef(self.series[:self.N - t], self.series[t:])[0, 1]
            else:
                acf[t] = 0.0
                
        # Find first zero crossing or where ACF drops below e^-1 (~0.368)
        for t in range(1, max_delay):
            if acf[t] <= 0.368 or acf[t] <= 0.0:
                return t
        return 1

    def false_nearest_neighbors(self, tau: int, max_m: int = 8, r_tol: float = 15.0, a_tol: float = 2.0) -> int:
        """
        Determines the optimal embedding dimension (m) using the False Nearest Neighbors (FNN) algorithm.
        
        Args:
            tau: Time delay.
            max_m: Maximum embedding dimension to check.
            r_tol: Tolerance parameter for distance increase ratio.
            a_tol: Tolerance parameter for absolute distance comparison to attractor size.
            
        Returns:
            The optimal embedding dimension.
        """
        std_series = np.std(self.series)
        
        for m in range(1, max_m):
            # Reconstruct for dimension m
            pts_m = self.reconstruct_phase_space(m, tau)
            n_pts = len(pts_m)
            if n_pts < 10:
                return m
                
            # Distance matrix for dimension m
            dists = dist.squareform(dist.pdist(pts_m))
            np.fill_diagonal(dists, np.inf)
            
            false_neighbors_count = 0
            valid_points = 0
            
            for i in range(n_pts):
                # Find nearest neighbor index
                nn_idx = np.argmin(dists[i])
                d_m = dists[i, nn_idx]
                
                # Check if the projection in dimension m+1 is valid
                idx_mplus1_i = i + m * tau
                idx_mplus1_nn = nn_idx + m * tau
                
                if idx_mplus1_i < self.N and idx_mplus1_nn < self.N:
                    valid_points += 1
                    # Component difference in next dimension
                    diff_next = np.abs(self.series[idx_mplus1_i] - self.series[idx_mplus1_nn])
                    d_mplus1 = np.sqrt(d_m**2 + diff_next**2)
                    
                    # Condition 1: Distance increase ratio too large
                    cond1 = (diff_next / (d_m + 1e-12)) > r_tol
                    # Condition 2: Neighbor distance is close to the attractor size
                    cond2 = (d_mplus1 / (std_series + 1e-12)) > a_tol
                    
                    if cond1 or cond2:
                        false_neighbors_count += 1
                        
            if valid_points > 0:
                fnn_fraction = false_neighbors_count / valid_points
                if fnn_fraction < 0.05:  # standard threshold (less than 5% false neighbors)
                    return m
                    
        return 3  # Fallback to standard dimension

    def reconstruct_phase_space(self, m: int, tau: int) -> np.ndarray:
        """
        Reconstructs the multi-dimensional phase space using delay coordinates.
        Y_t = [x_t, x_{t+tau}, ..., x_{t+(m-1)*tau}]
        
        Args:
            m: Embedding dimension.
            tau: Time delay.
            
        Returns:
            A 2D array of shape (N - (m-1)*tau, m) of reconstructed states.
        """
        n_pts = self.N - (m - 1) * tau
        if n_pts <= 0:
            raise ValueError(f"Time series length {self.N} is too short for m={m}, tau={tau}")
            
        states = np.zeros((n_pts, m))
        for j in range(m):
            states[:, j] = self.series[j * tau : j * tau + n_pts]
        return states

    def estimate_correlation_dimension(self, m: int, tau: int, num_r: int = 15) -> float:
        """
        Estimates the Correlation Dimension (D2) via the Grassberger-Procaccia algorithm.
        
        Args:
            m: Embedding dimension.
            tau: Time delay.
            num_r: Number of thresholds to sample.
            
        Returns:
            Estimated correlation dimension (slope of log C(r) vs log r).
        """
        states = self.reconstruct_phase_space(m, tau)
        n_pts = len(states)
        if n_pts < 10:
            return 0.0
            
        # Compute pairwise Euclidean distances
        dists = dist.pdist(states)
        max_d = np.max(dists)
        min_d = np.min(dists[dists > 0]) if np.any(dists > 0) else 1e-4
        
        # Log-spaced r thresholds
        r_vals = np.logspace(np.log10(min_d + 1e-4), np.log10(max_d / 2.0), num_r)
        c_r = np.zeros(num_r)
        
        total_pairs = n_pts * (n_pts - 1) / 2.0
        for idx, r in enumerate(r_vals):
            c_r[idx] = np.sum(dists < r) / total_pairs
            
        # Find linear scaling region (filter out 0 and 1 probabilities to avoid log(0)/log(1))
        valid_idx = (c_r > 1e-4) & (c_r < 0.9)
        if np.sum(valid_idx) < 3:
            return 0.0
            
        log_r = np.log(r_vals[valid_idx])
        log_c = np.log(c_r[valid_idx])
        
        slope, _, _, _, _ = stats.linregress(log_r, log_c)
        return float(slope)

    def estimate_largest_lyapunov_exponent(self, m: int, tau: int, steps: int = 10, theiler_window: int = 10) -> float:
        """
        Estimates the Largest Lyapunov Exponent (LLE) using Rosenstein's algorithm.
        
        Args:
            m: Embedding dimension.
            tau: Time delay.
            steps: Number of forward propagation steps to track.
            theiler_window: Temporal distance constraint to exclude autocorrelated points.
            
        Returns:
            Largest Lyapunov exponent. Positive value indicates chaotic/sensitive behavior.
        """
        states = self.reconstruct_phase_space(m, tau)
        n_pts = len(states)
        if n_pts < steps + 20:
            return 0.0
            
        # Distance matrix
        dists = dist.squareform(dist.pdist(states))
        
        # Apply Theiler window by setting nearby diagonal elements to infinity
        for i in range(n_pts):
            start = max(0, i - theiler_window)
            end = min(n_pts, i + theiler_window + 1)
            dists[i, start:end] = np.inf
            
        # Find nearest neighbor for each point
        nn_indices = np.argmin(dists, axis=1)
        
        # Track divergence of trajectories
        divergence = np.zeros(steps)
        counts = np.zeros(steps)
        
        for k in range(steps):
            log_div_sum = 0.0
            pt_count = 0
            for i in range(n_pts):
                idx_i = i + k
                idx_nn = nn_indices[i] + k
                
                # Verify indices are within reconstructed space boundaries
                if idx_i < n_pts and idx_nn < n_pts:
                    d = np.linalg.norm(states[idx_i] - states[idx_nn])
                    if d > 0:
                        log_div_sum += np.log(d)
                        pt_count += 1
            if pt_count > 0:
                divergence[k] = log_div_sum / pt_count
                counts[k] = pt_count
                
        # Find the slope of the linear divergence region
        valid_steps = counts > 0
        if np.sum(valid_steps) < 3:
            return 0.0
            
        x_vals = np.arange(steps)[valid_steps]
        y_vals = divergence[valid_steps]
        
        slope, _, _, _, _ = stats.linregress(x_vals, y_vals)
        return float(slope)

    def recurrence_quantitative_analysis(self, m: int, tau: int, eps_fraction: float = 0.15) -> Dict[str, float]:
        """
        Performs Recurrence Quantitative Analysis (RQA) on the reconstructed phase space.
        
        Args:
            m: Embedding dimension.
            tau: Time delay.
            eps_fraction: Distance threshold multiplier (fraction of standard deviation).
            
        Returns:
            A dictionary containing RQA metrics: Recurrence Rate (RR) and Determinism (DET).
        """
        states = self.reconstruct_phase_space(m, tau)
        n_pts = len(states)
        if n_pts < 5:
            return {"recurrence_rate": 0.0, "determinism": 0.0}
            
        # Distance matrix
        dists = dist.squareform(dist.pdist(states))
        
        # Recurrence threshold
        eps = eps_fraction * np.std(dists)
        R = (dists < eps).astype(int)
        np.fill_diagonal(R, 0)  # Exclude identity line
        
        # Compute Recurrence Rate (RR)
        rr = float(np.sum(R)) / (n_pts * (n_pts - 1))
        
        # Compute Determinism (DET) by analyzing diagonal line lengths >= 2
        diag_lines = []
        # Check diagonals parallel to the main diagonal
        for d in range(1, n_pts - 1):
            diag = np.diagonal(R, offset=d)
            # Find run lengths of 1s in diagonal
            run_len = 0
            for val in diag:
                if val == 1:
                    run_len += 1
                else:
                    if run_len >= 2:
                        diag_lines.append(run_len)
                    run_len = 0
            if run_len >= 2:
                diag_lines.append(run_len)
                
        total_recurrences = np.sum(R)
        recurrences_in_lines = sum(diag_lines)
        det = float(recurrences_in_lines) / (total_recurrences + 1e-12)
        
        return {
            "recurrence_rate": rr,
            "determinism": min(det, 1.0)
        }


def run_state_space_analysis(time_series: np.ndarray) -> Dict[str, Any]:
    """
    Helper function to orchestrate state space analysis on a time series.
    
    Args:
        time_series: 1D sequence of probabilities or other signal.
        
    Returns:
        A dictionary containing state space reconstruction parameters and metrics.
    """
    analyzer = StateSpaceAnalyzer(time_series)
    tau = analyzer.estimate_time_delay()
    m = analyzer.false_nearest_neighbors(tau)
    
    d2 = analyzer.estimate_correlation_dimension(m, tau)
    lle = analyzer.estimate_largest_lyapunov_exponent(m, tau)
    rqa = analyzer.recurrence_quantitative_analysis(m, tau)
    
    # Verdict of determinism:
    # A chaotic/deterministic system has:
    # - Low fractional correlation dimension (D2) compared to embedding dimension
    # - Positive Largest Lyapunov Exponent (LLE)
    # - High determinism score (DET) in recurrence plot
    is_deterministic = rqa["determinism"] > 0.8 and d2 < float(m) - 0.5 and lle > 0.01
    verdict = "Deterministic Structure Detected" if is_deterministic else "Consistent with High-Dimensional Randomness"
    
    return {
        "time_delay_tau": tau,
        "embedding_dimension_m": m,
        "correlation_dimension_d2": d2,
        "largest_lyapunov_exponent_lle": lle,
        "recurrence_rate_rr": rqa["recurrence_rate"],
        "determinism_det": rqa["determinism"],
        "determinism_verdict": verdict
    }


if __name__ == "__main__":
    print("=== SCRIPT 2: STATE SPACE ANALYZER (Academic RNG Framework) ===")
    
    # Generate chaotic/deterministic test data (logistic map)
    # x_{t+1} = r * x_t * (1 - x_t)
    print("Generating synthetic deterministic chaotic data (Logistic Map)...")
    np.random.seed(42)
    logistic_series = np.zeros(800)
    logistic_series[0] = 0.4
    r = 3.9  # chaotic regime
    for i in range(1, len(logistic_series)):
        logistic_series[i] = r * logistic_series[i-1] * (1 - logistic_series[i-1])
        
    # Generate purely random time series for comparison
    print("Generating synthetic white noise data...")
    noise_series = np.random.uniform(0, 1, 800)
    
    print("\n--- ANALYZING LOGISTIC MAP (CHAOTIC DETERMINISTIC) ---")
    logistic_results = run_state_space_analysis(logistic_series)
    print(f"Time Delay (tau): {logistic_results['time_delay_tau']}")
    print(f"Embedding Dimension (m): {logistic_results['embedding_dimension_m']}")
    print(f"Correlation Dimension (D2): {logistic_results['correlation_dimension_d2']:.4f}")
    print(f"Largest Lyapunov Exponent (LLE): {logistic_results['largest_lyapunov_exponent_lle']:.4f}")
    print(f"Recurrence Rate (RR): {logistic_results['recurrence_rate_rr']:.4f}")
    print(f"Determinism Score (DET): {logistic_results['determinism_det']:.4f}")
    print(f"Verdict: {logistic_results['determinism_verdict']}")
    
    print("\n--- ANALYZING WHITE NOISE (RANDOM) ---")
    noise_results = run_state_space_analysis(noise_series)
    print(f"Time Delay (tau): {noise_results['time_delay_tau']}")
    print(f"Embedding Dimension (m): {noise_results['embedding_dimension_m']}")
    print(f"Correlation Dimension (D2): {noise_results['correlation_dimension_d2']:.4f}")
    print(f"Largest Lyapunov Exponent (LLE): {noise_results['largest_lyapunov_exponent_lle']:.4f}")
    print(f"Recurrence Rate (RR): {noise_results['recurrence_rate_rr']:.4f}")
    print(f"Determinism Score (DET): {noise_results['determinism_det']:.4f}")
    print(f"Verdict: {noise_results['determinism_verdict']}")
