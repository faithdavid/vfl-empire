#!/usr/bin/env python3
"""
lattice_dimension_test.py

ACADEMIC RNG ANALYSIS FRAMEWORK: LATTICE-BASED LINEAR DEPENDENCY TESTING

This script implements lattice-based cryptanalytic tests to detect hidden linear relations or modular congruences
within correct-score probability sequences. It constructs a multi-dimensional lattice from consecutive snapshots,
applies the Lenstra-Lenstra-Lovász (LLL) lattice basis reduction algorithm (with an optimized pure-Python
implementation as a robust fallback for compiled C++ fpylll libraries), and evaluates the shortest vector
against the theoretical Gaussian Heuristic bounds to compute a "Hidden Linearity Score".

References:
1. Lenstra, A. K., Lenstra, H. W., and Lovász, L. (1982). "Factoring polynomials with rational coefficients."
   Mathematische Annalen, 261(4), 515-534.
2. Stern, J. (1987). "Secret linear congruential generators are not cryptographically secure." FOCS 1987.
"""

import numpy as np
from typing import Dict, Any, List, Tuple

# Try to import fpylll for native execution speed; fall back to pure-Python LLL if unavailable
HAS_FPYLLL = False
try:
    from fpylll import IntegerMatrix, LLL
    HAS_FPYLLL = True
except ImportError:
    pass

def gram_schmidt(B: List[List[float]]) -> Tuple[List[List[float]], List[List[float]]]:
    """
    Computes the Gram-Schmidt orthogonalization of a basis B.
    
    Args:
        B: Basis vectors (list of float lists).
        
    Returns:
        A tuple of (B_star, mu) where B_star is the orthogonal basis and mu contains coefficients.
    """
    n = len(B)
    m = len(B[0])
    B_star = [[0.0] * m for _ in range(n)]
    mu = [[0.0] * n for _ in range(n)]
    
    for i in range(n):
        B_star[i] = list(B[i])
        for j in range(i):
            num = sum(B[i][k] * B_star[j][k] for k in range(m))
            den = sum(B_star[j][k]**2 for k in range(m))
            if den > 1e-12:
                mu[i][j] = num / den
            else:
                mu[i][j] = 0.0
            for k in range(m):
                B_star[i][k] -= mu[i][j] * B_star[j][k]
    return B_star, mu

def pure_python_lll(B: List[List[float]], delta: float = 0.75) -> List[List[float]]:
    """
    Pure-Python implementation of the Lenstra-Lenstra-Lovász (LLL) lattice reduction.
    Guarantees execution capability on environments lacking C++ toolchains or fpylll binaries.
    
    Args:
        B: Input lattice basis (list of lists representing row vectors).
        delta: Lovász parameter (typically in [0.25, 1.0], default 0.75).
        
    Returns:
        The reduced lattice basis as a list of lists.
    """
    n = len(B)
    m = len(B[0])
    # Work with float representations for numeric stability
    B_reduced = [list(map(float, row)) for row in B]
    B_star, mu = gram_schmidt(B_reduced)
    
    k = 1
    while k < n:
        # Size reduction
        for j in range(k - 1, -1, -1):
            if abs(mu[k][j]) > 0.5:
                q = round(mu[k][j])
                for col in range(m):
                    B_reduced[k][col] -= q * B_reduced[j][col]
                B_star, mu = gram_schmidt(B_reduced)
                
        # Lovász condition check
        norm_sq = lambda v: sum(x**2 for x in v)
        if norm_sq(B_star[k]) >= (delta - mu[k][k-1]**2) * norm_sq(B_star[k-1]):
            k += 1
        else:
            # Swap vectors
            B_reduced[k], B_reduced[k-1] = B_reduced[k-1], B_reduced[k]
            B_star, mu = gram_schmidt(B_reduced)
            k = max(k - 1, 1)
            
    return B_reduced

