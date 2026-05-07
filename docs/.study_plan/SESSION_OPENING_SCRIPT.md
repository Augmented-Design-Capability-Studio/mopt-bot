# Session Opening — Researcher Script (Quick Version)

A condensed script for the opening of each session — purpose statement, consent, the optimization literacy quiz, stance framing, and the cues to play the orientation and task-briefing videos. Read it through once before piloting; mild paraphrasing during sessions is fine, but the **stance framing** (§3) should land the same way every time, since drift there is a confound for the workflow comparison.

**Conventions:** **[SAY]** = read aloud; **[ACTION]** = do; **[NOTE]** = researcher-only.

## Pre-session checklist

- [ ] Consent form ready (link or PDF)
- [ ] Background self-report ready (survey link or sheet — Part 1 items: experience, expertise, familiarity)
- [ ] Optimization literacy quiz ready (survey link, on-screen poll, or printed sheet — see [`OPTIMIZATION_LITERACY.md`](../.screener/OPTIMIZATION_LITERACY.md))
- [ ] VRPTW-understanding items ready (Part 2 — administered after the task briefing, not here)
- [ ] Knapsack orientation video queued ([`ORIENTATION_VIDEO_SCRIPT.md`](ORIENTATION_VIDEO_SCRIPT.md))
- [ ] VRPTW task-briefing video queued
- [ ] One-page VRPTW reference document on hand
- [ ] Recording software ready (screen + audio)
- [ ] Interface URL loaded with assigned **workflow mode** (Agile or Waterfall)
- [ ] Participant ID and condition recorded in session log

---

## 1. Purpose and consent (~3 min)

**[SAY]**

> Hi [name], thanks for joining. I'm [researcher].
>
> Today we'll have you try out a research prototype — an AI-assisted interface for **metaheuristic optimization**, designed as a general-purpose tool that could be applied to a wide range of optimization problems. For this session it's set up around a specific delivery-scheduling scenario as a test case, but the interface itself is meant to be domain-agnostic. We're not testing you; we're testing the interface — your honest reactions, including frustrations or "I'd never use this for X", are exactly what we want.
>
> The session is about 70–75 minutes: a quick warmup quiz, then a short video with a hands-on tutorial, then another video and some reading for our formal task, a quick interview to check your experience and understanding, followed by the formal task for about 30 minutes, and at the end, a conversation. You can stop or take a break anytime.

**[ACTION]** Share the consent form. Wait for signature.

**[SAY]**

> One thing to confirm out loud: are you comfortable with us recording the screen and audio for our analysis only? We don't share it outside the research team.

**[ACTION]** Start recording. Announce on tape:

**[SAY]**

> Recording started. [date], session [ID].

---

## 2. Background block: self-report + literacy warm-up (~5–6 min)

**[NOTE]** Two short instruments back-to-back, both before stance framing or any orientation material. **Order matters** — administer the self-report **first**, then the warm-up. Reversing them would let warm-up performance contaminate the self-rating, which is a well-known pitfall when an objective measure and a self-rated competence measure share a construct. Don't show the scoring key for the warm-up, don't review correct answers afterward, and don't volunteer optimization-concept hints in this section.

### 2a. Self-reported experience (~3–4 min)

**[SAY]**

> Before we get into the study, I'd like to ask you a few quick background questions about your experience with optimization. There are no right or wrong answers — we're just trying to understand the range of backgrounds participants are coming in with.

**[ACTION]** Share the self-report (Part 1 items: prior coursework/work, overall expertise, familiarity with optimization, expertise using and coding optimization tools, familiarity with heuristics/metaheuristics). Stay quiet while they fill it in.

### 2b. Optimization literacy warm-up (~2 min)

**[SAY]**

> Now a short five-question warm-up — multiple choice, no time pressure. We're collecting some additional background context for the analysis. Each question has an "I'm not sure" option — please use it freely if a question references something you don't recognize, rather than guessing. Otherwise, go with your honest take; your score doesn't change anything about the rest of the session.

