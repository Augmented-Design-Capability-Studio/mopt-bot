# Knapsack Orientation Video — Script

A ~3–4 minute video shown at the **Optimization orientation** step of the session (see [`STUDY_DETAILED_PLAN.md`](STUDY_DETAILED_PLAN.md) §5, step 3). It walks the participant through the AI-agent interface using the knapsack problem as a neutral warm-up so they recognize the workflow — chat → definition → configuration → run → iterate — before tackling the QuickBite task. The video deliberately avoids lecturing on optimization concepts so it does not coach answers to the [optimization literacy instrument](../.screener/OPTIMIZATION_LITERACY.md), which may be re-administered post-session; general optimization questions are routed to the agent during the session.

Format follows the in-use TTS script style: `[Inhale]` for breath cues, `[pause]` and `[long pause]` for in-line timing, and `<break time='Ns'/>` for SSML breaks between paragraphs. Each narration paragraph below is paired with a screen-recording action block lower in the file — match the pacing.

---

At Augmented Design Capability Studio, we built a general-purpose AI agent interface that creates metaheuristic optimization programs for you. [pause] For this study we are working with QuickBite and created a vehicle scheduling task as our test problem. [pause] Before you start, let's walk through the interface using a much simpler example: the knapsack problem. 

[Inhale] Knapsack is simple: choose from 22 candidate items to maximize total value while staying under a 50-unit capacity. [pause] Three things you might care about: total **value**, the **capacity** limit, and — sometimes — keeping the **selection small**. [pause] Capacity is a hard constraint, no exceptions; value is a goal you push as high as you can. As you direct the agent, watch which things get treated as hard rules and which get treated as goals. 

[Inhale] You start by typing your problem in the chat and uploading any data files. [long pause] The agent translates your natural-language goals into a structured problem definition, which then becomes a runnable problem configuration. [pause] You can edit either side directly — changes flow both ways, and the agent acknowledges them. 

[Inhale] Open the Definition tab to see what the agent gathered. [pause] You'll see facts the agent extracted from your prompt and the uploaded data, plus a few open questions where it wants your call. [pause] Adding a new goal mid-flow is simple — just say so in chat. Here we ask the agent to also keep the selection small. [pause] A new goal-term row appears in the definition, ready for the next stage. 

[Inhale] Now open the Problem Config tab to see how those goals are wired into the solver. [pause] Each row has a constraint type — objective, soft, hard, or custom — and a weight. [pause] You can drag-rank the rows to signal which ones matter most; that's a priority hint, since a goal's actual influence also depends on the scale of what it measures. [pause] Switching a row to **Custom** lets you type a specific weight number directly. [pause] Save when you're happy with the setup. 

[Inhale] Now launch a run with the **Run Optimization** button or by asking in chat. [long pause] When it finishes, you'll see the selected items and a convergence curve — views the agent set up for your task — showing how the cost dropped over the search. [pause] You can also expand a panel below to see how each goal contributed to the total cost — useful for spotting which goal is dominating. 

[Inhale] One last thing. If something the agent does doesn't make sense, push back — ask why. [pause] You can also ask the agent general questions about how metaheuristic optimization works; it can answer those just like it can set up your task. [pause] The same workflow you just saw is what you'll use on the QuickBite task next. 

[Inhale] That concludes the demo. During the study, take questions about the task or about how optimization works to the agent first — it can handle both. [pause] Save the researcher for anything about the session itself — pacing, technical glitches, or other things outside the task. <break time='0.5s'/>

---

## Screen recording cues

Condensed action plan for the recorder, paired 1-to-1 with the narration paragraphs above. Time each action block to land inside its paragraph; use the `[pause]`, `[long pause]`, and `<break time='Ns'/>` cues as breathing room. Re-record any segment where an agent reply takes longer than a single beat — cut the wait in post.

### Setup before recording

