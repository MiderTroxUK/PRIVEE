# MFE oral defence, speaking script

**John Hoarau, ESTIA 2026 · ALTEN Sud-Ouest, Direction de l'Innovation**
20 minutes of presentation, 10 minutes of questions. Delivered in English.

The spoken text is just under 3,000 words. At 140 words a minute, a rehearsed technical pace,
that is 21 minutes and the timings on each slide hold. To land inside 20, drop slides 8 and 12
on the day: together they are 126 words and neither carries a result. The three results slides
are 14, 15 and 16, and they are worth six of your twenty minutes. Protect them.

---

## Slide 1 · Title (0:00 to 0:34)

Good morning. My name is John Hoarau. For six months I have been at ALTEN Sud-Ouest, in the
Direction de l'Innovation, at the Toulouse Lab.

One number to open. Eight turns before a satellite manufacturer missed its delivery commitment,
the tool I built had already flagged it. At that moment its own manager was declaring an urgency
of zero point zero zero one.

That gap is what this mission is about.

---

## Slide 2 · Plan (0:34 to 0:49)

Five parts. The context and the problem. How the project was run. What I built. What the tests
returned, which is where the value is. Then the assessment.

---

## Slide 3 · The company and the programme (0:49 to 1:46)

ALTEN is a French engineering and technology consulting group, founded in 1988, present in more
than thirty countries. It sells engineering expertise rather than products.

One thing about that model matters here. A consulting group works for many clients at once, so
it sees the same difficulty appear in company after company. That is how a problem gets
recognised as belonging to the industry rather than to one customer.

I worked inside the Smart Green Supply Chain programme: lean, green, and predictive. My work
sits in the third. Its central artefact is DISCO, a serious game and digital twin covering
twenty-two suppliers. Earlier internships built the routing, the risk scoring, the carbon and
the transport. Not one of them computes urgency.

---

## Slide 4 · The problem (1:46 to 3:01)

A coordinator opens the week with a list of nodes and a finite amount of attention. Somewhere on
that list is the supplier that will cause next month's line stoppage. Nothing on the screen says
which one it is.

The twin computes the physical state of every node. What it never sees is the human who decides.
A buyer says a supplier is critical, a plant says a line is at risk, and the twin records the
consequence of those judgments without ever evaluating them.

That matters, because the declared signal is not neutral. Zhu, Yang and Hsee showed across five
controlled experiments that people favour imminent low-value tasks over distant high-value ones,
and that the bias survives being told about it. A twin that swallows that declaration as ground
truth inherits the bias.

So the research question. Can the gap between declared and computed urgency be measured reliably
enough, inside a working digital twin, to be acted upon? The word carrying the weight is
*reliably*.

---

## Slide 5 · The literature and the patent gap (3:01 to 4:19)

I looked in two places.

In the published research, six streams each settle something and each leave something open.
Deadline-driven value makes urgency time-varying, but stops at one task. The ripple effect makes
it propagate, but takes the node score as given. Rupture indicators are monitored one at a time.
Cognitive bias is quantified in the laboratory with no operational correction. Methods like AHP
capture a judgment cleanly but never compare it against anything. And digital twins are scored
on physical state, with their inputs assumed to arrive.

The patent record was more interesting. IBM in 2007 computes revenue at risk entirely from
measured inputs. Wipro in 2019 replaces those inputs with language, so the human narrates but is
never assessed. The most recent is a control tower where the operator receives decisions.
Fifteen years running away from the human declarant.

So the gap is specific. No system, published or patented, elicits a declared urgency, computes
its counterpart on the same node, and scores the difference against recorded outcomes.

---

## Slide 6 · Objectives and indicators (4:19 to 5:06)

Six objectives, each with an indicator chosen so it could be answered yes or no from an artefact
rather than from an opinion. Define the model and the score. Deliver a working, auditable
application. Propagate across tiers at realistic scale. Establish whether the signal predicts
recorded outcomes. Capitalise the research. And observe warehouse capacity from satellite
imagery instead of asking for it.

