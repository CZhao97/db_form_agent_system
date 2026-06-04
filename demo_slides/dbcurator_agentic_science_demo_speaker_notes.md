# DB-Curator demo slide speaker notes

Audience: ML experts and scientists who want to understand how an agentic system can be applied in a scientific domain.
Structure: cover slide plus 6 content slides. The cover is not counted in the 5-6 content-slide limit.
Suggested pace: 7-10 minutes total.

## Cover. DB-Curator
Main point: DB-Curator is not a chemistry chatbot. It is an agentic workflow for building scientific database rows with evidence.

Suggested script:
DB-Curator starts from an open-ended scientific database request, searches the literature, proposes candidate compounds, and verifies whether each candidate should be included. The key idea is that every accepted database row should have an auditable evidence trail, not just a plausible model-generated name.

Transition:
The first content slide explains why database construction is different from ordinary question answering.

## Content slide 1. The task: build a database, not just answer a question
Main point: Scientific database construction requires coverage plus strict entry-level evidence.

Suggested script:
In database construction, the hard part is not simply producing chemical names. The hard part is deciding whether each chemical belongs in a specific user-defined database and whether the supporting evidence can be inspected later. This is why the task is a good fit for an agentic system. The agent has to search dynamically, track the verification state of each candidate, and stop with a clear decision: supported, rejected, or evidence-limited.

What to emphasize:
A standard LLM answer may be fluent, but a database row must be auditable.

Transition:
Now I will show how DB-Curator connects dynamic search to verification.

## Content slide 2. How the workflow connects search to verification
Main point: The workflow has three connected functions: build literature, ground candidates, verify predicates.

Suggested script:
The left side of the figure shows how the system builds the literature and candidate pool. The right side shows the verification loop. The system first searches broadly using the user definition. Then candidate compounds trigger more specific searches. During verification, the Researcher proposes evidence and the Critique agent checks whether the evidence actually satisfies the rubric. If a predicate is missing, the system can search again or leave the case evidence-limited.

What to emphasize:
The corpus is not fixed before the run. It is built and revised as the agent discovers candidates and evidence gaps.

Transition:
This design matters because benchmarks are incomplete, so useful systems must recover known entries and also find valid missing entries.

## Content slide 3. What the system produces: release-ready rows
Main point: DB-Curator recovers known benchmark entries and finds human-validated compounds absent from the benchmark.

Suggested script:
In the fixed-cohort release audit, DB-Curator produced 246 accepted rows out of 250. Of these, 178 overlapped known benchmark entries. More importantly, 68 were not in the benchmark but were judged valid by human experts. That is the application value: the system is not only matching existing lists. It can surface literature-buried additions while keeping evidence attached. The four errors are the small set that still require correction.

How to read the figure:
The figure separates name-level acceptance from evidence support. The key message is that accepted rows are useful only if they also carry auditable papers.

Transition:
That raises the most important question: how do we know the evidence is real?

## Content slide 4. How every accepted output is verified
Main point: Verification is done at both paper level and predicate level.

Suggested script:
There are two checks. First, paper-level audit asks whether the cited item is a real primary paper and whether the recovered text contains the quoted span or equivalent local context. Second, predicate-level audit asks whether the paper supports the actual database definition. A compound may be real but still fail if it appears only as a solvent, reagent, or out-of-scope context. This is the main contrast with baseline generation: a baseline can name plausible compounds, but DB-Curator produces rows whose papers and evidence spans can be inspected.

How to explain the numbers:
2,166 out of 2,166 means every fixed-cohort primary-paper reference had quote or context support. 7,430 out of 7,453 is the benchmark-scale evidence audit. 11 out of 257 shows that direct generation produced very few usable references.

Transition:
Next, I will show that this is not just a few selected examples. We tested the same idea across five domains.

## Content slide 5. Benchmark-scale evidence and agentic correction
Main point: DB-Curator scales across several scientific database types, and the critique loop changes decisions rather than merely retrieving more text.

Suggested script:
Across 1,887 candidate rows in five scientific domains, DB-Curator assigned 977 Confirmed labels. The cited primary-paper references remained auditable at scale, with 7,430 of 7,453 references having quote or local-context support. The right side shows why the agentic loop matters. Forty-nine initially evidence-limited rows were rescued after targeted follow-up, while five premature Confirmed labels were tightened. This connects the benchmark result to the mechanism: the system uses evidence gaps to decide when to search again and uses critique to correct the verification state.

How to read the figure:
The left figure shows benchmark-scale outcomes and citation support. The right figure shows decision changes caused by critique and retrieval mode. Together, they show both performance and why the agentic loop matters.

Transition:
The final slide summarizes the general lesson for applying agentic AI in scientific domains.

## Content slide 6. Takeaway: a pattern for agentic AI in science
Main point: DB-Curator illustrates a general pattern: dynamic evidence construction plus predicate-level verification.

Suggested script:
There are three takeaways. First, this is a practical scientific application: the system builds database rows and shifts human work from searching the literature to auditing compact evidence trails. Second, the verification principle is strict: accepted rows require real papers and predicate-relevant support. Third, the machine-learning lesson is that the agentic value is not fluent generation. It is dynamic evidence construction, explicit state tracking, and critique-driven correction.

Closing sentence:
DB-Curator shows one concrete pattern for applying agentic AI in science: dynamically build the evidence set, convert the user request into predicates, and verify each output before it becomes a database fact.
