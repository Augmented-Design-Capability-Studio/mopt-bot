# QuickBite — Operational Reference

A printed handout the participant keeps alongside the briefing video (`BRIEFING_VIDEO_SCRIPT.md`). Contains scenario data — zones, vehicles, orders, traffic times — for look-up during the session. Operational priorities are conveyed in the video and through the participant's conversation with the AI; this document is **not** a problem specification.

## Editor note (not for participants)

This reference deliberately omits anything that pre-formalizes the optimization problem: no enumeration of cost-function components, no "soft / hard constraint" labels, no measurement definitions (e.g. how lateness is counted), no "stochastic noise" framing, no inferences from facts to goals (e.g. "drivers are salaried, so we want fairness"). Participants are given the **operational facts and data** here and the **operational priorities** in the video, and they translate both into goals/rules in their own language with the agent. See `STUDY_DETAILED_PLAN.md` §1 (*Observe operational-to-formal translation*). **Future edits:** if you find yourself adding a sentence that tells the participant which factor to weight, or labels a rule as soft / hard, soften it back into a fact-only statement — that translation work is what we're studying.

---

## 1. Service area

QuickBite operates from a **central depot** with five delivery zones around the city.

| Idx | Zone | Notes |
|-----|------|-------|
| 0 | Depot (central) | Vehicles start and end the day here, except Eve |
| 1 | A — Riverside | — |
| 2 | B — Harbor | — |
| 3 | C — Uptown | — |
| 4 | D — Westgate | Roadworks 08:00–12:00 (extra time for any trip in or out) |
| 5 | E — Northgate | — |

*(Zone map sketch — to insert if the printed copy is illustrated)*

---

## 2. Travel times

Below is the estimated base travel time between zone centers, in minutes, under normal traffic conditions. The travel time can be generally treated as symmetric; in-zone travel is treated as negligible.

|       | Depot | A | B | C | D | E |
|-------|:-----:|:-:|:-:|:-:|:-:|:-:|
| **Depot** | 0  | 12 | 18 | 25 | 30 | 22 |
| **A**     | 12 |  0 |  8 | 15 | 20 | 14 |
| **B**     | 18 |  8 |  0 | 10 | 18 | 12 |
| **C**     | 25 | 15 | 10 |  0 |  9 | 11 |
| **D**     | 30 | 20 | 18 |  9 |  0 |  7 |
| **E**     | 22 | 14 | 12 | 11 |  7 |  0 |

The system looks up actual travel time from city traffic data; what's on the road varies with time of day and conditions.

### Time-of-day periods

| Time          | Period         |
|---------------|----------------|
| 07:00–09:30   | Morning peak   |
| 09:30–11:30   | Normal         |
| 11:30–13:00   | Lunch surge    |
| 13:00–16:00   | Normal         |
| 16:00–18:00   | Evening peak   |

Westgate (Zone D) roadworks add extra time to any trip in or out of D between **08:00 and 12:00**, regardless of period.

---

## 3. The fleet

| ID | Driver | Capacity (units) | Start zone | Shift start | Max shift |
|----|--------|:---------------:|:----------:|:-----------:|:---------:|
| 0  | Alice  | 22              | Depot      | 08:00       | 8h        |
| 1  | Bob    | 20              | Depot      | 08:00       | 8h        |
| 2  | Carol  | 20              | Depot      | 09:00       | 8h        |
| 3  | Dave   | 22              | Depot      | 08:00       | 8h        |
| 4  | Eve    | 20              | Northgate (E) | 09:30    | 8h        |

Drivers are salaried. Trucks are loaded once at the depot at the start of the day. A copy of the fleet info is in `DRIVER_INFO.csv` for upload.

### Driver notes (from the dispatcher)

- **Alice** — would rather avoid Westgate, especially in the morning.
- **Carol** — gets uncomfortable when a route is mostly express stops.
- **Dave** — gets noticeably less sharp after about 6.5 hours on shift.
- **Bob, Eve** — no specific notes.

---

## 4. Tomorrow's orders

30 orders total. Each order has a delivery zone, a size in capacity units, a priority (express or standard), a time window during which the driver should arrive, and a service time.

If a driver arrives before the time window opens, they wait until it opens, then perform the service.

### Order list

| ID  | Zone | Size | Priority | Window open | Window close | Service |
|-----|:----:|:----:|:--------:|:-----------:|:------------:|:-------:|
| O00 | E | 1 | standard | 09:30 | 12:00 | 10 min |
| O01 | B | 4 | standard | 10:00 | 12:30 | 10 min |
| O02 | A | 1 | standard | 08:30 | 10:30 | 10 min |
| O03 | A | 2 | standard | 12:00 | 13:30 | 10 min |
| O04 | E | 4 | standard | 10:30 | 12:30 | 10 min |
| O05 | A | 3 | standard | 08:30 | 11:00 | 10 min |
| O06 | D | 4 | **express**  | 08:00 | 09:30 | 15 min |
| O07 | B | 2 | standard | 13:00 | 14:00 | 10 min |
| O08 | D | 4 | standard | 14:00 | 16:00 | 10 min |
| O09 | A | 1 | standard | 10:30 | 12:30 | 10 min |
| O10 | A | 5 | standard | 10:00 | 11:30 | 10 min |
| O11 | C | 3 | standard | 08:30 | 10:00 | 10 min |
| O12 | B | 2 | standard | 11:30 | 14:00 | 10 min |
| O13 | C | 4 | standard | 09:30 | 11:00 | 10 min |
| O14 | E | 2 | **express**  | 13:30 | 14:30 | 15 min |
| O15 | E | 5 | **express**  | 10:00 | 11:00 | 15 min |
| O16 | A | 5 | **express**  | 11:30 | 14:00 | 15 min |
| O17 | A | 2 | standard | 09:30 | 10:30 | 10 min |
| O18 | A | 2 | standard | 09:00 | 10:00 | 10 min |
| O19 | D | 3 | standard | 08:00 | 10:30 | 10 min |
| O20 | B | 1 | standard | 13:30 | 15:30 | 10 min |
| O21 | D | 3 | standard | 09:30 | 11:30 | 10 min |
| O22 | D | 4 | standard | 09:30 | 10:30 | 10 min |
| O23 | B | 3 | standard | 12:30 | 14:30 | 10 min |
| O24 | B | 5 | standard | 13:30 | 14:30 | 10 min |
| O25 | D | 3 | **express**  | 08:00 | 10:00 | 15 min |
| O26 | A | 4 | standard | 09:30 | 10:30 | 10 min |
| O27 | E | 1 | standard | 12:00 | 13:30 | 10 min |
| O28 | C | 4 | standard | 13:30 | 15:00 | 10 min |
| O29 | A | 1 | standard | 12:00 | 14:00 | 10 min |

A copy of the order list is in `ORDERS.csv` for upload.

---

## 5. Operational facts

- Every order on the list must be served. Orders are not skipped.
- Trucks are loaded once at the depot at the start of the day; drivers do not return to the depot to reload.
- Shift duration is capped at 8 hours per driver.
- Occasionally a specific order is required to go with a specific driver (relationship or customer-request reasons). When this applies for a given day, the dispatcher will note it directly.