I flag the fourth now, because it changed the shape of the mission. Its indicator required the
signal to be compared against a trivial baseline. Holding to that clause turned a validation
step into the main contribution.

---

## Slide 7 · How the week ran (5:06 to 6:10)

The internship agreement prescribes Agile and Test and Learn, and I applied it literally. Monday
planning set the objective. Three scrums surfaced blockages within a day rather than a week. A
point with the programme director on Wednesday took the scientific decisions. A Friday
demonstration required something to be shown, not described.

Four contact points a week is heavy for research and development, and it was the most useful
organisational feature of the internship. It made it impossible to spend three weeks on an idea
that would not survive a reviewer.

Test and Learn means something only if things were abandoned. The first urgency model was a
single time-driven curve that rose as a deadline approached. It could not represent a node on
schedule but out of capacity. I dropped it in April, at a cost of three weeks.

---

## Slide 8 · Phases and milestones (6:10 to 6:43)

Ten phases, nine milestones, seven closed at the time of writing.

One decision matters more than the rest. The original plan gave the second half of the mission
to extending the model's scope. I reallocated it to validating what already existed, because an
unvalidated extension of an unvalidated model compounds the problem rather than advancing it.
That is why I can state a measured result today.

---

## Slide 9 · Two signals and a score (6:43 to 7:49)

Two signals, elicited independently, and a score that compares them.

On the left, declared urgency: at each node the operator compares four criteria pairwise through
AHP, which yields a consistency-checked weight per criterion. On the right, computed urgency,
aggregated from six indicator blocks.

The four declared criteria were chosen so each has a computed counterpart. Operational impact
mirrors performance and capacity. The time window mirrors the time block. Downstream dependencies
mirror the severity the propagation amplifies. Recoverability mirrors the recovery term of the
risk block. Without that correspondence the comparison would be between unrelated quantities.

The score is the distance between the two, on a zero to one hundred scale, and it is asymmetric.
False urgency costs one, hidden risk costs twice as much. That is the rule clinical triage has
applied for decades: under-triage costs a life where over-triage costs a queue.

---

## Slide 10 · Real urgency and the OR (7:49 to 9:16)

A moment on the aggregation, because it is the central modelling decision.

Read each of the six blocks as an independent cause that could on its own put the node in
trouble. The node is in trouble if the time block fires, or capacity fires, or any of the four
others does. The probability of that disjunction is one minus the probability that none of them
fires. The OR in the name is the logical connective, not an arithmetic operation.

Why it matters is on this slide. Node A has capacity failed at zero point nine and everything
else healthy. Node B has all six blocks at zero point two and nothing actually broken.

A weighted average ranks Node B first, and sends the coordinator to the node where nothing is
wrong, because five healthy blocks average away the one that failed. The probabilistic OR gives
Node A zero point nine two against zero point seven four, and ranks Node A first.

Same six numbers, opposite ranking. For a signal whose job is to catch the node about to fail,
non-compensatory behaviour is not a preference, it is a requirement.

---

## Slide 11 · Declared urgency and the gate (9:16 to 10:00)

Declared urgency is not a free-text estimate. It comes from pairwise comparisons.

The important part is the gate. A weight vector whose consistency ratio exceeds the threshold is
refused, and the operator is sent back to the most contradictory of their own comparisons.
Without it, an incoherent judgment would propagate as though it were a considered one.

One hypothesis, because everything downstream rests on it. The weekly review is taken at face
value, as a sincere report of what its author perceives. That is what makes the two signals
independent in source.

---

## Slide 12 · Propagation (10:00 to 10:22)

Both signals propagate in opposite directions. Declared urgency descends from the customer
towards suppliers, attenuated. Computed risk ascends the other way, amplified.

The asymmetry is physical. Demand pressure is what a customer transmits downwards. Physical risk
is what a supplier transmits upwards.

---

## Slide 13 · Architecture (10:22 to 11:29)

