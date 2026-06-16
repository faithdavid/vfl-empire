#!/usr/bin/env python3
"""
predictive_consistency_model.py

ACADEMIC RNG ANALYSIS FRAMEWORK: ODDS PREDICTIVE CONSISTENCY AND CALIBRATION

This script evaluates the mathematical and logical consistency of correct-score probability sequences. It builds
a multivariate autoregressive model that predicts the "shape" of the probability distribution for the next snapshot
based on historical lags. The script computes out-of-sample prediction error, multi-class Brier Scores (against simulated
outcomes generated from the distributions), and the Expected Calibration Error (ECE) with corresponding calibration curves.

References:
1. Brier, G. W. (1950). "Verification of forecasts expressed in terms of probability." Monthly Weather Review, 78(1), 1-3.
2. Guo, C., Pleiss, G., Sun, Y., and Weinberger, K. Q. (2017). "On calibration of modern neural networks." ICML 2017.
"""

import numpy as np
from typing import Dict, Any, List, Tuple

class PredictiveConsistencyModel:
    """
    Fits statistical models to correct-score probability vectors to test internal consistency and out-of-sample calibration.
    """
    
    def __init__(self, data: np.ndarray, lag: int = 1):
        """
        Args:
            data: NumPy array of shape (N, 31) representing correct score probability sequences.
            lag: Autoregressive lag dimension.
        """
        self.data = data
        self.lag = lag
        self.N, self.C = data.shape
        
    def prepare_dataset(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Constructs the feature matrix X (autoregressive lags) and target matrix Y.
        
        Returns:
            X: Matrix of shape (N - lag, lag * 31).
            Y: Target matrix of shape (N - lag, 31).
        """
        X_list, Y_list = [], []
        for i in range(self.N - self.lag):
            lag_features = self.data[i : i + self.lag].flatten()
            X_list.append(lag_features)
            Y_list.append(self.data[i + self.lag])
            
        return np.array(X_list), np.array(Y_list)

    def train_test_split(self, X: np.ndarray, Y: np.ndarray, train_ratio: float = 0.8) -> Tuple[Tuple[np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray]]:
        """
        Splits dataset into training (80%) and testing (20%) sets sequentially.
        
        Args:
            X: Feature matrix.
            Y: Target matrix.
            train_ratio: Proportion of training data.
            
        Returns:
            Splits: ((X_train, Y_train), (X_test, Y_test)).
        """
        split_idx = int(len(X) * train_ratio)
        return (X[:split_idx], Y[:split_idx]), (X[split_idx:], Y[split_idx:])

    def fit_ridge_regression(self, X_train: np.ndarray, Y_train: np.ndarray, alpha: float = 1.0) -> np.ndarray:
        """
        Fits a multivariate Ridge regression model analytically.
        Formula: W = (X^T * X + alpha * I)^-1 * X^T * Y
        
        Args:
            X_train: Features training set.
            Y_train: Target training set.
            alpha: L2 regularization weight.
            
        Returns:
            W: Weight matrix of shape (lag * 31, 31).
        """
        n_features = X_train.shape[1]
        I = np.identity(n_features)
        W = np.linalg.solve(X_train.T @ X_train + alpha * I, X_train.T @ Y_train)
        return W

    def predict(self, X_test: np.ndarray, W: np.ndarray) -> np.ndarray:
        """
        Predicts next-step correct-score probabilities and ensures normalization.
        
        Args:
            X_test: Test features.
            W: Fitted weights.
            
        Returns:
            P_pred: Normalized predictions of shape (N_test, 31).
        """
        preds = X_test @ W
        # Standard projection: clip negative values and re-normalize to 1.0
        preds_clipped = np.clip(preds, 1e-12, None)
        row_sums = np.sum(preds_clipped, axis=1, keepdims=True)
        return preds_clipped / row_sums

    def simulate_outcomes(self, p_true: np.ndarray) -> np.ndarray:
        """
        Simulates actual discrete binary outcomes from the true probability vectors.
        This provides the target outcomes to compute multi-class Brier and ECE scores.
        
        Args:
            p_true: Multi-class probabilities of shape (N_test, 31).
            
        Returns:
            Y_onehot: Binary binary indicators of shape (N_test, 31) with exactly one 1 per row.
        """
        N_test, C = p_true.shape
        Y_onehot = np.zeros_like(p_true)
        for i in range(N_test):
            # Sample index from category probabilities
            outcome_idx = np.random.choice(C, p=p_true[i])
            Y_onehot[i, outcome_idx] = 1.0
        return Y_onehot

    def compute_brier_score(self, p_pred: np.ndarray, y_true: np.ndarray) -> float:
        """
        Computes the Multi-Class Brier Score.
        Formula: BS = (1 / N) * sum_i(sum_j( (p_pred_{i, j} - y_true_{i, j})^2 ))
        
        Args:
            p_pred: Predicted probabilities.
            y_true: Simulated one-hot outcomes.
            
        Returns:
            Mean Brier score (lower is better, bounds are [0, 2.0]).
        """
        return float(np.mean(np.sum((p_pred - y_true)**2, axis=1)))

    def compute_expected_calibration_error(self, p_pred: np.ndarray, y_true: np.ndarray, num_bins: int = 5) -> Tuple[float, List[Dict[str, float]]]:
        """
        Computes the Expected Calibration Error (ECE) for multi-class probability forecasts.
        
        Args:
            p_pred: Predicted probabilities.
            y_true: Simulated one-hot outcomes.
            num_bins: Number of confidence intervals.
            
        Returns:
            A tuple of (ece_metric, bin_details_list).
        """
        N_test, C = p_pred.shape
        # Flatten probabilities and outcomes to compute calibration across all outcomes
        p_flat = p_pred.flatten()
        y_flat = y_true.flatten()
        
        bin_edges = np.linspace(0.0, 1.0, num_bins + 1)
        ece = 0.0
        bin_details = []
        
        for b in range(num_bins):
            low = bin_edges[b]
            high = bin_edges[b+1]
            
            # Select elements falling within bin interval
            in_bin = (p_flat >= low) & (p_flat < high) if b < num_bins - 1 else (p_flat >= low) & (p_flat <= high)
            bin_size = np.sum(in_bin)
            
            if bin_size > 0:
                avg_confidence = float(np.mean(p_flat[in_bin]))
                avg_accuracy = float(np.mean(y_flat[in_bin]))
                
                # Weight by bin size ratio
                weight = bin_size / len(p_flat)
                ece += weight * abs(avg_accuracy - avg_confidence)
                
                bin_details.append({
                    "bin": b + 1,
                    "range": [low, high],
                    "count": int(bin_size),
                    "confidence": avg_confidence,
                    "accuracy": avg_accuracy
                })
                
        return float(ece), bin_details


def run_predictive_analysis(data: np.ndarray) -> Dict[str, Any]:
    """
    Central function to fit, test, and score predictive consistency of probability snapshots.
    
    Args:
        data: Matrix of CS probabilities of shape (N, 31).
        
    Returns:
        A dictionary containing weight statistics, out-of-sample errors, and calibration scores.
    """
    model = PredictiveConsistencyModel(data, lag=1)
    X, Y = model.prepare_dataset()
    (X_train, Y_train), (X_test, Y_test) = model.train_test_split(X, Y)
    
    # Fit
    W = model.fit_ridge_regression(X_train, Y_train, alpha=1.0)
    
    # Predict
    P_pred = model.predict(X_test, W)
    
    # Simulate outcomes based on true test data
    np.random.seed(42)  # Ensure reproducibility of simulated outcomes
    Y_sim = model.simulate_outcomes(Y_test)
    
    # Evaluate
    mae = float(np.mean(np.abs(P_pred - Y_test)))
    brier = model.compute_brier_score(P_pred, Y_sim)
    ece, bins = model.compute_expected_calibration_error(P_pred, Y_sim)
    
    # Baseline comparison: predicting flat uniform distribution
    uniform_pred = np.ones_like(P_pred) / 31.0
    uniform_brier = model.compute_brier_score(uniform_pred, Y_sim)
    
    # Consistency verdict
    # Good model should beat uniform baseline and have low expected calibration error (< 5%)
    verdict = "Odds Show High Predictive and Calibration Consistency" if ece < 0.05 and brier < uniform_brier else "Inconsistencies or Dynamic Structural Shifts Detected"
    
    return {
        "out_of_sample_mae": mae,
        "brier_score": brier,
        "uniform_baseline_brier": uniform_brier,
        "expected_calibration_error_ece": ece,
        "bin_details": bins,
        "consistency_verdict": verdict
    }


if __name__ == "__main__":
    print("=== SCRIPT 4: PREDICTIVE CONSISTENCY MODEL (Academic RNG Framework) ===")
    
    # Import SCRIPT 1 generator to produce test data
    from distribution_fingerprint import generate_synthetic_cs_data
    
    print("Generating synthetic correct-score probabilities (1000 snapshots)...")
    synthetic_data = generate_synthetic_cs_data(1000)
    
    print("Running predictive consistency and calibration analysis...")
    results = run_predictive_analysis(synthetic_data)
    
    print("\n[OUT-OF-SAMPLE PERFORMANCE AND CALIBRATION]")
    print(f"Mean Absolute Error (on probabilities): {results['out_of_sample_mae']:.6f}")
    print(f"Multi-Class Brier Score: {results['brier_score']:.6f}")
    print(f"Uniform Baseline Brier Score: {results['uniform_baseline_brier']:.6f}")
    print(f"Expected Calibration Error (ECE): {results['expected_calibration_error_ece']:.4%}")
    print(f"Verdict: {results['consistency_verdict']}")
    
    print("\n[CALIBRATION CURVE BIN DETAILS]")
    for b in results['bin_details']:
        print(f"  Bin {b['bin']} [{b['range'][0]:.2f} - {b['range'][1]:.2f}]: count = {b['count']}, Avg Confidence = {b['confidence']:.4%}, Avg Empirical Accuracy = {b['accuracy']:.4%}")
