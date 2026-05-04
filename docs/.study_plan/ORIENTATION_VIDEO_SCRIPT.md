# Knapsack Orientation Video — Script

A ~3–4 minute video shown at the **Optimization orientation** step of the session (see [`STUDY_DETAILED_PLAN.md`](STUDY_DETAILED_PLAN.md) §5, step 3). It walks the participant through the AI-agent interface using the knapsack problem as a neutral warm-up so they recognize the workflow — chat → definition → configuration → run → iterate — before tackling the QuickBite task. The video deliberately avoids lecturing on optimization concepts so it does not coach answers to the [optimization literacy instrument](../.screener/OPTIMIZATION_LITERACY.md), which may be re-administered post-session; general optimization questions are routed to the agent during the session.

Format follows the in-use TTS script style: `[Inhale]` for breath cues, `[pause]` and `[long pause]` for in-line timing, and `<break time='Ns'/>` for SSML breaks between paragraphs.

---

At Augmented Design Capability Studio, we built a general-purpose AI agent interface that creates metaheuristic optimization programs for you. [pause] For this study we are working with QuickBite and created a vehicle scheduling task as our test problem. [pause] Before you start, let's walk through the interface using a much simpler example: the knapsack problem. <break time='2s'/>

[Inhale] Knapsack is simple: choose items to maximize total value while staying under a capacity limit. [long pause] In this toy setup, we have 22 candidate items and a capacity of 50 units. [long pause] Notice the difference between the two sides of this. Capacity is a hard constraint — your selection must fit, no exceptions. Value is a goal — you want as much of it as possible, but there is no fixed "right" amount. As you direct the agent, pay attention to which things get treated as hard rules and which get treated as goals. <break time='2s'/>

[Inhale] You start by typing your project goals into the chat and uploading data files if needed. [long pause] The agent translates your natural-language goals into a structured problem definition, which then becomes a runnable problem configuration on the Problem Setup panel. [long pause] You can edit either the definition or the configuration directly — changes flow both ways, and the agent acknowledges them. <break time='2s'/>

[Inhale] You are not limited to a single goal. You might also care about how many items you pick, or about keeping the total weight balanced — and the agent can encode those alongside value as competing objectives. [pause] When two goals pull against each other, you decide how to weigh them. [pause] You can drag-rank the goals to signal which ones matter most — that's a priority hint, not a direct weight setting, since a goal's actual influence also depends on the size of what it measures. Or set the importance numbers yourself. [pause] Try changing things between runs and see how the chosen items shift. <break time='2s'/>

[Inhale] Once you have at least one goal and a search strategy, you can launch a run, either with the "Run Optimization" button or by asking in chat. [long pause] When a run finishes, you'll see the selected items and a convergence curve — views the agent has set up for the problem you've described — showing how the cost dropped over the search. [pause] On richer problems, you can also expand a panel to see how each goal term contributed to the total cost — useful for spotting which goal is dominating. <break time='2s'/>

[Inhale] One last thing. If something the agent does doesn't make sense, push back — ask why it's doing what it's doing, or ask it to walk you through its choices. [pause] You can also ask the agent general questions about how metaheuristic optimization works; it can answer those just like it can set up your task, so try it before flagging the researcher. <break time='1s'/> [pause] The same workflow you just saw — chat, define, configure, run, iterate — is what you'll use on the QuickBite scheduling task. The QuickBite delivery manager will brief you on the details next. <break time='2s'/>

[Inhale] That concludes the demo. If anything is unclear during the study, feel free to ask our researcher. <break time='0.5s'/>

---

## Screen recording cues

Condensed action plan for the recorder, mapped to the narration paragraphs above. Time the actions to land within each paragraph; use the `[pause]`, `[long pause]`, and `<break time='Ns'/>` cues as breathing room. Re-record any segment where an agent reply takes longer than a single beat — cut the wait in post.

### Setup before recording

