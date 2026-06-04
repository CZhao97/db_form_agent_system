# DB-Curator demo slide speaker notes

Audience: ML experts and scientists who want to understand how an agentic system can be useful in a scientific domain.

Structure: the cover page is not counted. The deck has six content slides.

## Cover. DB-Curator

Opening script:
Today I will introduce DB-Curator, an agentic system for scientific database construction. The key idea is that the system does not simply answer a question or summarize papers. It builds candidate database rows and verifies whether each row is supported by inspectable evidence.

Transition:
Before the method, I want to clarify why this is a good problem for agentic AI.

## Content slide 1. Background: databases make science reusable

Main point: scientific databases are important, but specialized database construction is still slow because every row needs scope, interpretation and provenance.

Suggested script:
Scientific databases convert scattered literature into reusable knowledge. In practice, specialized databases are still built by expert curation. Experts define the topic scope, search papers, interpret the experimental context, and record evidence. The bottleneck is not only finding papers or chemical names. The real bottleneck is deciding whether each candidate deserves to become a database row.

How to explain the slide:
Walk left to right. The four boxes are the human curation workflow: define scope, search papers, interpret context, and record evidence. The takeaway is that a database row is a scientific decision, not just an extracted name.

Transition:
This is why ordinary extraction or ordinary RAG is not enough.

## Content slide 2. Problem: extraction and RAG do not decide database membership

Main point: a mention is not a database entry.

Suggested script:
In a paper, the same chemical name can play very different roles. It may be the target compound, a reagent, a precursor, a solvent, a contaminant, or just a comparison. Standard extraction and RAG can find mentions and generate answers, but database construction requires a row-level decision. The citation must support the exact predicate needed by the database definition. If evidence is missing, contradictory to the scope, or off-topic, the row label should change.

How to explain the slide:
Use the left box for what extraction and RAG usually do. Use the right box for what a database-building system must do. Emphasize the sentence at the bottom: these are not wording problems; they are label-changing events.

Transition:
DB-Curator addresses this by turning the user request into an evidence contract.

## Content slide 3. Core idea: turn user intent into an evidence contract

Main point: DB-Curator makes database construction agentic by coupling dynamic literature construction to predicate-state verification.

Suggested script:
DB-Curator first clarifies the user request into a rubric. Then it dynamically constructs the literature set. Search is not fixed at the beginning; it changes when new candidates or evidence gaps appear. Candidate compounds are grounded and filtered before expensive verification. Finally, the Researcher agent finds evidence and the Critique agent checks whether each required predicate is supported and whether any exclusion criterion is triggered.

How to explain the states:
Supported means the cited evidence satisfies the predicate. Unresolved means the system has not found enough evidence. Exclusion means the evidence shows the candidate is out of scope. Exhausted means the search budget is spent without enough support. A row is accepted only when required predicates are supported and no exclusion criterion is triggered.

Transition:
Here is what this looks like in a concrete scientific application.

## Content slide 4. Application demo: DBP database construction

Main point: the workflow can be explained through a concrete DBP curation task.

Suggested script:
Suppose the user asks for a database of experimentally confirmed disinfection byproducts. The system refines this into a DBP rubric: water-relevant disinfection or oxidation context, formation from disinfectant or oxidant reaction with relevant precursors, and structural confirmation in peer-reviewed studies. Then we can follow one concrete candidate, NDMA. The Researcher retrieves DBP and chloramination evidence. The Critique agent asks whether the cited paper supports formation, not merely occurrence or toxicity. If the predicate is still incomplete, the next search targets formation plus analytical confirmation.

How to explain the output:
For each compound, the output is not just a name. In this mini-run, the row becomes Confirmed only when the formation, matrix and structural-evidence predicates are supported. The final row contains compound identity, label, predicate states, evidence snippets, citations and search logs. This is the key application story for scientists: the agent run produces an auditable row, not just an answer.

Transition:
The next slide explains how we verify that those outputs are reliable.

## Content slide 5. Verification: how do we know the output is reliable?

Main point: trust comes from paper-level and predicate-level audit, not from model confidence.

Suggested script:
We evaluate reliability at two levels. First, paper-level audit asks whether the cited item resolves to a real primary paper and whether the paper contains the quoted span or equivalent local context. Second, predicate-level audit asks whether the paper supports the actual rubric predicate. Mentioning the same compound is not enough. If a paper only shows the compound as a reagent, solvent, precursor or off-scope context, that can block release.

How to explain the numbers:
DB-Curator had 2,166 out of 2,166 fixed-cohort references with quote or context support. At benchmark scale, 7,430 out of 7,453 primary-paper references were auditable. By contrast, zero-shot direct generation yielded only 11 usable references out of 257. The key message is that the output is trusted because the cited paper and predicate can be inspected.

Transition:
Finally, I will summarize the strongest results and the ML lesson.

## Content slide 6. Evidence-grounded agents outperform plausible generation

Main point: the strongest result is evidence grounding, not just name generation or high label counts.

Suggested script:
There are three results to remember. First, in fixed-cohort release audits, DB-Curator produced 246 release-ready rows out of 250, including 68 benchmark-missing entries that were judged valid by human experts. Second, at benchmark scale, it evaluated 1,887 candidates across five domains: DBPs, blood exposome chemicals, drugs, endogenous metabolites and microbial natural products. It assigned 977 Confirmed labels and maintained auditable support for 7,430 of 7,453 primary-paper references. Third, the critique loop changed decisions: 49 evidence-limited rows were rescued to Confirmed, five premature Confirmed labels were tightened away, and 51 of 54 changed decisions were judged right by human inspection.

Closing message:
The value of agentic AI in this scientific setting is not fluent generation. It is dynamic evidence construction, explicit state tracking, and critique-driven correction. Practically, humans audit compact evidence trails and edge cases instead of searching every paper from scratch.
