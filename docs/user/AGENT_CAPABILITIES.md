# What the Assistant Can Help With

This page describes what you can ask the chat assistant and how it can help you get
more out of the platform. It is also what the assistant uses to answer questions
like "what can you do?" or "how do I see more?".

## 1) Translating Goals into a Setup

You describe operational goals in plain language; the assistant maps them to
goal-term emphases, constraint handling, and search-strategy settings, then writes
those into the Definition and Problem Config tabs for you. You can always override
or fine-tune anything yourself.

Useful prompts:

- "Minimize cost while keeping hard-limit violations near zero."
- "Treat the main constraint as non-negotiable and balance the remaining priorities."
- "Set up a balanced baseline I can compare other runs against."

## 2) Explaining the Current Setup

The assistant can describe what is currently configured — in plain language,
in engineering language, or as a diff against a previous run.

Useful prompts:

- "Summarize my current optimization strategy in plain language."
- "List my active priorities and constraints."
- "Show this configuration as if I were handing it to an engineer."
- "What changed in Problem Config between my last two runs?"

## 3) Interpreting Run Results

After each run the assistant can interpret the convergence curve, metric cards,
and violation summary, and propose the next single most useful change.

Useful prompts:

- "Why didn't this run improve over the last one?"
- "Which violation is the biggest drag on the current cost?"
- "What is the smallest next change with the highest expected impact?"
- "What is one safe tuning and one aggressive tuning to try next?"

## 4) Explaining the Module Code

The assistant can walk you through how the active module is structured and how
your priorities flow through its layers into a run. The optimizer supports several
search families (evolutionary, swarm, annealing, ant-colony) that can be selected
without rewriting anything else.

Useful prompts:

- "Explain how the active module is structured."
- "Walk me through how the evaluator scores a candidate solution."
- "Why does changing this emphasis usually move the result?"
- "Why might a run with the same setup return slightly different numbers?"

## 5) Pointing You at the Right UI Surface

The assistant can tell you where to look in the UI to see more detail — the
Definition tab, Problem Config tab, Raw JSON tab, or the Results panel. See
`INTERFACE_GUIDE.md` for the full layout.

Useful prompts:

- "Where can I see the convergence chart for this run?"
- "How do I see the structured record of what we discussed?"
- "Where is the raw configuration so I can compare two runs?"

## 6) What the Assistant Will Not Do

- It will not invent goal terms, constraints, or settings you have not discussed
  or configured. If you ask "list every weight you support", it will only describe
  the ones currently in your Definition, Config, or chat history.
- It will not reveal hidden internal field names or scoring formulas — it talks
  about the setup in user-facing terms.
- It will not reveal raw source code, internal configuration keys, or library
  names. If you ask about implementation details, it will describe the approach
  in plain engineering language.

## 7) Useful General Prompts

- "What can you help me do right now?"
- "What's the next single most useful step?"
- "What should I check before running again?"
- "Compare Run #N and Run #M and explain the trade-off."