class LatticeDimensionTester:
    """
    Implements LLL lattice reduction techniques to test sequences for low-dimensional integer linear relations.
    """
    
    def __init__(self, use_native: bool = True):
        self.use_native = use_native and HAS_FPYLLL

    def construct_relation_lattice(self, vector: np.ndarray, scale: float = 1e6) -> List[List[float]]:
        """
        Constructs a lattice to check for integer linear relations: sum(a_i * x_i) ≈ q.
        Matrix shape is (d+1) x (d+1):
        [  1     0    ...    0    scale*x_1 ]
        [  0     1    ...    0    scale*x_2 ]
        [ ...   ...   ...   ...       ...   ]
        [  0     0    ...    1    scale*x_d ]
        [  0     0    ...    0    scale     ]
        
        Args:
            vector: Float array of values to test.
            scale: Scaling factor to convert floats to pseudo-integers.
            
        Returns:
            The basis matrix of the constructed lattice.
        """
        d = len(vector)
        matrix = []
        for i in range(d):
            row = [0.0] * (d + 1)
            row[i] = 1.0
            row[-1] = vector[i] * scale
            matrix.append(row)
        # Add modulus scaled vector row
        last_row = [0.0] * (d + 1)
        last_row[-1] = scale
        matrix.append(last_row)
        return matrix

    def run_reduction(self, B: List[List[float]]) -> List[List[float]]:
        """
        Applies LLL reduction to the basis using either native fpylll or pure-Python fallback.
        
        Args:
            B: Lattice basis.
            
        Returns:
            Reduced basis.
        """
        if self.use_native and HAS_FPYLLL:
            # Construct IntegerMatrix for fpylll
            # fpylll requires integers, so we round to nearest int
            n = len(B)
            m = len(B[0])
            M = IntegerMatrix(n, m)
            for i in range(n):
                for j in range(m):
                    M[i, j] = int(round(B[i][j]))
            LLL.reduction(M)
            return [[float(M[i, j]) for j in range(m)] for i in range(n)]
        else:
            return pure_python_lll(B)

    def evaluate_shortest_vector(self, B_reduced: List[List[float]], d: int) -> Tuple[float, float, float]:
        """
        Evaluates the shortest vector in the reduced basis against the Gaussian Heuristic.
        Gaussian Heuristic bound for lattice dimension N:
        GH(L) ≈ sqrt(N / (2 * pi * e)) * (det L) ^ (1/N)
        
        Args:
            B_reduced: LLL-reduced basis.
            d: Base vector dimension.
            
        Returns:
            A tuple of (shortest_vector_norm, gaussian_heuristic_bound, hidden_linearity_score).
        """
        # Shortest non-zero vector in the reduced basis (row 0)
        shortest_vector = B_reduced[0]
        obs_norm = float(np.linalg.norm(shortest_vector))
        
        # Calculate lattice determinant (product of GS diagonal or absolute determinant of basis)
        # For our relation lattice, the determinant is det(L) = scale (from diagonal properties)
        n = d + 1
        det_L = 1e6 # Determinant of our relation lattice is invariant and equals the scale factor
        gh_bound = float(np.sqrt(n / (2 * np.pi * np.e)) * (det_L ** (1.0 / n)))
        
        # Hidden Linearity Score: GH_bound / Observed_Norm
        # Large ratio (> 1.0 or high relative value) suggests vector is much shorter than expected for random lattices
        hl_score = float(gh_bound / (obs_norm + 1e-12))
        return obs_norm, gh_bound, hl_score


def run_lattice_test(probabilities: np.ndarray, dimension: int = 5) -> Dict[str, Any]:
    """
    Orchestrates the lattice-based hidden linearity test on a sequence.
    
    Args:
        probabilities: Time series of a probability feature (length N).
        dimension: Dimension d of the relation test.
        
    Returns:
        A dictionary of results including shortest vector details and linearity score.
    """
    if len(probabilities) < dimension:
        raise ValueError(f"Probabilities length ({len(probabilities)}) must be >= dimension ({dimension})")
        
    tester = LatticeDimensionTester()
    
    # Subsample consecutive observations to construct a test vector of size `dimension`
    test_vector = probabilities[:dimension]
    
    B = tester.construct_relation_lattice(test_vector, scale=1e6)
    B_reduced = tester.run_reduction(B)
    
    shortest_norm, gh_bound, hl_score = tester.evaluate_shortest_vector(B_reduced, dimension)
    
    # Verdict based on academic cryptanalytic thresholds
    if hl_score > 10.0:
        verdict = "HIGH CONFIDENCE: Strong Hidden Linearity Detected"
    elif hl_score > 3.0:
        verdict = "WARNING: Moderate Linear Dependencies Identified"
    else:
        verdict = "Lattice basis conforms to high-dimensional randomness"
        
    return {
        "using_fpylll": tester.use_native,
        "test_dimension": dimension,
        "shortest_vector": B_reduced[0],
        "shortest_vector_norm": shortest_norm,
        "gaussian_heuristic_bound": gh_bound,
        "hidden_linearity_score": hl_score,
        "independence_verdict": verdict
    }


if __name__ == "__main__":
    print("=== SCRIPT 3: LATTICE DIMENSION TEST (Academic RNG Framework) ===")
    
    # Generate high-structure linear data: LCG sequence normalized to [0, 1]
    # s_{i+1} = (1103515245 * s_i + 12345) % 2^31
    print("Generating synthetic highly structured sequence (Linear Congruential Generator)...")
    lcg_series = np.zeros(100)
    seed = 12345
    m = 2**31
    a = 1103515245
    c = 12345
    curr = seed
    for i in range(100):
        curr = (a * curr + c) % m
        lcg_series[i] = curr / float(m)
        
    # Generate random sequence for comparison
    print("Generating synthetic truly random sequence (white noise)...")
    np.random.seed(42)
    rand_series = np.random.uniform(0, 1, 100)
    
    print("\n--- RUNNING LATTICE TEST ON LINEAR CONGRUENTIAL GENERATOR ---")
    lcg_results = run_lattice_test(lcg_series, dimension=5)
    print(f"Lattice reduction using fpylll library: {lcg_results['using_fpylll']}")
    print(f"Dimension d: {lcg_results['test_dimension']}")
    print(f"Shortest Vector: {lcg_results['shortest_vector']}")
    print(f"Observed Shortest Norm: {lcg_results['shortest_vector_norm']:.4f}")
    print(f"Expected Gaussian Heuristic Bound: {lcg_results['gaussian_heuristic_bound']:.4f}")
    print(f"Hidden Linearity Score: {lcg_results['hidden_linearity_score']:.4f}")
    print(f"Verdict: {lcg_results['independence_verdict']}")
    
    print("\n--- RUNNING LATTICE TEST ON WHITE NOISE ---")
    rand_results = run_lattice_test(rand_series, dimension=5)
    print(f"Observed Shortest Norm: {rand_results['shortest_vector_norm']:.4f}")
    print(f"Expected Gaussian Heuristic Bound: {rand_results['gaussian_heuristic_bound']:.4f}")
    print(f"Hidden Linearity Score: {rand_results['hidden_linearity_score']:.4f}")
    print(f"Verdict: {rand_results['independence_verdict']}")
