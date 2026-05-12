# Session Opening — Researcher Script

**Conventions:** **[SAY]** = read aloud; **[ACTION]** = do; **[NOTE]** = researcher-only.

## Pre-session checklist

- \[ \] Add a section to the participant Google doc
- \[ \] Consent form ready (link or PDF)
- \[ \] Pre-task ackground self-report ready (Part 1)
- \[ \] Knapsack orientation video queued
- \[ \] VRPTW task-briefing video queued
- \[ \] One-page VRPTW reference document on hand
- \[ \] Recording software ready (Zoom video, audio, and screen sharing)
- \[ \] Interface _tutorial_ URL loaded with assigned **workflow mode** (Agile or Waterfall)
- \[ \] Interface URL loaded with assigned **workflow mode** (Agile or Waterfall)
- \[ \] Participant ID and condition recorded in session logs

---

## 1. Purpose and consent (~3 min)

**[SAY]**

> Hi [name], thanks for joining. I'm [researcher].
>
> Today we'll have you try out a research prototype — an AI-assisted interface for **metaheuristic optimization**, designed to solve a wide range of optimization problems involving trade-offs. Traditionally, to optimize a decision given a bunch of trade-offs, even a domain expert may have to hire a programmer. We designed the interface because we believe that very soon, people with or without technical knowledge can use AI programming agents to create their own optimization programs with a fast turnaround.
>
> In the main task of this study, you will try out our interface by role-playing as a scheduler for a small delivery crew. Depending on your background you might find it more or less challenging. Keep in mind that we're not testing you; we're testing the interface. Your honest reactions are exactly what we want.
>
> The session is about 70–75 minutes. It includes about 6 steps: 1) a quick survey and a warmup quiz, 2) a short video with a hands-on tutorial, 3) another video and some reading for our formal task, 4) a few quick questions to check your understanding, followed by 5) the formal task for about 30 minutes, and at the end, 6) a conversation. You can stop or take a break anytime. You will be compensated $25 if you complete this whole session.

**[ACTION]** Share the consent form. Wait for signature.

**[SAY]**

> This study also requires video and audio recording. Are you comfortable with us recording the screen and audio for our analysis?

**[ACTION]** Start recording (on Zoom). Check screen sharing.

---

## 2. Background block: self-report + literacy warm-up (~5–6 min)

**[NOTE]** Two short instruments back-to-back.

### 2a. Self-reported experience (~3–4 min)

**[SAY]**

> Before we get into the interface, I'd like to ask you a few quick background questions about your experience with optimization. There are no right or wrong answers — we're just trying to understand the range of backgrounds participants are coming in with. We will then complete 5 warm-up multiple choice questions.

**[ACTION]** Share the self-report. Stay quiet while they fill it in.

### 2b. Optimization literacy warm-up (~2 min)

**[SAY]** *(optional)*

> Now a short five-question warm-up about your understanding of computational optimization. Each question has an "I'm not sure" option — please use it freely if a question references something you don't recognize, rather than guessing. Otherwise, go with your honest take. Your score doesn't change anything about the rest of the session or your compensation.

**[ACTION]** Share the quiz. Stay quiet while they fill it in.

**[ACTION]** Once they're done,  pause the survey as prompted by the form.

