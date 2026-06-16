# Foundational Mathematics for Modeling Match Outcomes

When dealing with "related data" in football (where Home Goals and Away Goals are interdependent, and markets like Odd/Even, Over/Under, and Correct Score are all mathematically linked), the industry relies on a few core mathematical models. 

Here is the essential literature and the mathematical principles for preparing your data and deriving outputs.

## 1. The Dixon-Coles Model (The Industry Standard)
**Paper:** *Modelling Association Football Scores and Inefficiencies in the Football Betting Market* by Mark J. Dixon and Stuart G. Coles (1997).
*   **The Math:** It models Home and Away goals as independent Poisson distributions, but introduces a **dependency parameter ($\rho$)** to correct for the fact that low-scoring matches (0-0, 1-0, 0-1, 1-1) happen more frequently in reality than a pure Poisson model predicts.
*   **Data Prep:** You prepare two attack parameters (Home Attack, Away Attack) and two defense parameters (Home Defense, Away Defense).
*   **Deriving Output:** You use the equations to generate a full 2D probability matrix (a grid of 0-0 to 5-5). From this single matrix, you calculate the probability of *every* market:
    *   *Home Win* = Sum of probabilities where H > A.
    *   *Over 2.5* = Sum of probabilities where H + A > 2.
    *   *Odd/Even* = Sum of probabilities where (H + A) % 2 == 0.

## 2. Bivariate Poisson & Copula Models
**Paper:** *Bivariate Poisson regression models with applications to football* by Dimitris Karlis and Ioannis Ntzoufras (2003).
*   **The Math:** Instead of treating Home and Away goals as separate processes, Bivariate Poisson assumes both teams are influenced by a shared, hidden third variable (e.g., the pace of the game or the weather). 
*   **Advanced Level (Copulas):** When you want to link two completely different distributions (e.g., Team A's goals follow a Poisson distribution, but Team B's goals follow a Negative Binomial distribution), mathematicians use **Copulas** (like the Sklar's Theorem) to glue them together into a joint distribution.
*   **Data Prep:** You model the "covariance" (how often Team A scoring increases the chance of Team B scoring).

## 3. Markov Chains and State Transitions
**Paper:** *A Markov Chain Model for Football* by various authors (frequently used in live/in-play modeling).
*   **The Math:** Match outcomes are treated as a series of state transitions. A game starts at `[0,0]`. The probability of transitioning to `[1,0]` depends on the current state.
*   **Data Prep for VFL:** This is highly relevant to your `analyze_scoreline_table_xminus1.py` script. You treat the "Entering Rank" (e.g., H12 vs A1) as the initial state, and map the transition probabilities to the final Scoreline state. 

## 4. Bayesian Inference and Elo Ratings
**Paper:** *A comprehensive review of the Elo rating system in sports* 
*   **The Math:** Elo is a zero-sum rating system. When Team A beats Team B, Team A takes points from Team B. The number of points exchanged depends on the expected outcome.
*   **Deriving Output:** You convert the difference in Elo ratings between two teams directly into a probability using a logistic curve: $P(A) = 1 / (1 + 10^{(R_B - R_A)/400})$.

---

### How to Prep Your VFL Data Based on These Papers

To build models that output EV, you must structure your database away from "flat results" and into **Probability Mass Functions (PMFs)**:

1.  **Calculate Expected Goals (lambda $\lambda$)**: For every team, calculate $\lambda_{attack}$ and $\lambda_{defense}$. 
2.  **Generate the Bivariate Matrix**: For a fixture (e.g., London Guns vs Liverpool), multiply their parameters to get $\lambda_{home}$ and $\lambda_{away}$. Generate a 10x10 grid of probabilities for every scoreline (0-0 to 9-9).
3.  **Apply the Dependency Correction**: Apply the Dixon-Coles $\rho$ parameter to inflate the probabilities of 0-0 and 1-1 (because VFL algorithms likely mimic real-life under-dispersion).
4.  **Collapse the Matrix into Prices**: 
    *   Sum the grid to find your true Over 2.5 probability.
    *   Convert probability to True Odds ($1 / P$).
    *   Compare True Odds vs MSport Odds to find EV.
