# DB-Curator demo slide speaker notes

Audience: ML experts and scientists who want to understand how an agentic system can be useful in a scientific domain.
Suggested pace: 6 slides, 6-10 minutes total.

## Slide 1. DB-Curator
Main point: DB-Curator is not a chatbot for chemistry. It is an agentic workflow for building scientific database rows with evidence.

Suggested script:
DB-Curator starts from an open-ended scientific database request, such as building a topic-specific chemical database. The system searches the literature, proposes candidate compounds, and then verifies whether each candidate should be included. The key idea is that every accepted database row should have an auditable evidence trail, not just a plausible model-generated name.

Transition:
The first thing to understand is why this task is different from ordinary question answering.

## Slide 2. The task: build a database, not just answer a question
Main point: Scientific database construction requires coverage plus strict entry-level evidence.

Suggested script:
In database construction, the hard part is not simply producing chemical names. The hard part is deciding whether each chemical belongs in a specific user-defined database and whether the supporting evidence can be inspected later. This is why the task is a good fit for an agentic system. The agent has to search dynamically, track the verification state of each candidate, and stop with a clear decision: supported, rejected, or evidence-limited.

What to emphasize:
A standard LLM answer may be fluent, but a database row must be auditable.

Transition:
Now I will show how DB-Curator connects dynamic search to verification.

## Slide 3. How the workflow connects search to verification
Main point: The workflow has three connected functions: build literature, ground candidates, verify predicates.

Suggested script:
The left side of the figure shows how the system builds the literature and candidate pool. The right side shows the verification loop. The system first searches broadly using the user definition. Then candidate compounds trigger more specific searches. During verification, the Researcher proposes evidence and the Critique agent checks whether the evidence actually satisfies the rubric. If a predicate is missing, the system can search again or leave the case evidence-limited.

What to emphasize:
The corpus is not fixed before the run. It is built and revised as the agent discovers candidates and evidence gaps.

Transition:
This design matters because benchmarks are incomplete, so useful systems must recover known entries and also find valid missing entries.

## Slide 4. What the system produces: release-ready rows
Main point: DB-Curator recovers known benchmark entries and finds human-validated compounds absent from the benchmark.

Suggested script:
In the fixed-cohort release audit, DB-Curator produced 246 accepted rows out of 250. Of these, 178 overlapped known benchmark entries. More importantly, 68 were not in the benchmark but were judged valid by human experts. That is the application value: the system is not only matching existing lists. It can surface literature-buried additions while keeping evidence attached. The four errors are the small set that still require correction.

How to read the figure:
The figure separates name-level acceptance from evidence support. The key message is that accepted rows are useful only if they also carry auditable papers.

Transition:
That raises the most important question: how do we know the evidence is real?

## Slide 5. How every accepted output is verified
Main point: Verification is done at both paper level and predicate level.

Suggested script:
There are two checks. First, paper-level audit asks whether the cited item is a real primary paper and whether the recovered text contains the quoted span or equivalent local context. Second, predicate-level audit asks whether the paper supports the actual database definition. A compound may be real but still fail if it appears only as a solvent, reagent, or out-of-scope context. This is the main contrast with baseline generation: a baseline can name plausible compounds, but DB-Curator produces rows whose papers and evidence spans can be inspected.

How to explain the numbers:
2,166 out of 2,166 means every fixed-cohort primary-paper reference had quote or context support. 7,430 out of 7,453 is the benchmark-scale evidence audit. 11 out of 257 shows that direct generation produced very few usable references.

Transition:
Finally, I will summarize the ML lesson from the benchmark and critique-loop results.

## Slide 6. What this shows about agentic AI for science
Main point: The general contribution is dynamic evidence collection plus predicate-level correction.

Suggested script:
Across 1,887 candidate rows in five scientific domains, DB-Curator assigned 977 Confirmed labels. The critique loop mattered because it changed decisions. Forty-nine initially evidence-limited rows were rescued after more targeted evidence collection, while five premature Confirmed labels were tightened. For ML audiences, the lesson is that agentic systems are valuable when they create inspectable intermediate states and evidence contracts, not just when they retrieve more text.

Closing sentence:
DB-Curator shows one concrete pattern for applying agentic AI in science: dynamically build the evidence set, convert the user request into predicates, and verify each output before it becomes a database fact.
