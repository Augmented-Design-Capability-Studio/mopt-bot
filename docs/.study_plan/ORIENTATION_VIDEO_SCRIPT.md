# Knapsack Orientation Video — Script

A ~3–4 minute video shown at the **Optimization orientation** step of the session (see [`STUDY_DETAILED_PLAN.md`](STUDY_DETAILED_PLAN.md) §5, step 3). It introduces the AI-agent interface using the knapsack problem as a neutral warm-up, and seeds the four optimization concepts participants need before they tackle the QuickBite task: **hard vs. soft constraints**, **multi-objective trade-offs**, **stochasticity in solver results**, and the **model-vs-reality gap**.

Format follows the in-use TTS script style: `[Inhale]` for breath cues, `[pause]` and `[long pause]` for in-line timing, and `<break time='Ns'/>` for SSML breaks between paragraphs.

---

At Augmented Design Capability Studio, we built an AI agent interface that creates metaheuristic optimization programs for you. [pause] We are working with QuickBite and created a vehicle scheduling task as our test problem. [pause] Before you start, let's walk through the interface using a much simpler example: the knapsack problem. <break time='2s'/>

[Inhale] Knapsack is simple: choose items to maximize total value while staying under a capacity limit. [long pause] In this toy setup, we have 22 candidate items and a capacity of 50 units. [long pause] Notice the difference between the two sides of this. Capacity is a hard constraint — your selection must fit, no exceptions. Value is a goal — you want as much of it as possible, but there is no fixed "right" amount. As you direct the agent, pay attention to which things get treated as hard rules and which get treated as goals. <break time='2s'/>

[Inhale] You start by typing your project goals into the chat. [long pause] The agent translates your natural-language goals into a structured problem definition, which then becomes a runnable problem configuration on the Problem Setup panel. [long pause] You can edit either the definition or the configuration directly — changes flow both ways, and the agent acknowledges them. <break time='2s'/>

[Inhale] You are not limited to a single goal. You might also care about how many items you pick, or about keeping the total weight balanced — and the agent can encode those alongside value as competing objectives. [pause] When two goals pull against each other, you decide how to weigh them. [pause] Try changing the weights between runs and see how the chosen items shift. <break time='2s'/>

[Inhale] Once you have at least one goal and a search strategy, you can launch a run, either with the "Run Optimization" button or by asking in chat. [long pause] When a run finishes, you'll see the selected items and a convergence curve showing how the cost dropped over the search. [pause] Two things to keep in mind. The search has randomness in it, so two runs with the same settings can give slightly different answers — that is expected, not a bug. [pause] And a small improvement doesn't mean you have found the best possible answer; more iterations or different settings often still help. <break time='2s'/>

[Inhale] One last thing. The number the program is minimizing is just a score — a stand-in for what you really care about. [pause] If a high-scoring solution doesn't feel right, the score is probably missing something. Push back on the agent and ask it to add or change what's being measured. <break time='1s'/> [pause] The same workflow you just saw — chat, define, configure, run, iterate — is what you'll use on the QuickBite scheduling task. The QuickBite delivery manager will brief you on the details next. <break time='2s'/>

[Inhale] That concludes the demo. If anything is unclear during the study, feel free to ask our researcher. <break time='0.5s'/>
