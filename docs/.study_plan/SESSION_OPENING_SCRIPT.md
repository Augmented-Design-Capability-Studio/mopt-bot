# Session Opening — Researcher Script (Quick Version)

A condensed script for the opening of each session — purpose statement, consent, stance framing, and the cues to play the orientation and task-briefing videos. Read it through once before piloting; mild paraphrasing during sessions is fine, but the **stance framing** (§2) should land the same way every time, since drift there is a confound for the workflow comparison.

**Conventions:** **[SAY]** = read aloud; **[ACTION]** = do; **[NOTE]** = researcher-only.

## Pre-session checklist

- [ ] Consent form ready (link or PDF)
- [ ] Knapsack orientation video queued ([`ORIENTATION_VIDEO_SCRIPT.md`](ORIENTATION_VIDEO_SCRIPT.md))
- [ ] VRPTW task-briefing video queued
- [ ] One-page VRPTW reference document on hand
- [ ] Recording software ready (screen + audio)
- [ ] Interface URL loaded with assigned **workflow mode** (Agile or Waterfall)
- [ ] Participant ID and condition recorded in session log

---

## 1. Purpose and consent (~5 min)

**[SAY]**

> Hi [name], thanks for joining. I'm [researcher].
>
> Today we'll have you try out a research prototype — an interface that helps a person solve a scheduling problem by directing an AI assistant. We're not testing you; we're testing the interface. Honest reactions — including frustrations or "I'd never use this for X" — are exactly what we want.
>
> The session is about 60–75 minutes: a short video with a hands-on tutorial, then another video and some reading for our formal task, a quick interview to check your experience and understanding, followed by the formal task for about 30 minutes, and at the end, a conversation. You can stop or take a break anytime.

**[ACTION]** Share the consent form. Wait for signature.

**[SAY]**

> One thing to confirm out loud: are you comfortable with us recording the screen and audio for our analysis only? We don't share it outside the research team.

**[ACTION]** Start recording. Announce on tape:

**[SAY]**

> Recording started. [date], session [ID].

---

## 2. Stance framing (~3 min)

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

## 3. Orientation video and hands-on tutorial (~10-15 min)

**[SAY]**

> Before the actual task, here's a short video that walks through the interface using a simpler problem — the knapsack problem — so you see the workflow before doing it for real.

**[ACTION]** Play the **knapsack orientation video** (~3–4 min). Stay quiet during playback.

**[SAY]** *(after the video)*

> Any questions about anything in the video?

**[NOTE]** Brief discussion only. If they ask how it relates to the actual task, deflect: *"See if the connections feel natural once you see it."*

**[ACTION]** Guide the participant through the **knapsack tutorial** on the interface (~5-8 min).

---

## 4. Task briefing handoff (~10 min script ends)

**[SAY]**

> Now I'll play the actual task briefing. It introduces a small delivery service called **QuickBite** — a fleet of vehicles and a set of orders to deliver in one day. You'll have a one-page reference on hand for the rest of the session, so don't worry about memorizing anything.
>
> Watch it through, take a moment to read the reference, ask any questions you have, and then we'll start.

**[ACTION]** Play the **VRPTW task-briefing video** and hand over the reference document. Give maximum 3 minutes for the participant to read through the session.

**[NOTE]** End of opening. Continue with the **pre-interaction check** ([`STUDY_DETAILED_PLAN.md`](STUDY_DETAILED_PLAN.md) §5, step 5), then the interaction phase.

---

## Timing summary

| Step | Duration | Cumulative |
|------|----------|------------|
| Purpose + consent + recording start | ~5 min | 5 |
| Stance framing | ~3 min | 8 |
| Orientation video + discussion | ~10–15 min | 18–23 |
| Task-briefing handoff (incl. video) | ~10 min | 28–33 |

The pre-interaction check, interaction phase (~30–40 min), and post-task discussion follow.
