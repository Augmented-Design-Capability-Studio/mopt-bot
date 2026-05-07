# Optimization Concepts

Plain-language answers to common questions about how the search engine works.

## Hard rules vs soft rules

A hard rule must be satisfied — the search rejects any solution that breaks it, no matter how good it looks otherwise. A soft rule is a preference with a penalty: breaking it is allowed but costs you in the score. Capacity caps and shift limits are typical hard rules; lateness or workload fairness usually starts as soft. The choice between hard and soft changes how the search treats violations, not just how much they cost.

## Why identical settings give different answers

The search engine uses randomness — where it starts, which combinations it tries, which mutations it applies. With the same problem and the same settings, two runs explore different paths and often land on different answers. This is normal, not a bug. Re-running a few times is a useful sanity check on whether your current best is robust or just lucky.

## What a convergence curve shows

The convergence chart tracks the best score the search has found over time. A curve that drops fast then flattens means the search has likely converged on its best answer for this run. A curve still falling at the end means more iterations could help. A flat line from the start often means the problem is over-constrained and the search can't make progress.

## Multi-goal trade-offs

When you have several objectives, the score blends them using importance levels you set. Doubling the importance of on-time delivery makes the search willing to give up some fuel savings to reduce lateness. The numbers express how much you care about each goal **relative to the others**, not absolute units. Tune them by running, observing, and adjusting.

## When the search gets stuck

Sometimes runs converge early on a mediocre answer because the search found a local pocket and couldn't escape. Symptoms: similar costs across multiple runs, a convergence curve that flattens too soon. Fixes: try annealing search (more willing to escape early), increase the iteration budget, or rebalance priorities so the search has stronger pressure to keep exploring.

## What scoring captures and what it misses

The score reflects only what's encoded as goals and rules. If something matters in real operations but isn't in the setup — driver familiarity, customer relationships, weather risk — the search won't know. A "winning" score is the best answer **given the model**, not the best decision in reality. Always check results against operational judgment before acting on them.
