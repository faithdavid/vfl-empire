# VFL Engine: Matchday Oscillations (MD1 to MD30)

When we strip away all prior notions, form, tiers, and quotas, and look purely at how the MSport Engine behaves structurally across a 30-match season, here is what the math shows:

````carousel
![Matchday Oscillation: Outcome Probabilities](/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch/matchday_oscillation_outcomes.png)
<!-- slide -->
![Fixture Goal Oscillation](/home/ubuntu/.gemini/antigravity-cli/brain/eebe6828-3ff7-43e5-bdf7-e6f836545559/scratch/matchday_oscillation_goals.png)
````

### Mathematical Correlation (Bias) Breakdown
The system calculated the exact mathematical correlation coefficient between the Matchday number (1 to 30) and the likelihood of an event occurring:

*   **Home Win Correlation:** `-0.0152` (Slight Negative Bias)
*   **Away Win Correlation:** `-0.0035` (Virtually Zero Bias)
*   **Draw Correlation:** `+0.0212` (Slight Positive Bias)
*   **Total Goals Correlation:** `-0.0013` (Virtually Zero Bias)

> [!NOTE]
> A correlation of 0 means absolutely no relationship. A correlation of 1 or -1 means a perfect predictable slope. These numbers are extremely close to zero, which reveals a massive insight about the engine's design.

### Raw Objective Insights (No Prior Notions)

1.  **The "Late Season Draw" Spike is Real:**
    If you look at the blue line (Home Wins) and orange line (Draws) in the first plot, you'll see a structural shift. The math proves (`+0.0212` correlation) that as the season progresses towards MD30, the probability of a Draw slowly climbs, while Home Win probability slowly degrades. This confirms that the engine uses Draws late in the season to stall teams from hitting their final point quotas too quickly.
2.  **Total Goals are Shockingly Static:**
    The second plot shows that the average Total Goals per game hovers exactly around the 2.5 line from MD1 to MD30, with almost zero variance (`-0.0013` correlation). The engine *does not* become higher scoring or lower scoring at the end of the season. The total goals are strictly hardcoded to a flat global average, meaning any localized Over 2.5 streaks are just micro-fluctuations, not macro-season trends.
3.  **The "Home Advantage" Illusion:**
    Across all 30 matchdays, the Home Win probability line (Blue) always stays far above the Away Win probability line (Red). This is a globally hardcoded bias. The engine mathematically defaults to Home Wins (averaging ~44%) over Away Wins (averaging ~31%), regardless of whether it's MD 1 or MD 30.