**[ACTION]** Share the quiz (link, on-screen poll, or printed sheet — see [`OPTIMIZATION_LITERACY.md`](../.screener/OPTIMIZATION_LITERACY.md)). Stay quiet while they fill it in.

**[ACTION]** Once they're done, record the score (0–5) in the session log. Do **not** review answers with the participant.

**[SAY]** *(after they're done)*

> Great, thanks. Let's keep going.

---

## 3. Stance framing (~3 min)

**[SAY]**

> Two things to keep in mind for the rest of the session.
>
> **First — your role.** In this scenario you are the **scheduler**: the person responsible for the scheduling decisions. You decide what matters, what the priorities are, which trade-offs you'd accept. You are not expected to write code, and you're not expected to know optimization jargon. Bring whatever you already know about logistics or planning, and use it however feels natural — engage as yourself.
>
> **Second — how to think about the AI agent.** Treat the agent as an **optimization programmer who is helping you**. Imagine you'd otherwise have to hire a programmer to set up and run the solver — that's the kind of teammate this agent is meant to replace. So talk to it the way you'd talk to that programmer: tell it what you care about, push back when something doesn't make sense, ask why it's doing what it's doing, and don't accept an answer you don't believe.
>
> The thing we're really trying to learn is whether this kind of interface lets a scheduler like you do work that would otherwise have to be handed off to a programmer. So as you go, notice when it helps and when it gets in the way — we'll talk about those at the end.

**[NOTE]** Pause for questions. Common one — *"What if I don't know the answer to something the agent asks?"* → *"Say so, and see how it handles it. That's part of what we're studying."*

---

## 4. Orientation video and hands-on tutorial (~7–10 min)

**[SAY]**

> Before the actual task, here's a short video that walks through the interface using a simpler example — a packing problem where you choose items to put in a bag with limited space. **You don't need to be familiar with this kind of problem**; the goal is just to see how the agent works through it with you, including the views it sets up to show its results. If anything in the video feels unclear, you can ask the agent to explain it in plain language during the hands-on part — that's part of what it does.

**[ACTION]** Play the **knapsack orientation video** (~3–4 min). Stay quiet during playback.

**[SAY]** *(after the video)*

> Any questions about anything in the video?

**[NOTE]** Brief discussion only.
- If they ask how it relates to the actual task, deflect: *"See if the connections feel natural once you see it."*
- If they seem unsure about the packing/knapsack idea itself, **route them to the agent** rather than explaining it yourself: *"Try asking it in chat once we start the hands-on part — explaining things like that is exactly what it's there for."* Don't define the problem for them; the goal is for them to practice using the agent the same way they will during the formal task.

**[ACTION]** Guide the participant through the **knapsack tutorial** on the interface (~4–6 min).

---

## 5. Task briefing handoff (~10 min, script ends)

**[SAY]**

> Now I'll play the actual task briefing. It introduces a small delivery service called **QuickBite** — a fleet of vehicles and a set of orders to deliver in one day. You'll have a one-page reference on hand for the rest of the session, so don't worry about memorizing anything.
>
> Watch it through, take a moment to read the reference, ask any questions you have, and then we'll start.

**[ACTION]** Play the **VRPTW task-briefing video** and hand over the reference document. Give maximum 3 minutes for the participant to read through the session.

**[NOTE]** End of opening. Continue with the **pre-interaction check** ([`STUDY_DETAILED_PLAN.md`](STUDY_DETAILED_PLAN.md) §5, step 6), then the interaction phase.

---

## Timing summary

| Step | Duration | Cumulative |
|------|----------|------------|
| Purpose + consent + recording start | ~3 min | 3 |
| Background block: self-report (2a) + literacy warm-up (2b) | ~5–6 min | 8–9 |
| Stance framing | ~3 min | 11–12 |
| Orientation video + hands-on tutorial | ~7–10 min | 18–22 |
| Task-briefing handoff (incl. video + reading) | ~10 min | 28–32 |

The pre-interaction check (~5 min, includes the VRPTW-understanding items), interaction phase (~30 min), and post-task questionnaire + interview (~10–12 min) follow.
