# Algorithm Choices

Plain-language guide to picking a search method.

## Which algorithm should I use?

If you don't have a preference, **genetic search (GA)** is the safe default — a solid all-purpose choice that works for most setups. Pick a different method only if you have a specific reason: you want a faster pass when trade-offs look smooth (try swarm), or earlier runs keep getting stuck on similar answers (try annealing). You can change methods between runs, so the first choice isn't permanent.

## Genetic search (GA)

Tries lots of combinations, keeps the best ones, and mixes them to try better ones each round. A solid all-purpose choice when you don't know much about the problem yet. It's the default starting point when no preference has been stated.

## Swarm search (PSO)

Many candidates explore together and share what they find — often faster when the trade-offs between objectives are smooth and well-behaved. Worth trying when genetic search feels slow on a problem where small input changes give small output changes.

## Annealing search (SA)

Starts wide and bold, then narrows in — useful when other methods keep getting stuck on the same answer. Good when the search space has a lot of similar-looking dead ends and you need a method willing to take risks early before settling down.

## When to switch search methods

Switch when you have a specific signal: runs converge to similar costs across attempts (try annealing for variety), one method feels slow on a smooth problem (try swarm), or you want a baseline before tuning priorities (stick with genetic). Don't switch as a fix for unclear objectives — algorithm choice rarely rescues a fuzzy problem.

## Algorithm choice never blocks running

The choice is reversible and shouldn't hold up a first run. In waterfall, treat the algorithm question as a soft default — start with genetic search unless the user prefers otherwise. In agile, set a working algorithm so a baseline run is possible; the user can change it any turn. Don't make method selection an open question unless the user raised it.
