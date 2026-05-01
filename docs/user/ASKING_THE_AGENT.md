# Asking the Agent

This guide helps users ask high-value questions and get transparent, confidence-building answers.

## 1) Asking "What Did You Program?"

Use prompts like:

- "What exactly did you program for this run?"
- "Describe what you changed in config terms and why."
- "Show this as a short implementation changelog."

Expected answer style:

- Goal-term changes (what was emphasized/de-emphasized)
- Constraint handling changes
- Search strategy and parameter changes
- Intended trade-off
- Suggested next validation run

## 2) Ask for Two Levels of Detail

### Plain-language view

"Explain this run in plain operations language."

### Technical view

"Explain this as configuration and solver settings."

Switch between these views to match your confidence level.

## 3) Good Follow-up Questions

- "What is the smallest next change with highest expected impact?"
- "What are the top risks in this configuration?"
- "What evidence from the run supports your recommendation?"
- "If this fails, what fallback setting should I try?"

## 4) Grounded Explanation Requests

To keep answers concrete, ask:

- "Cite the settings you are referring to."
- "Compare this run to Run #N and list only changed fields."
- "Separate confirmed effects from hypotheses."

## 5) Confidence Checklist

Before accepting a recommendation, ask the agent to confirm:

- Current objective priorities
- Constraint strictness assumptions
- Search strategy and stopping behavior
- Expected upside and downside

Then run one focused validation test.

## 6) Prompt Templates You Can Reuse

- "Give me a one-paragraph rationale for the current configuration."
- "Provide a diff-style summary between the last two runs."
- "Propose one safe tuning and one aggressive tuning."
- "Explain what this setting does and when to increase or decrease it."