- Confirm the session is in **demo** workflow mode (researcher detail card shows the muted-amber `detail--wf-demo` border; the participant header shows the muted-amber top accent and the "Demo mode" chip). Demo is what we want here — its prompt guardrails keep the agent's output predictable, runs are not gated by open questions, and auto-run from chat intent is disabled so the **Run optimization** button click stays part of the recording.
- Confirm the in-app tutorial is **disabled** (in demo it is hidden anyway, but double-check `participant_tutorial_enabled` is off so no stale bubble flashes if mode is flipped mid-recording).
- Start a **fresh session** so chat history is empty and the Definition panel is clean.
- Have the **Problem Definition / Problem Config** tabs and the **Results & Visualization** panel both visible (no devtools, no URL bar showing problem identifiers).
- Copy the starter prompt to clipboard so you can paste it cleanly:
  > *"I would like to optimize for a simple knapsack problem. I have a list of 22 items with various values and weights to put into a bag of 50-weight capacity. I want to maximize the value in the bag without exceeding the capacity limit."*
- Have the **knapsack item file** ready in the file picker (Downloads / clipboard path) — it goes up on-camera during para 3.

### Para 1 — Lab intro + test problem framing

- Show the interface **idle** on the knapsack demo problem; chat empty, panels clean.
- No clicks. Optional: open with a brief title card or studio branding, then cut to the interface.

### Para 2 — Knapsack setup; the three things to care about

- Briefly hover or pan across the **Problem Definition** panel as each concept is named: highlight the **capacity** field, the **value** goal area, and (briefly) the empty space where a third selection-size goal-term row will appear later.
- No typing. Don't dwell — the framing is verbal.

### Para 3 — Chat → upload

- Click into the chat input.
- **Paste** the starter prompt and submit.
- When the agent's first reply asks for the data file (it should, given the prompt mentions a list of items), click **Upload file(s)…** in the chat footer and pick the knapsack item file. The chip should appear in the chat footer.
- Submit a brief follow-up like *"there you go"* if the upload alone hasn't already triggered the agent's next turn.

### Para 4 — Definition tab + add a third goal

- Click the **Definition** tab. Show the populated **Gathered** rows (items, capacity, value goal) and any **Open questions** the agent raised — pan briefly to the open-questions area as the narration mentions them.
- Click into the chat input. **Type:** *"Choose fewer items if possible."* and submit.
- Wait for the agent's reply to land and the post-run loading state to clear.
- Return to the **Definition** tab. A new gathered or assumption row tied to **selection size / fewer items** should now be visible — pan to it as the narration says "a new goal-term row appears."

### Para 5 — Problem Config tab

- Click the **Problem Config** tab.
- Demonstrate **drag-ranking** by dragging one goal row above another. The helper text below the section ("Drag to set a priority order…") will read on-screen as the narration explains the priority-hint caveat.
- Click the constraint-type selector on one row (a soft or objective row) and switch it to **Custom**, then click into its weight field and adjust the number to show the input is directly editable.
- Click **Save**.

### Para 6 — Run + visualizations + breakdown

- Click **Run optimization**.
- The optimization progress bar plays; once the run-finished line lands in chat, the **"Configuring visualization and analyzing run..."** loading label takes over briefly.
- Switch to the **Item Selection** tab — show which items were packed and the total weight.
- Switch back to the **Convergence** tab — show the cost curve.
- (If your build exposes it) expand the per-goal-term contribution panel on the run card so the *"see how each goal contributed"* line lands on a visible expansion.

### Para 7 — Push back / ask the agent

- Click into the chat input.
- Type a short concept question, e.g. *"What does the convergence curve mean?"*
- Submit; let the reply render briefly. Don't pause to read the full response — the narration carries on.

### Para 8 — Outro

- Return to a clean state, or freeze on the run results card.
- No interaction.

### Don'ts

- No devtools, browser address bar, or researcher-only UI in frame at any time.
- No tooltips or panel labels that contain `test_problem_id`, `vizTabs`, or anything implying preset/templated views.
- Don't read agent replies aloud — narration stays scripted regardless of what the agent actually says.

### Timing budget

Eight narration paragraphs at ~500 words total run ~3:20 of pure speech at a typical TTS pace, plus ~14 seconds of inter-paragraph `<break>` and ~10 seconds of in-line `[pause]` cues — landing the finished cut at roughly **3:35–3:55**. If the recorder needs more breathing room for an agent reply, hold on the `[long pause]` cues in Paras 3 and 6 first; if cuts are needed, trim the action between *"submit a brief follow-up"* (Para 3) and the agent's acknowledgment.