The model was delivered as SupplyScore, a standalone Python application over a per-node database
layer. Three decisions carry the engineering weight.

Every operation passes through a single orchestrating facade, so there is no second write path
into the domain, including from the administration interface. Every business write then crosses
a single mutation service that validates ranges, diffs against current state, and records the
author. The audit trail becomes a property of the architecture rather than a convention someone
has to remember. And persistence is split one database per node, so tenant isolation follows
from the storage layout rather than from a query filter someone could forget.

On the right, the application as the operator meets it. The weekly review commits as one signed
transaction. The explainability page reconstructs any score term by term, and it is what made
the next diagnosis possible from the application rather than by hand.

---

## Slide 14 · Result one, early warning (11:29 to 13:25)

Now the results. Four tests, all designed to try to break the tool rather than to show it
working.

The first campaign replays the 2020 to 2022 semiconductor shortage over nineteen turns across
eight nodes. Real urgency comes from public time series of the actual crisis, declared urgency
from the participants. Four of the eight go on to miss a commitment. At each turn I rank the
nodes by hidden risk and flag those above zero point one zero.

For six consecutive turns, before the crisis is visible, the signal flags exactly three nodes
and all three go on to miss. Precision one point zero zero. Recall zero point seven five. Zero
false alarms.

The worst-scoring node throughout is the satellite prime. Flagged from turn zero, it misses at
turn eight. Eight turns of warning, raised while its own manager declares zero point zero zero
one.

That flag does not come from a pessimistic declaration. It comes from an optimistic declaration
against a computed state that is not. A system aggregating only indicators would have ranked
that node by its indicators. A system collecting only declarations would have believed it.

From turn six precision falls to zero point five zero or below, and that is not a failure. The
crisis becomes public, everyone raises their urgency, and a measure defined as a difference
closes mechanically. It bounds where the measure applies: early warning, not crisis management.

I will state the limit before you ask. Eight nodes, four positives, one scenario. That precision
is an encouraging observation, not an established rate.

---

## Slide 15 · Result two, one block explained it (13:25 to 15:30)

The second question is different: turning that ranking into a probability attached to a named
week.

Scored against the outcome definition the system itself applies, the first version failed on
both axes. Discrimination indistinguishable from chance, and a Brier skill between minus three
point four and minus six point nine, meaning several times worse than a forecaster who announces
the base rate.

The reliability diagram localises it. Where the model announces a low probability it is right.
Where it announces a high probability it is wrong every time: twenty-one forecasts announcing a
mean of zero point nine four eight, and not one materialised.

Then the explainability layer gave me the cause, and it comes down to a count. Across three
hundred and twenty-eight indicator snapshots, the accumulated-delay field that the time block
reads was written a non-zero value exactly zero times. The event engine writes to capacity, cost
and failure probability, never to any quantity on the time axis. The block is blind by
construction, and because it drives the entire confident tail, so is the forecast.

The repair is a change to the event mapping, not to the mathematics. Lost production time is
additive: a four-week freeze costs four weeks whether the order is a tenth done or nine tenths
done.

On the same one hundred and twenty frozen forecasts, the Brier skill improves from minus one
point two seven eight to minus zero point six four six at one week. The calibration deficit is
roughly halved at every horizon. It is still negative everywhere, and I report it as such. On
discrimination I claim nothing: with twenty-six positives the interval is too wide to read.

---

## Slide 16 · Result three, the domain (15:30 to 17:51)

The third test is a negative result, and it is the one I would defend hardest.

A result measured on one scenario stays a property of that scenario. So I built a second chain,
an airframer's supply base, fifteen nodes over five tiers, with no exogenous events and milestone
truth computed from the indicators rather than written by me.

The adequacy signal scores a precision of zero point zero zero across nineteen turns, against a
base rate of zero point two zero. Worse than chance.

The reason is in the opening turn. The three suppliers that go on to miss declare the first,
second and fourth highest urgencies in the chain, before anything has visibly gone wrong. The
worst of them declares zero point nine eight two against a computed state of zero point six five
five.

