"""LLM prompt contributions for the template problem.

These strings are injected into the chat system prompt and config-derivation call
by the port's study_prompt_appendix() and config_derive_system_prompt() methods.
Keep them problem-agnostic from the participant's perspective — refer to
"the optimization problem" rather than naming the domain.
"""

# Appended to the base study chat system prompt for every turn in this problem.
# Use this to teach the model about the problem structure, objective vocabulary,
# and any domain conventions the participant should discover through chat.
STUDY_PROMPT_APPENDIX = """
## Problem-specific context (hidden from participant)

TODO: Describe the underlying problem to the model here.
- What does the objective function minimize/maximize?
- What are the key constraints?
- How do the weight keys map to those objectives?
- What common participant mistakes should the model help with?
""".strip()


# System instructions for the LLM when deriving a structured panel config
# from the current problem brief via structured JSON output.
CONFIG_DERIVE_SYSTEM_PROMPT = """
TODO: Provide instructions for deriving the panel config JSON from the brief.
The LLM will produce a { "problem": { "weights": {...}, "algorithm": "...", ... } } object.
Describe how each field should be inferred from brief items.
""".strip()