**[SAY]** *(after they're done)*

> Great, thanks. We can pause here for a bit.

---

## 3. Orientation video and hands-on tutorial (~7–10 min)

**[SAY]**

> Let's get familiar with the interface. We'll now watch a short video that walks through the interface using a simpler example: a packing problem where you choose items to put in a bag with limited capacity. After the video, we will have a hands-on practice for the same problem. You don't need to be familiar with this kind of problem; the goal is just to see how the agent works through it with you. If anything in the video feels unclear, you can try asking the agent to explain it in plain language during the hands-on part before asking the researcher.

**[ACTION]** Play the **knapsack orientation video** (~3–4 min). Stay quiet during playback.

**[SAY]** *(after the video)*

> Any questions about anything in the video?

**[NOTE]**
- If they seem unsure about the packing/knapsack idea itself, **route them to the agent** rather than explaining it yourself: *"Try asking it in chat once we start the hands-on part — explaining things like that is exactly what it's there for."* Don't define the problem for them; the goal is for them to practice using the agent the same way they will during the formal task.

**[ACTION]** Guide the participant through the **knapsack tutorial** on the interface (~4–6 min).

---


## 4. Task briefing handoff (~12 min, script ends)

**[SAY]**

> Now I'll play the actual task briefing video. It introduces a small delivery service called **QuickBite** — a fleet of vehicles and a set of orders to deliver in one day. You'll have a hard copy reference on hand for the rest of the session, so don't worry about memorizing anything. We present the problem this way because we are interested in how people formulate the problem to the AI agent.

**[ACTION]** Play the **VRPTW task-briefing video** and hand over the reference document. Give maximum 3 minutes for the participant to read through the session (8 min).

**[SAY]** *(after the video)*
> Now we'll continue the pre-task survey form. I'm just going to ask you about your understanding of the problem. We expect participants from various backgrounds so totally fine if you aren't 100-percent sure.

**[ACTION]** Complete the rest of the pre-task form (3 min).

---

## 5. Stance framing (~2 min)

**[SAY]** *(After finishing the pre-task form)*

> Three things to keep in mind for the rest of the session:
>
> **First — your role.** In this scenario you are the **scheduler**: the person responsible for the scheduling decisions. You decide priorities and trade-offs based on the briefing materials. You are not expected to write code, and you're not expected to know optimization jargon. Bring whatever you already know about logistics or planning, and use it however feels natural.
>
> **Second — the AI agent's role.** Treat the agent as an **optimization programmer who is helping you**. Imagine you'd otherwise have to hire a programmer to set up and run the solver. Talk to the agent the way you'd talk to that programmer: tell it what you care about, push back when something doesn't make sense, and ask why it does certain things. Of course, for glitches and procedural questions, feel free to let the researcher know!
>
> **Third - think aloud.** As you go, try **thinking aloud**, that is, vocalizing your thoughts for your actions. Notice when the system helps and when it gets in the way — we'll talk about those at the end.

**[NOTE]** Pause for questions. Common one — *"What if I don't know the answer to something the agent asks?"* → *"Say so, and see how it handles it. That's part of what we're studying."*

---

## 6. Main task interaction

**[ACTION]** Stay put as the participants interacts with the system. Wait for the participant to get a satisfactory result or wait around 30 minutes.

**[NOTE]** May remind the participant to think aloud. Do not intervene or send "steer" messages unless the participant is stuck.

---

## 7. Post-Task Interview

**[SAY]** *(after the main task)*
> We are at the 30-minute mark. We may want to wrap up the interaction and talk about how you feel for a little.

**[ACTION]** Open and show the participant the post-task interview.

---

## 7. Final Thoughts

**[SAY]** *(after the post-task questions)*

> Great. This concludes our session. Thank you so much for your participation. Once again, if you have any questions or concerns after this session, feel free to reach out to me.
>
> We will deliver a $25 Amazon gift card to your email address in a few days. Our lab administrator is usually quite responsive. If you still haven't received it in about 2 weeks, please send me a reminder too!


## Timing summary


| Step                                                       | Duration  | Cumulative |
| ---------------------------------------------------------- | --------- | ---------- |
| Purpose + consent + recording start                        | ~3 min    | 3          |
| Background block: self-report (2a) + literacy warm-up (2b) | ~5–6 min  | 8–9        |
| Orientation video + hands-on tutorial                      | ~7–10 min | 15–19      |
| Task-briefing handoff (incl. video + reading)              | ~12 min   | 27–31      |
| Stance framing                                             | ~3 min    | 30–34      |
| Interaction                                                | ~35 min   | 65-70      |
| Final questions                                            | ~5 min    | 70-75      |