Hidden risk is the positive part of computed minus declared, so when the declaration is the
higher of the two it clips to zero. Their hidden risk is exactly zero for nineteen turns, and no
threshold could have selected them. The free text says why: all three intend to delay informing
their customer until they have a recovery plan.

So here is the boundary, and it is the contribution I would put first. The tool measures
misperception, not non-disclosure. It finds the supplier who has misread their own situation. It
cannot find the one who has read it correctly and is managing what they say. Precision one on
the first chain and zero on the second do not contradict. Together they name the domain.

On the right, the fourth test. I wrote the cheapest thing that could replace the forecast layer,
a one-line ratio of weeks remaining to weeks required, and it beats five hundred Monte Carlo
trajectories at six horizons of eight. What the simulation buys is calibration. On this chain the
forecast layer is a calibration wrapper around a lead-time ratio.

---

## Slide 17 · The result nobody planned (17:51 to 19:06)

One measurement was not planned, and it has the widest consequences.

In the treatment arm, declarants are shown the system's own forecast immediately before
declaring. The scenario is frozen, so any difference belongs to the act of displaying them.

At first contact all eight declarants record an influence, and the direction is entirely
one-sided. Five revise downward, three are confirmed, not one revises upward. The critical event
lands two turns later. The pattern reproduced at fifteen declarants on the second chain.

The measurement an engineer should act on is the third. Reported influence falls from thirteen
declarants of fifteen to three by the final turn, and they give a measurable reason. Between
consecutive turns, on an unchanged node, the four-week probability moves by more than zero point
two zero on one node in ten, with a largest jump of zero point nine three. An advisory number
that jumps like that teaches its reader to stop looking. Disengagement is the rational response,
not negligence.

---

## Slide 18 · Objectives against outcomes (19:06 to 19:59)

Against the six objectives: all met, two with something added. The fourth is met with its domain
established, which is more than the indicator asked for. The sixth was reframed on the way,
because measurement rather than assumption established that docks cannot be counted from a nadir
view.

What the programme can now say about SupplyScore comes down to three statements. It detects
misperception, not non-disclosure. It is an early-warning tool that closes by construction once
a crisis is public. And its forecast layer buys calibration rather than short-horizon
discrimination.

Not one of those three was in the specification. Each came from a test built to find it rather
than to confirm the tool.

---

## Slide 19 · Limits, what comes next, what I take (19:59 to 21:13)

Four limits, and I will not soften them. The declarants were agents, not human consultants. The
positive class is small on both chains. The carbon block remains the least exercised for want of
node-level data. And every score depends on which outcome definition it is read against, which
no amount of extra data will fix.

For ALTEN, four actions in order of cost. Connect computed urgency to the quantity being
forecast, one afternoon on forecasts that already exist. Fill the indicators before calibrating.
Make the forecast state its own ignorance. And run the campaign with humans.

What I take is a method. Independence between two signals has to be designed before either of
them is, and before trusting a component, write the cheapest thing that could replace it and
score them against each other. The difficulty was never the mathematics. It sits at the two
joins: model to world, and output to the person who acts on it.

---

## Slide 20 · Close (21:13 to 21:20)

Thank you. I am happy to take your questions.

---
---

# Question and answer preparation

Ten minutes. Answer in three sentences and stop. The instinct to keep talking is what turns a
good answer into a weak one.

## The five hard questions

**"Precision of 1.00 on eight nodes is not a result. Why should we believe it?"**

You should not believe it as a rate, and I do not present it as one. Eight nodes, four
positives, three flagged, one scenario. What I claim is narrower: on this chain, over six
consecutive turns, the measure selected only nodes that later missed, and the flag preceded the
first miss by eight turns. Widening that base is the first of the three phases that close the
internship.

**"Your Brier skill is negative everywhere. Your forecast is worse than announcing the base
rate. Why keep it?"**

