Benchmark Analysis: System Optimization
=======================================

These sections interpret the parametric benchmark results, validating the system's architectural choices.

### 1. Evidence Retrieval: Contextual Saturation
**Figure X** plots the agent's verification performance against the number of retrieved documents ($k$).
As observed, the system reaches **Performance Saturation** at $k=25$. Increasing the context window to 50 or 100 documents yields negligible gains in accuracy while linearly increasing token costs and latency.
*   **Interpretation:** This "early saturation" is a direct indicator of the **high precision** of the offline hybrid index. By effectively filtering irrelevant noise *before* the LLM reasoning stage, the retrieval layer ensures that the top-25 results almost always contain the necessary "Needle in a Haystack."
*   **Design Decision:** Consequently, we fix $k=25$ as the optimal operating point, maximizing cost-efficiency without compromising recall.

### 2. Search Depth: Adaptive Reasoning
**Figure Y** illustrates the relationship between the Maximum Search Depth (allowed iterations) and the actual average cost.
Crucially, increasing the depth limit from 5 to 10 **does not** proportionally double the average latency.
*   **Interpretation:** This confirms the system's **Adaptive Computing** capability. The agent utilizes a dynamic stopping mechanism:
    *   **Easy Queries:** Are resolved in 2-3 steps, exiting early.
    *   **Complex Queries:** (e.g., verifying multi-stage formation pathways) utilize the extended budget to perform deep multi-hop reasoning.
*   **Conclusion:** The agent automatically allocates computational resources where they are most needed. Unlike a static pipeline that forces a fixed cost per item, our architecture exhibits an "Elastic Compute" profile, making it robust enough for hard cases while remaining efficient for the majority of the corpus.