- Confirm the session is in **demo** workflow mode (researcher detail card shows the muted-amber `detail--wf-demo` border; the participant header shows the muted-amber top accent and the "Demo mode" chip). Demo is what we want here — its prompt guardrails keep the agent's output predictable, and runs are not gated by open questions, so the recording doesn't deadlock waiting on an answer.
- Confirm the in-app tutorial is **disabled** (in demo it is hidden anyway, but double-check `participant_tutorial_enabled` is off so no stale bubble flashes if mode is flipped mid-recording).
- Start a **fresh session** so chat history is empty and the Definition panel is clean.
- Have the **Problem Definition / Problem Config** tabs and the **Results & Visualization** panel both visible (no devtools, no URL bar showing problem identifiers).
- Copy the starter prompt to clipboard so you can paste it cleanly:
  > *"I would like to optimize for a simple knapsack problem. I have a list of 22 items with various values and weights to put into a bag of 50-weight capacity. I want to maximize the value in the bag without exceeding the capacity limit."*
- Have the **knapsack item file** ready in the file picker (Downloads / clipboard path) — it goes up on-camera during para 3.

### Para 1 — Lab + test problem intro

- Show the interface **idle** on the knapsack demo problem; chat empty, panels clean.
- No clicks. Optional: open with a brief title card or studio branding, then cut to the interface.

### Para 2 — Knapsack setup; hard rule vs goal

- Hover/highlight the **capacity** field and the **value** goal area in the Problem Definition panel as the narration mentions each.
- No typing. Don't dwell — the framing is verbal.

### Para 3 — Chat → upload → definition → configuration

- Click into the chat input.
- **Paste** the starter prompt and submit.
- When the agent's first reply asks for the data file (it should, given the prompt mentions a list of items), click **Upload file(s)…** in the chat footer and pick the knapsack item file. The chip should appear in the chat footer.
- Submit a brief follow-up so the agent acknowledges the upload (e.g. type *"there you go"* and submit) — or just let the agent's next turn arrive on its own if the upload alone triggers a reply.
- As the agent replies, let the **Problem Definition** tab populate (gathered rows: items, capacity, value goal). In demo mode the agent will also raise a small number of **open questions** rather than silently making assumptions — that's expected and visible on the panel.
- Click once between the **Definition** and **Problem Config** tabs so both layouts are shown.

### Para 4 — Multiple goals, ranking, weights

- Click into the chat. **Type:** *"Also keep the bag light — fewer items if possible."* Submit.
- After the agent's reply (which in demo mode may add the goal *and* attach a clarifying open question rather than committing to a numeric weight), switch to **Problem Config**.
- Demonstrate **drag-ranking** the two goal rows (drag one to swap order). Note: the helper text below the section explains that ranking is a priority hint, not a direct weight setting.
- Briefly hover or click into a **Custom**-mode weight value to show that the number is directly editable when constraint type is Custom.
- Click **Save**.

### Para 5 — Run + convergence + breakdown

- Click **Run optimization**.
- Let the **Convergence** tab animate as the solver progresses.
- Switch to the **Item Selection** tab — show which items were packed and the total weight.
- (Optional, only if your build exposes it) expand the per-goal-term contribution panel on the run card.

### Para 6 — Push back / ask the agent

- Click into the chat input.
- **Type a short example question** so the viewer sees the agent answering interface/concept questions, e.g. *"Why did you pick those items?"* — or, to model the optimization-question redirect, *"What does the convergence curve mean?"*
- Submit; let the reply render briefly. Don't pause to read the full response — the narration carries on.

### Para 7 — Outro

- Return to a clean state, or freeze on the run results card.
- No interaction.

### Don'ts

- No devtools, browser address bar, or researcher-only UI in frame at any time.
- No tooltips or panel labels that contain `test_problem_id`, `vizTabs`, or anything implying preset/templated views.
- Don't read agent replies aloud — narration stays scripted regardless of what the agent actually says.