Correct, and I say so on the slide. I keep it for one measured reason: the baseline produces an
ordering and has no means of turning it into a probability, and its own Brier skill is minus
four point eight five against my minus one point six. The layer buys calibration, not
discrimination. If the programme only needs a ranking, the one-line ratio is the better
instrument and I would tell them to use it.

**"A one-line formula beats five hundred Monte Carlo trajectories. Does that not invalidate the
simulation?"**

On this chain, at short horizons, yes, and that is why I ran the test. The cause is nameable:
the autoregressive state never reaches the milestone term, so the scored quantity depends on a
lead-time draw and nothing else. It is a wiring defect, not a mathematical one, and the repair
is measurable on forecasts I already have frozen.

**"Precision 0.00 on the second chain. Your core contribution does not work."**

It does not work on that chain, and understanding why is the contribution. The three failing
suppliers declared the highest urgencies in the chain from the opening turn, so a measure
defined as computed minus declared clips to zero and cannot open. That separates two problems
that were being treated as one: misperception, which a questionnaire reaches, and
non-disclosure, which nothing that asks the supplier can reach. A future user needs to know
which of the two they have before deploying anything.

**"Your declarants are language models, not people. What is any of this worth?"**

Every behavioural claim applies to that population and I weakened all of them accordingly. What
the agents let me do is iterate: a full nineteen-turn campaign replays in an afternoon, so a
design flaw was found and re-tested the same day. The structural results, the blind time block
and the missing path to the milestone term, do not depend on who the declarant is. The human
campaign is the fourth item on the list for ALTEN.

## Five more you should expect

**"Why a noisy-OR rather than a weighted average?"**
Because a weighted average is compensatory. On the example on slide ten it ranks a node where
nothing has failed above a node whose capacity has collapsed. For a signal meant to catch the
node about to fail, that is the wrong behaviour.

**"Why price hidden risk at twice false urgency?"**
Because the two errors are not symmetric. Over-declaring consumes shared capacity and somebody
notices. Under-declaring generates no signal at all and surfaces only as a missed delivery.
Clinical triage has priced that asymmetry the same way for decades.

**"How do you know the two signals are really independent?"**
It is a stated hypothesis, not a proof: the weekly review is taken as a sincere report. I
designed for it rather than assuming it. Real urgency is fed from public time series, declarants
never see the computed value, and every result records which of the two could have reached the
other. The satellite workstream exists to put at least one indicator beyond the declarant's
reach entirely.

**"What would you do differently?"**
Two things. I would have scored the forecast layer against recorded outcomes far earlier, since
it took a few hundred lines and located the defect immediately where months of implementation
had not. And I would have written the outcome definition into the pre-registration alongside the
thresholds, having since measured that it moves the result by a factor of six.

**"Is this deployable?"**
Not as a probability, and not on a chain where suppliers manage their disclosure. As a weekly
ranking of where a coordinator should look, on a chain where the failing supplier is also the
one misreading its own state, and before a crisis becomes public: yes. That is exactly the
domain the third test established.

## Two from the ESTIA side

**"Where is the systems engineering in this?"**
The V-cycle is on the model: specification reviewed before implementation, then the campaign
designed before the system was finished, so the tests could not be written to fit the results.
Agile and Test and Learn ran the week inside that. Four things were abandoned, and the report
records each one with its cost.

**"What does this bring to your engineering training?"**
Three capabilities I did not have in April: supply chain modelling, software engineering built
to be handed on rather than to run once, and applied artificial intelligence from two directions
at once. But what I expect to reuse longest is a habit, not a skill. Before trusting a
component, write the cheapest thing that could replace it and score them against each other.

---

## Practical notes

Speak the numbers, do not read them off the slide. The three the jury should leave with are
0.001, eight turns of warning, and zero times across 328 snapshots.

Slide 16 carries two tests and is the densest of the deck. Take a breath before "So here is the
boundary", and slow down for the three sentences that follow. They are the contribution.

Never say "the tool works". Say what it does and where, and let the numbers carry the rest.
