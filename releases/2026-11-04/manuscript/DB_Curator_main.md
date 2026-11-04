**DB-Curator: on-demand scientific database construction through rubric-guided deep research**

**Chen Zhao<sup>1,2</sup>**, **Botao Liu<sup>1</sup>, Xiaoxiao Li<sup>2,</sup>\*, Tao Huan<sup>1,</sup>\***

1.  Department of Chemistry, Faculty of Science, University of British Columbia, Vancouver Campus, 2036 Main Mall, Vancouver, British Columbia, V6T 1Z1, BC, Canada

2.  Department of Electrical and Computer Engineering, University of British Columbia, Vancouver Campus, 3110-2332 Main Mall, Vancouver, V6T 1Z4, BC, Canada

\* Author to whom correspondence should be addressed:

Dr. Tao Huan

Tel: (+1)-604-822-4891

E-mail: <thuan@chem.ubc.ca>

Website: <https://huan.chem.ubc.ca/>

Dr. Xiaoxiao Li

E-mail: xiaoxiao.li@ece.ubc.ca

Website: https://xxlya.github.io/

**Abstract**

Constructing scientific databases requires finding evidence scattered across the literature and deciding whether each candidate meets topic-specific requirements. We present DB-Curator, a deep-research system that translates a user-approved scientific scope into an explicit acceptance rubric. The rubric guides compound discovery, directs searches towards unresolved criteria and links database decisions to evidence. Across five chemical domains, DB-Curator constructed 1,000 retained entries with 7,689 source-located paper citations. Expert review with system labels hidden from the reviewer recorded agreement with 241/250 construction outputs and 1,870/1,886 benchmark decisions. Across repeated comparisons, Confirmed-label yield rose from 32.5% with frozen retrieval to 43.2% with adaptive research. Starting from identical evidence states, criterion-directed Critique prompted more follow-up research and Confirmed outputs than general review. DB-Curator connects scientific scope, adaptive literature research and inspectable row-level decisions for on-demand chemical database construction.

Scientific databases make experimental findings searchable, comparable and reusable across studies. Resources such as HMDB, the Blood Exposome Database and curated disinfection-by-product databases demonstrate the scientific value of bringing scattered chemical knowledge together.<sup>1-3</sup> Their usefulness depends on stable identities, clear inclusion criteria and traceable evidence for individual entries.<sup>4-6</sup> Building a specialized database requires curators to define its scope, search the literature, identify candidates and interpret experimental context before accepting each entry. Repeating this work for emerging research questions is laborious, particularly when the relevant evidence is distributed across many papers. Automating database construction therefore requires both broad candidate discovery and evidence that justifies each inclusion decision.

Advances in literature infrastructure and scientific language processing provide a foundation for this task. Resources such as Europe PMC, S2ORC and OpenAlex make publications and metadata accessible at scale, while document-processing tools support structured access to scientific text.<sup>7-12</sup> Chemical text-mining systems and domain-adapted models support entity recognition and normalization.<sup>13-18</sup> Large language models further enable extraction of structured relationships and experimental information from scientific passages.<sup>22,23</sup> Together, these capabilities expand the literature that automated curation workflows can examine.

Extracting a chemical entity, however, does not establish whether it belongs in a particular database. A compound may appear as a reaction product, reagent, precursor, contaminant or comparison standard. Membership depends on the requested scientific scope and on relationships involving formation route, sample matrix, biological origin or analytical identification. Establishing these relationships can require information distributed across a document, beyond the passage containing the chemical name.<sup>19-21</sup> For example, detection in human blood and production within the human body answer different curation questions. Evidence must therefore support the specific relationship required for inclusion, with attribution that allows the underlying claim to be checked.<sup>25-27</sup>

These requirements make database construction a task of evidence-dependent decision-making for each candidate. Retrieval-augmented scientific question answering can identify relevant passages and synthesize supported answers.<sup>34</sup> Constructing a database additionally requires a consistent acceptance rule for every proposed entry. Missing evidence, contrary evidence and evidence from an irrelevant context must lead to distinct decision states. Moreover, an unresolved inclusion criterion should guide the next search rather than simply terminate assessment. The central challenge is to connect scientific scope, adaptive evidence acquisition and database membership through explicit, inspectable criteria.

Scientific agents connect iterative search, reasoning and review.<sup>32,33,39,40</sup> DeepEvidence organizes biomedical evidence exploration and synthesis around an evolving evidence graph, whereas LitMOF validates literature and crystallographic records to repair and expand metal-organic framework databases.<sup>54,55</sup> These systems address evidence synthesis and structure-specific curation, respectively. DB-Curator is designed for on-demand compound database construction without a predefined curation topic. It separates the shared discovery and verification workflow from topic-specific scientific requirements, which are expressed in a topic definition and acceptance rubric proposed by the agent and refined with the user until approval. Changing these inputs allows the same workflow to serve different chemical domains without redesigning its agents. For each candidate, the rubric defines both the evidence required for database membership and the unresolved questions that guide follow-up searches.

Here we present DB-Curator, a multi-agent system for on-demand scientific database construction. The system translates a user-approved scientific scope into an explicit acceptance rubric shared across candidate discovery, evidence acquisition and row assessment. A Researcher agent gathers candidate-specific evidence, while a Critique agent reviews its interpretation and can request follow-up on unresolved criteria. A decision contract checks recorded criterion states and citation links before release. Each output connects the candidate’s identity, evidence and decision, allowing curators to inspect the basis for inclusion or continued uncertainty. We evaluate this approach across five chemical domains through open-ended construction, benchmark verification, expert review, component comparisons and evidence-linked case analyses.

**Results**

**A shared rubric connects scientific scope, search and row decisions**

DB-Curator uses a shared acceptance rubric to connect scientific scope, evidence acquisition and database membership decisions. Derived from a user-approved topic definition, the rubric specifies the evidence required for inclusion, the findings that trigger exclusion and optional guidance for interpretation. Each candidate is assessed against these criteria, making gaps in the available evidence explicit. Unresolved criteria then guide further searches, and the evidence acquired updates the assessments used to determine the candidate’s status.

The rubric carries these requirements through candidate discovery and verification (Fig. 1). Topic-centred literature retrieval, chemical entity recognition and contextual filtering identify candidates within the approved scope. For each candidate, the Researcher agent gathers evidence and updates criterion assessments through iterative search and reading. The Critique agent reviews those assessments and can request targeted follow-up on an unresolved requirement. Before release, the controller checks the recorded criterion states and citation links. Each output preserves these assessments alongside the compound identity, cited passages, decision label and release status, allowing the decision to be inspected. The complete workflow and rubric specifications appear in Supplementary Fig. 1 and Supplementary Notes 1 and 2.

![image](figures/workshop_style/Figure1.pdf)

**Figure 1 Conceptual overview of DB-Curator.** The shared Topic Definition and Acceptance Rubric connect candidate scope, evidence targets and row conditions across the four stages. Online and offline literature sources supply candidates, and the Researcher agent iteratively gathers evidence for a provisional decision. Critique reviews the interpretation against the rubric and can request targeted follow-up. Checkmarks summarize the review questions. The output-box labels “unresolved” and “limited evidence” abbreviate Suspected and Insufficient Direct Evidence, respectively. This overview summarizes the main stages. Supplementary Fig. 1 shows the complete workflow.

**Open-ended construction produces evidence-linked databases**

We asked DB-Curator to build databases from open-ended topic requests in five domains: disinfection by-products (DBPs), blood-exposome chemicals, drugs, human endogenous metabolites and microbial natural products. Construction continued until each topic contained 200 distinct retained entries. Prediction and release were recorded separately: the last Researcher report supplied the prediction label, while database retention required an approved Confirmed release decision, acceptance under the topic rubric and successful source checks for every cited paper.

The resulting databases contained 1,000 entries after processing 2,122 candidate records (Fig. 2a). Processing effort ranged from 1.61 records per retained row for blood-exposome chemicals to 3.54 for DBPs. The accumulation curves show how these differences build up as each database approaches 200 entries. The complete candidate inventory is provided in Supplementary Note 7.

The processed records represented 861 distinct identities matched to the five benchmark resources. Of these, 594 entered the retained databases (69.0%, Fig. 2b). Topic-level retention ranged from 60.1% for endogenous metabolites to 79.2% for drugs. A further 406 retained entries had no established benchmark match, ranging from 14 blood-exposome chemicals to 165 microbial natural products. Their accompanying passages provide a starting point for curators to assess possible additions to existing resources.

Zero-shot generation readily named familiar compounds, with 749/1,000 proposals matched to benchmark records under the same identity policy (Fig. 2c). However, none of its 991 paper citations could be matched to attributed text in a title- and identifier-compatible source. The 1,000 retained DB-Curator entries carried 7,689 paper citations with both source identity and attributed text verified (Fig. 2d). This traceability is enforced during release: every cited paper must pass the source check before its row enters the database.

Expert review with system labels hidden from the reviewer assessed topic membership and whether the supplied citations supported each entry. The construction audit covered the complete processing pools of five runs, each stopped at 50 retained entries. The reviewer endorsed 241/250 retained entries (96.4%). Agreement was 45/50 for DBPs, 50/50 for blood-exposome chemicals, 50/50 for drugs, 47/50 for endogenous metabolites and 49/50 for microbial natural products (Fig. 2e). Five of the nine entries not accepted were topic-relevant classes rather than individual compounds. The other four objections concerned a precursor, topic scope or isotope identity. Review of all 109 non-Confirmed candidates identified two missed qualifying compounds, both in the blood-exposome task. Across these 359 evaluated candidates, precision was 241/250 (96.4%) and processed-pool recall was 241/243 (99.2%, Fig. 2e and Supplementary Table 4). The corresponding zero-shot audit, with system labels hidden from the reviewer, agreed with 248/250 inclusion proposals (99.2%).

![image](figures/nature/Figure2.pdf)

<span> **Figure 2 Database construction, citation traceability and expert review.** (a) Accumulation of retained entries towards the 200-entry target per topic, alongside total records processed and records processed per retained entry. (b) Retained benchmark identities divided by encountered benchmark identities. (c) Benchmark-matched proposals among 200 entries per topic and method. Darker bars denote DB-Curator and lighter bars denote zero-shot. (d) Citation instances with a matched publication and attributed text verified against full text or abstracts, allowing formatting and minor OCR differences. Database/tool records are excluded. (e) Precision from expert review of 50 retained entries per topic and method, with system labels hidden from the reviewer. The five reviewed DB-Curator runs stopped at 50 retained entries each. Recall includes all 109 non-Confirmed candidates, completing their 359-candidate processing pool. Colored segments count qualifying retained entries. Rose denotes objections for precision and missed qualifying candidates for recall. Overall precision is 241/250 (96.4%) and 248/250 (99.2%). DB-Curator processed-pool recall is 241/243 (99.2%). </span>

**Evaluation of benchmark-listed candidates**

To separate discovery from assessment, we supplied 1,887 benchmark-listed compounds directly to the agentic verification loop: all 687 curated DBPs and 300 sampled records from each other domain. The final Researcher reports classified 975 (51.7%) as Confirmed: 330 DBPs, 68 blood-exposome chemicals, 213 drugs, 125 endogenous metabolites and 239 microbial natural products (Fig. 3a). The rubric, rather than benchmark membership, guides these predictions. A drug listed in DrugBank still requires evidence for pharmacological activity, and an HMDB metabolite still requires evidence for human production. The blood-exposome rubric jointly requires detection in human blood and an environmental origin.

The remaining predictions were Insufficient Direct Evidence (664), Suspected (114), Explicit Negative Evidence (108), Out of Scope Matrix or Context (14) and Indirect or Class-Level Only (12) (Fig. 3a). These categories distinguish missing evidence from contrary evidence, giving curators a prioritized list for follow-up. Across the benchmark evaluation, 7,624 of 7,647 literature references corresponded to real scholarly works (99.7%), while 23 were judged incorrect. Attributed text was located for 7,246 reference instances. Researcher-Confirmed predictions contained 4,169 literature references, of which 3,964 were source-located. The complete citation inventory is summarized in Supplementary Table 1.

Verification also depends on access to the relevant experimental text. Subscription-only articles may expose an abstract but withhold the methods, results or supplementary tables needed to establish a compound’s identity, origin or sample matrix. Institutionally licensed or author-provided full text can therefore be needed to resolve criteria left open by abstract-only retrieval.

Expert review of the archived benchmark outputs, with system labels hidden from the reviewer, agreed with 1,870/1,886 decisions (99.2%) on topic membership and citation support (Fig. 3b). Among the reviewed Confirmed predictions, 98.9% were endorsed (Methods and Supplementary Note 9).

Evaluations ending without confirmation consumed most of the computation, accounting for 66.7% of recorded tokens. Their median consumption was 375,023 tokens, 3.2 times the 118,650 used for Confirmed predictions (Fig. 3c). They also more often returned for additional research and review (70.9% versus 33.4%), consistent with continued efforts to resolve evidence gaps. Token use tracked runtime across candidates, with a Pearson correlation of 0.91 on logarithmic scales (Fig. 3d). Topic median runtimes ranged from 4.6 to 8.4 minutes (Supplementary Fig. 3).

![image](figures/nature/Figure3.pdf)

<span> **Figure 3 Agentic verification of benchmark-listed compounds.** (a) Final Researcher predictions for 1,887 benchmark-listed candidates. Segment labels give counts, and the right column gives Confirmed counts and fractions. The lightest red segment combines out-of-scope and class-level outcomes. (b) Expert agreement on topic membership and evidence support for 1,870/1,886 reviewed outputs (99.2%), with system labels hidden from the reviewer. Panel b summarizes the expert-reviewed archived outputs. (c) Independently normalized log-token densities for 1,887 candidates: 975 Confirmed and 912 other outcomes. Dashed lines mark medians. (d) Token use versus runtime for 1,887 candidates with both measurements. Hexagonal-bin color denotes candidate count, and Pearson correlation is calculated after log\(_{10}\) transformation (\(r=0.91\)). Both axes are logarithmic, and each observation is linked to its corresponding evaluation run. Topic-specific runtimes appear in Supplementary Fig. 3. </span>

**Evidence acquisition increases Confirmed-label yield**

To compare the stages of evidence acquisition, we evaluated four configurations on 100 randomly sampled candidates from each topic benchmark. The same candidate subsets were used for all configurations and all three repeats. Zero-shot labeling used no retrieval, and Static RAG classified one frozen evidence bundle. Adaptive search used the Researcher agent state immediately before the first Critique call, and Full used the last Researcher label after the verification loop. Across 1,500 observations per configuration, Confirmed totals were 317 (21.1%), 488 (32.5%), 648 (43.2%) and 673 (44.9%), respectively (Fig. 4a).

Confirmed-label yield was higher with adaptive research than with a frozen evidence bundle. DBP confirmations rose from 15.7 to 43.7 per 100 candidates and microbial natural products from 55.0 to 68.7 (Fig. 4a). Adaptive search queries the criteria that remain unresolved. Observed paired differences were +11.40 percentage points for Frozen–Zero, +10.67 for Adaptive–Frozen and +1.67 for Full–Adaptive (Fig. 4b and Supplementary Table 6). Critique also requested explicit evidence for the relationships required by the rubric. The case studies show clearer organic-precursor and secondary-metabolite support after review, even when the label stayed Confirmed (Fig. 6a,b).

Across three repeats, 76.0% to 90.0% of candidates retained the same binary prediction within each topic (Fig. 4a). These rates summarize repeat consistency on the same randomly sampled candidates within each topic. With GPT-5-mini or Gemini 2.5 Flash as Critique, final Researcher reports contained 673 and 647 Confirmed predictions, respectively (Fig. 4c). The corresponding increases from the pre-Critique Researcher state were 25 and 28 predictions. A positive aggregate change therefore occurred under both model configurations, including when Researcher and Critique used the same model. Across the end-to-end reruns, 1,302/1,500 paired binary predictions agreed (86.8%).

Mean recorded token use was 518 for zero-shot labeling, 3,871 for frozen retrieval and 232,118 for Full, with mean runtimes of 29.0 and 271.1 seconds for frozen retrieval and Full (Supplementary Fig. 2). The observed yield gains accompany deeper evidence search and greater computational investment.

**Feedback organization changes research activity and decision yield**

To test whether organizing feedback around individual criteria changes subsequent research, we compared three Critique designs from identical saved Researcher agent states. A provided criterion-directed feedback. B gave general review with the same rubric and criterion assessments. C gave general review without explicit rubric items or criterion assessments. The Researcher agent retained the full topic definition and rubric in every arm. The arms shared the same models, tools, release rules and computational allowances, including token, model-request and cost ceilings. Each permitted up to three subsequent Researcher rounds and three Critique rounds. This design compares how feedback organizes further research within a common resource envelope. Each arm included the same 100 candidates, 20 per topic (Fig. 4d).

Criterion-directed feedback produced 58 Confirmed labels, compared with 48 under general review and 51 when explicit rubric information was withheld from Critique (Fig. 4d). It also prompted more follow-up research: A used 1.62 Researcher agent rounds per candidate versus 1.08 and 1.07, and 209,138 tokens versus 172,190 and 148,995 (Fig. 4d). Mean newly recorded source-file counts were 148.9, 67.9 and 74.7. Within the shared resource ceilings, criterion-directed feedback made greater use of the available computation and produced more Confirmed outputs.

![image](figures/nature/Figure4.pdf)

**Figure 4 Evidence-acquisition stages, repeat stability and feedback-guided research.** Panels a,c use the same 500 candidates (100 per topic) in three repeats. (a) Confirmed labels per 100 candidates, reported as mean \(\pm\) sample s.d. Colored strips use a common 0–100 scale. The pooled row summarizes 1,500 candidate–repeat observations. Full range is the minimum–maximum across repeats. Same label is the fraction receiving an unchanged binary prediction in all three repeats. (b) Observed paired differences between adjacent stages, in percentage points. (c) Adaptive and Full means \(\pm\) sample s.d. and their mean difference under GPT-5-mini (GPT) or Gemini 2.5 Flash (Gemini) as Critique. Each configuration was rerun end to end. (d) Same-state feedback comparison. A: criterion-directed feedback. B: general review with the same rubric and criterion assessments. C: general review without those explicit Critique inputs. Researcher inputs remain complete. Panel d uses all 100 assigned candidates per arm. Resource values are post-fork means, and cost is the accounted US-dollar cost. Source-file counts include separate retrieval artifacts from the same paper. Repeated-ablation resource use appears in Supplementary Fig. 2.

**Criterion profiles across verification outcomes**

Criterion-level records show which recorded assessments distinguish Confirmed predictions from other outcomes (Fig. 5a). A recorded criterion indicator denotes an item marked solved or scored at least 0.5, including resolution through supporting or disqualifying evidence. Across all 1,887 benchmark candidates, context-specific indicators differed most between outcome groups: treatment attribution for DBPs, blood and environmental context for exposome chemicals, human biochemical function for endogenous metabolites and structural evidence for microbial natural products. Generic identity indicators were common in both groups. Confirmed records concentrate near the maximum number of recorded criterion indicators, whereas other outcomes span a wider range (Fig. 5b). Together, these profiles describe how scientific context appears in the recorded assessments across domains (Supplementary Note 12 and Supplementary Fig. 4).

![image](figures/nature/Figure5.pdf)

**Figure 5 Criterion-specific separation and row-level evidence-state distributions.** (a) The three largest signed between-group separations and the smallest separation per topic. Points show the fraction marked solved or scored at least 0.5 among Researcher-Confirmed predictions (blue circles) and other predictions (open red diamonds). Connecting lines and right-side values show differences in percentage points. M, X and O identify mandatory, exclusion and optional roles. Drug modality is summarized as one ANY condition. (b) Number of recorded criterion indicators per row, stacked by final Researcher label using the categories and colours of Fig. 3a. Bar heights are percentages of all records within each topic. The same indicator definition applies in a,b and includes both supporting and disqualifying evidence. The labels and cohort are the same as in Fig. 3a: 330/357 Confirmed/other records for DBPs, 68/232 for blood, 213/87 for drugs, 125/175 for endogenous metabolites and 239/61 for microbial products (1,887 records, 975 Confirmed). All 28 criterion profiles appear in Supplementary Fig. 4.

**Review can make criterion-specific evidence more explicit**

Review can strengthen the connection between evidence and a required criterion even when the release decision remains Confirmed. We compared the initial and subsequent passages in 11 accepted records with source-linked inspections (Fig. 6 and Supplementary Note 13).

For 4-hydroxybenzene-1,2-dicarboxylic acid, the initial quotation identified the compound as a product of chlorination. It did not explicitly connect formation to an organic precursor, another requirement of the DBP rubric. Critique requested that connection, and the revised report added a sentence from the same paper linking the products to natural organic matter (Fig. 6a).

For Isoterrelumamide A, the initial primary paper established fungal isolation and structure determination, but the quoted passage did not explicitly establish secondary-metabolite status. Follow-up added named-compound context for that classification (Fig. 6b). In both cases, review made an evidence-to-criterion link more explicit without changing the final Confirmed label.

The third case traces an unresolved exact-species requirement across research and review. The candidate was PC(20:2(11Z,14Z)/20:1(11Z)), but the initial passage named PC(20:3(8Z,11Z,14Z)/20:1(11Z)), a different lipid species. Critique identified this mismatch. The later passage described the Kennedy pathway for phosphatidylcholine synthesis generally, without naming the requested species. Thus, the report remained Confirmed even though the added evidence did not resolve the exact-species requirement (Fig. 6c).

![image](figures/nature/Figure6.pdf)

**Figure 6 How review changes criterion-level evidence.** Only the criterion targeted by follow-up is shown for each case. Follow-up sentences are quoted verbatim, with criterion-relevant words highlighted. Initial summaries and requests are paraphrased. Internal citation and figure numbers are retained from the sources. Symbols summarize our inspection of the displayed source passages. Check marks indicate explicit support and open circles indicate unresolved links. (a) The same abstract supplies the connection to natural organic matter (NOM). (b) An added review names the compound in its secondary-metabolite discussion. (c) Follow-up describes general phosphatidylcholine (PC) biosynthesis, leaving the exact target species unresolved. Blue rows mark established links and red marks the unresolved link. All three records had approved Confirmed release decisions. Source locations accompany the 11 source-linked inspections in the Source Data (Supplementary Note 13).

**Discussion**

DB-Curator organizes database construction around the scientific question that each row must answer. A compound name identifies the entity to investigate, while the rubric specifies the relationships that establish membership, such as formation during disinfection, occurrence in blood or production by a microorganism. These requirements guide candidate discovery and subsequent searches, and the resulting record connects the decision to the passages used to make it.

The evaluation follows that process from discovery to decision. Open-ended construction produced evidence-linked records across five domains, and expert review assessed whether the supplied evidence supported the recorded decisions. Adaptive research produced more Confirmed labels than a frozen evidence bundle. This pattern was especially pronounced for DBPs and microbial natural products, whose defining relationships may require searches beyond an initial paper bundle.

Critique examines how explicitly the collected evidence supports the rubric and requests further material for missing links. The case studies show how this can make a precursor relationship or biological classification explicit, alongside an exact-identity requirement that remained unresolved. In the same-state comparison, directed feedback prompted more research and more Confirmed outputs at greater cost (Fig. 4d). These observations characterize Critique as criterion-level review with conditional follow-up.

DB-Curator builds on scientific agents that combine retrieval, reasoning and iterative assessment. Claim-verification systems retrieve rationales, while ReAct, Reflexion and deep-research agents coordinate reasoning with tool use and revision.<sup>28-33,39,40</sup> DeepEvidence organizes biomedical evidence through an evolving graph, and chemistry-focused systems support extraction, molecular reasoning and discovery.<sup>24,34-38,41-43,55</sup> LitMOF applies literature validation to a specific materials domain.<sup>54</sup> DB-Curator treats the curation scope as a configurable input rather than a fixed property of the workflow. The agent proposes a topic definition and acceptance rubric from the user’s request, then refines them with the user until approval. The definition and rubric carry the topic-specific requirements, while the discovery, search and verification architecture remains shared across chemical domains.

The remaining opportunities centre on the evidence available to curators. Access to figures, supplementary files and licensed full text would extend coverage beyond abstracts and accessible passages. Preserving identity information and evidence links across research steps would also help distinguish exact compounds from related species, formulations or classes. The expert review illustrates this distinction: five of the nine construction entries not accepted were class-level entities. Topic relevance and suitability as an individual database row are related but separate judgments.

The framework could be adapted to other databases by changing the entity recognizer, grounding resources and rubric. Materials records might require composition, synthesis conditions and measured performance, while clinical-trial records require population, intervention and endpoint definitions. Chemical curation provides the present test: a workflow in which scientific scope directs literature research and each database decision remains open to inspection.

**Methods**

**Overview**

DB-Curator maps a user request *u* to candidate database records through iterative search, reading and rubric-based assessment. Its shared state contains the topic specification, queries, retrieved documents, text chunks, candidate identities, evidence passages and provenance links. Agents update this state and save intermediate outputs for inspection.

The workflow comprises four stages. Scope refinement produces a user-approved definition and rubric. Topic-level retrieval collects literature for chemical recognition and normalization. Candidate ranking and model-based triage produce a verification queue. Finally, the Researcher agent–Critique agent workflow collects candidate-specific evidence, assesses rubric criteria and records a label and release status.

**Tools for retrieval, identity grounding and evidence search**

The agents use a shared toolset for compound grounding, literature search, entity recognition and passage retrieval. PubChem provides identity metadata and synonyms. Hybrid online/offline search supplies paper records and available text, from which HunFlair2 extracts source-linked chemical mentions. Candidate-specific documents are indexed in FAISS, and passage queries return evidence with paper identifiers and source locations.<sup>45</sup> The same source links accompany each criterion assessment and final row.

**Topic definition and rubric refinement**

The refinement agent converts the request *u* into a topic specification *s* and a structured rubric *r*. Users inspect, edit and approve the scientific scope, mandatory inclusion criteria, exclusions and optional guidance. Retrieval and verification then use the approved specification, with the same rubric retained across candidates and repeats within each topic.

Initial broad queries derive from the user request and refined specification. The definition supplies the main topic, while rubric items contribute evidence concepts and exclusions for search planning. The literature agent inspects returned titles and abstracts, identifies useful chemical classes and seed compounds, and expands the search around them. During candidate verification, identity terms and selected synonyms are combined with context terms from unresolved criteria.

**Broad retrieval with hybrid online/offline fusion**

FullTextJournalSearchTool searches PubMed/PMC, Europe PMC, Semantic Scholar and an offline corpus of approximately 6.3 million paper records.<sup>7,50</sup> Preprint sources are enabled when requested by the run configuration.

Each query launches source-specific searches in parallel. Online APIs return ranked records, while offline retrieval uses SQLite full-text search over titles, abstracts, identifiers and metadata.<sup>44</sup> Paper records are deduplicated using DOI, PMID, PMCID, Semantic Scholar or arXiv identifiers, followed by normalized titles. Reciprocal rank fusion combines the source–query rankings: each occurrence contributes the reciprocal of its rank plus a fixed offset of 60, and contributions are summed across lists. The fused ranking is passed to text enrichment.

**Full-text acquisition and parallel processing**

Offline records are enriched from available local text or PDF files. Online acquisition first attempts structured JATS or PMC full text, followed by Unpaywall and open-access PDF routes. OpenDataLoader performs PDF conversion, with Docling or pdfminer as fallbacks.<sup>46,47</sup> When full text is unavailable, the abstract is retained and marked as abstract-only. Section headings are preserved when available. Search, enrichment, conversion, embedding and reranking use parallel workers.

**Candidate discovery by entity extraction, normalization and filtering**

ChemicalNerTool processes retrieved documents in batches using HunFlair2 and a biomedical entity linker. Mentions retain their surrounding text, source files and available identifiers, providing the compound–context records used for candidate ranking.

Let \(D\) denote the retrieved paper set and \(M(d)\) the chemical mentions extracted from paper *d*. DB-Curator constructs the raw candidate set by normalizing and aggregating mentions across papers:

\[E=\bigcup_{d\in D}\{\operatorname{norm}(m):m\in M(d)\}.\]

Each candidate *e* retains mention counts, context samples, identifiers and surface forms. A representative name is selected from observed forms and synonyms. PubChem, RDKit and OPSIN support identity grounding and structure handling.<sup>5,48,49</sup>

Candidates undergo deterministic ranking followed by model-based relevance triage. Let \(S(e)\) contain the mention snippets for candidate *e*, and let \(h(\cdot)\) denote the BAAI/bge-small-en-v1.5 encoder. Similarity to the refined specification *s* is the strongest snippet-level cosine similarity:

\[s_{\mathrm{topic}}(e)=\max_{x\in S(e)}\operatorname{cos}\!\left(h(x),h(s)\right).\]

When the embedding model is unavailable, TF–IDF vectors replace \(h(\cdot)\). Let \(A(e)\) denote the observed surface forms of *e* and \(g(a)\) the compound-grounding score returned for form *a*. The candidate grounding score and pre-rank score are

\[s_{\mathrm{ground}}(e)=\max_{a\in A(e)}g(a),\qquad
s_{\mathrm{pre}}(e)=0.8\,s_{\mathrm{topic}}(e)+0.2\,s_{\mathrm{ground}}(e).\]

Candidates are ordered using topic similarity, grounding, PubChem compound-match score, pre-rank score and mention count, and the top *K* candidates enter LLM triage. Let \(\ell(e,s,r)\) denote the triage relevance score for candidate *e* under specification *s* and rubric *r*. The downstream verification queue is

\[E'=\{e\in\operatorname{TopK}(E):\ell(e,s,r)\geq\theta\},\qquad \theta=0.7.\]

Gemini 2.5 Flash receives the selected names, synonyms, topic definition and verification template for triage.

**Dual-agent verification**

Each candidate \(e \in E^{'}\) receives an independent verification session. Its input contains the name, synonyms, original request, refined definition, rubric items and search allowance. CompoundDatabaseTool supplies additional identity metadata and search aliases when available.

The query builder retains the original query, adds one or two primary identity terms, and combines them with current context terms. Critique follow-up targets the highest-priority unresolved rubric item, with duplicate queries suppressed.

FullTextIndexTool divides retrieved text into approximately 1,200-character chunks with 180-character overlap, preserving section boundaries where available. Metadata stubs and short non-substantive chunks are removed. The remaining chunks are embedded with all-MiniLM-L6-v2 and stored in the session’s FAISS index. FullTextQueryTool combines BM25 and vector retrieval with equal weights when both are available, otherwise using vector retrieval alone. It fetches the larger of 120 chunks or four times the requested output size. BAAI/bge-reranker-v2-m3 reranks the results, with cross-encoder/ms-marco-MiniLM-L-6-v2 as a fallback. Returned passages include title, section, DOI, PMID and source-path metadata.

The passages form the candidate evidence set \(T_e\). The Researcher agent proposes a label and criterion assessments and may continue its own research before the first Critique call. Critique reviews this reasoning, the criterion assessments and the proposed label criterion by criterion against the rubric and the supplied passages, without retrieving evidence itself, and then approves, requests follow-up for a named unresolved criterion or ends verification. Requested follow-up returns the candidate to the Researcher agent for targeted retrieval and a revised report. Runs used a LangGraph recursion limit of 24 graph steps and stopped after two consecutive rounds without rubric-relevant progress. Timeouts, runtime errors, insufficient evidence and explicit negative evidence remain distinct outcomes.

**Decision contract and release**

The decision contract evaluates the agent-recorded criterion states: supported, contradicted, unresolved and conflicting. Mandatory inclusion criteria require a recorded supported state and linked evidence. In the construction and benchmark runs, declared exclusion-trigger propositions required a contradicted state, whereas negatively worded inclusion requirements required support. Drug modality was treated as one ANY condition, and optional guidance did not block acceptance. The feedback-mechanism comparison used explicit operator/polarity annotations and a common evidence-triggered exclusion rule for all arms, as described below.

The prediction endpoint is the last Researcher label after any Critique-triggered follow-up. Critique approval and release eligibility are separate fields. Database release requires an approved Confirmed release decision and satisfaction of the recorded criterion and citation checks. A Critique-approved label could supersede the Researcher prediction when the saved rubric was fully solved. Each paper citation must identify the correct source and accurately represent the attributed passage. Compound-database and tool records can support identity but are excluded from the paper-citation denominator. The audit record \(\Pi_e\) preserves the Researcher label, release decision, criterion assessments, papers and passages for inspection. Model-generated InChIKeys and formulas are stored separately from source-provided identity information.

**Evaluation cohorts and endpoints**

Construction continued through the same-topic literature candidate pools until 200 distinct entries per topic met the release rule. All processed records and technical outcomes remain in the candidate inventory. Parent-equivalent measurements after enzymatic deconjugation were retained with explicit sample-treatment metadata. Benchmark verification used the complete assigned cohort. For candidate \(i\), let \(R_i\) be the last Researcher label. Confirmed-label yield over an assigned cohort is \[Y_{\mathrm{Confirmed}}=\frac{1}{N}\sum_{i=1}^{N}\mathbf{1}\{R_i=\mathrm{Confirmed}\}.\] This prediction endpoint is used for benchmark verification, the final stage of the repeated ablation, the Critique-model comparison and the same-state feedback comparison. Retained database size is reported separately using release eligibility. The repeated component ablation uses saved labels at the specified stages. The same-state feedback comparison reports Confirmed percentages and post-fork resource means across the same 100 selected candidates in all three arms (Fig. 4d). Supplementary Table 3 summarizes the cohorts and endpoints.

The zero-shot construction baseline generated compounds and citations from the topic definition without retrieval, grounding or Critique. The zero-shot labeling baseline classified supplied compounds under the same topic definition without retrieval. Static RAG issued one retrieval call per candidate across the enabled online and offline sources, using the canonical name, up to three synonyms and fixed topic-context terms. At most eight paper records were retained, each represented by up to 1,400 characters of abstract or full text, and Gemini 2.5 Flash classified this bundle once at temperature 0. Adaptive search used the saved Researcher agent state immediately before the first Critique call within Full, and Full used the final label after Critique review and any follow-up retrieval. Critique-model comparisons ran each configuration end to end. Inputs, prompts and execution configurations are archived with the Source Data.

Paired stage contrasts compare the same candidate and repeat across configurations. Differences were averaged within each topic and then across the five topics with equal weight. Errors contributed zero to confirmation yield. Supplementary Note 10 reports the topic-level contrasts.

**Citation audit and benchmark linkage**

Citation audits checked the identity of the cited paper and the correspondence between the attributed passage and the source text. Records were linked using DOI, PMID, PMCID, title or source-path metadata. DOI and PMID matches required compatible titles. Automated checks accepted exact matches and formatting differences, including spacing, typography and minor OCR omissions that preserved the quoted content. Differences involving chemical identity, species, numerical values or negation were referred for review. Original quotations and source passages were retained together. Verification rates use all paper-citation instances, excluding compound-database and tool records.

Benchmark matching was evaluated independently of the system label. Matches used benchmark-native identifiers, unique normalized primary names, full InChIKeys and canonicalized structures. Known structure conflicts were not resolved by name similarity alone. Acid and conjugate-base forms were grouped without removing stereochemical or isotopic distinctions. The complete DBP benchmark was used directly. The other resources were supplemented by the Blood Exposome search index, the Natural Products Atlas catalogue and source-attributed DrugBank or HMDB accessions in PubChem. Unresolved lookups were retained as unresolved rather than evidence of absence. The same identity policy was applied to zero-shot proposals. Let \(B_t\) be the distinct benchmark identities encountered during processing for topic \(t\), and let \(C_t\) be those represented in the final retained cohort. Benchmark-linked retention is

\[T_t^{\mathrm{benchmark}}=\frac{|B_t\cap C_t|}{|B_t|}.\]

**Expert review**

Across all four cohorts, Botao Liu, a domain expert and co-author, assessed topic membership and citation support with system labels hidden from the reviewer. These comprised 250 DB-Curator construction entries and 250 zero-shot proposals (50 per topic in each cohort), 1,886 benchmark records and 109 non-Confirmed candidates from open-ended construction. Review judgments were compared with the corresponding archived system decisions for analysis. Under the reviewer’s annotation convention, entries without a recorded objection were counted as agreement on topic membership and citation support. Written comments and subsequent author clarification were reconciled at the row level. Class-level organic entries remained outside the accepted count when they did not identify an individual entity (Supplementary Note 9).

The construction confusion matrix included every candidate evaluated in five runs stopped at 50 retained entries per topic. Their complete processing pools contained 250 retained entries and 109 non-Confirmed candidates. Human-qualified retained and non-retained candidates were counted as TP and FN, respectively. Retained candidates failing the requirements were FP, and non-retained candidates whose supplied evidence did not meet the inclusion requirements were TN. Precision was \(\mathrm{TP}/(\mathrm{TP}+\mathrm{FP})\), and processed-pool recall was \(\mathrm{TP}/(\mathrm{TP}+\mathrm{FN})\). The recall denominator comprises human-qualified candidates that entered verification in these five construction runs.

**Same-state feedback comparison**

The comparison used 100 candidates, 20 per topic, selected before any feedback branch was run. Automated assessment of pre-Critique evidence defined two selection strata, with 66 candidates assessed as having evidence gaps and 34 as complete. Each saved Researcher state was copied into three isolated branches with identical evidence, models and resource ceilings. A returned criterion-directed feedback, B returned general review with the same rubric and criterion assessments, and C omitted those explicit inputs from Critique. Each branch allowed up to three Researcher rounds and three Critique rounds. Recorded mandatory inclusion criteria required support, drug modality used an ANY operator, and exclusions were triggered by supporting evidence for the exclusion proposition. The comparison measured follow-up research, resource use and system-reported labels. Final Confirmed percentages and post-fork resource means use all 100 assigned candidates per arm (Fig. 4d). Release additionally requires Critique approval and the applicable decision and citation checks.

Token summaries use the provider usage recorded across all assigned branches. Cost summaries retain reservations for calls without complete billing receipts.

**Evidence inspection in accepted records**

We selected the finally Confirmed, accepted records from the existing source-linked diagnostic inspections. For each record, we compared the initial and subsequent passages with the named rubric requirements. All 11 matching cases were retained, including unresolved identity and scope links. The displayed criterion states were assigned by inspection of the cited passages. The analysis follows changes in criterion-specific support across research and review stages (Supplementary Note 13).

**LLM settings**

Gemini 2.5 Flash served as the Researcher agent and zero-shot labeler, GPT-5-mini as primary Critique and Gemini 2.5 Flash as alternate Critique. Repeated comparisons used the same fixed inputs in three repeats. Definitions, rubrics, prompts, outputs and analysis scripts accompany the evaluation data (Supplementary Notes 2–4).

**Data availability**

Figure source data, case-level evaluation tables, audit records and offline reproduction scripts accompany the manuscript in the Source Data and reproduction archive. The offline retrieval resource contains approximately 6.3 million paper records, with full text available locally where permitted. Licensed full texts remain subject to publisher access conditions. The versioned data and reproduction archive is available at Zenodo (<https://doi.org/10.5281/zenodo.21285739>). Benchmark data were obtained from DrugBank (<https://go.drugbank.com/releases/latest#open-data>), HMDB (<https://www.hmdb.ca/downloads>), the Blood Exposome Database (<https://zenodo.org/records/8140710>), Natural Products Atlas (<https://www.npatlas.org/download>) and the DBP curation resource (<https://pubs.acs.org/doi/10.1021/acs.est.4c13900>).

**Code availability**

The DB-Curator implementation, prompts, analysis scripts and figure-generation code are available in the versioned Zenodo archive (<https://doi.org/10.5281/zenodo.21285739>). The development repository is hosted at <https://github.com/CZhao97/db_form_agent_system>.

**Author contributions**

C.Z., B.L., X.L., and T.H. conceived the study. C.Z. developed the agentic system and conducted experiments. C.Z. and B.L. performed citation-source inspection, scope-consistency checks and evaluation analyses. C.Z., B.L., X.L., and T.H. wrote and revised the manuscript. X.L. and T.H. supervised the project.

**References**

1\. Wishart, D. S. et al. HMDB 5.0: the Human Metabolome Database for 2022. Nucleic Acids Res 50, D622–D631 (2022).

2\. Barupal, D. K. & Fiehn, O. Generating the Blood Exposome Database Using a Comprehensive Text Mining and Database Fusion Approach. Environ. Health Perspect. 127, 097008 (2019).

3\. Xiang, T. et al. Disinfection Byproducts Confirmed over 50 Years: Systematic Curation, Modes of Toxic Action, and Toxicogenomics. Environ. Sci. Technol. 59, 22334–22350 (2025).

4\. Wishart, D. et al. T3DB: the toxic exposome database. Nucleic Acids Res. 43, D928–D934 (2015).

5\. Kim, S. et al. PubChem 2023 update. Nucleic Acids Res 51, D1373–D1380 (2023).

6\. Wishart, D. S. et al. DrugBank 5.0: a major update to the DrugBank database for 2018. Nucleic Acids Res 46, D1074–D1082 (2018).

7\. Levchenko, M. et al. Europe PMC in 2017. Nucleic Acids Res 46, D1254–D1260 (2018).

8\. Piwowar, H. et al. The state of OA: a large-scale analysis of the prevalence and impact of Open Access articles. PeerJ 6, e4375 (2018).

9\. Lo, K., Wang, L. L., Neumann, M., Kinney, R. & Weld, D. S2ORC: The Semantic Scholar Open Research Corpus. in Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics (eds Jurafsky, D., Chai, J., Schluter, N. & Tetreault, J.) 4969–4983 (Association for Computational Linguistics, Online, 2020). doi:10.18653/v1/2020.acl-main.447.

10\. Priem, J., Piwowar, H. & Orr, R. OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts. Preprint at https://doi.org/10.48550/arXiv.2205.01833 (2022).

11\. Wei, C.-H. et al. PubTator 3.0: an AI-powered literature resource for unlocking biomedical knowledge. Nucleic Acids Res 52, W540–W546 (2024).

12\. Lopez, P. GROBID: Combining Automatic Bibliographic Data Recognition and Term Extraction for Scholarship Publications. in Research and Advanced Technology for Digital Libraries (eds Agosti, M., Borbinha, J., Kapidakis, S., Papatheodorou, C. & Tsakonas, G.) 473–474 (Springer, Berlin, Heidelberg, 2009). doi:10.1007/978-3-642-04346-8\_62.

13\. Mavračić, J., Court, C. J., Isazawa, T., Elliott, S. R. & Cole, J. M. ChemDataExtractor 2.0: Autopopulated Ontologies for Materials Science. J. Chem. Inf. Model. 61, 4280–4289 (2021).

14\. Krallinger, M. et al. The CHEMDNER corpus of chemicals and drugs and its annotation principles. J Cheminform 7 (Suppl 1), S2 (2015).

15\. Leaman, R., Wei, C.-H. & Lu, Z. tmChem: a high performance approach for chemical named entity recognition and normalization. J Cheminform 7, S3 (2015).

16\. Lee, J. et al. BioBERT: a pre-trained biomedical language representation model for biomedical text mining. Bioinformatics 36, 1234–1240 (2020).

17\. Beltagy, I., Lo, K. & Cohan, A. SciBERT: A Pretrained Language Model for Scientific Text. in Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing and the 9th International Joint Conference on Natural Language Processing (EMNLP-IJCNLP) (eds Inui, K., Jiang, J., Ng, V. & Wan, X.) 3615–3620 (Association for Computational Linguistics, Hong Kong, China, 2019). doi:10.18653/v1/D19-1371.

18\. Sänger, M. et al. HunFlair2 in a cross-corpus evaluation of biomedical named entity recognition and normalization tools. Bioinformatics 40, btae564 (2024).

19\. Peng, Y., Rios, A., Kavuluru, R. & Lu, Z. Extracting chemical–protein relations with ensembles of SVM and deep learning models. Database (Oxford) 2018, bay073 (2018).

20\. Kononova, O. et al. Opportunities and challenges of text mining in materials research. iScience 24, 102155 (2021).

21\. Jain, S., van Zuylen, M., Hajishirzi, H. & Beltagy, I. SciREX: A Challenge Dataset for Document-Level Information Extraction. in Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics (eds Jurafsky, D., Chai, J., Schluter, N. & Tetreault, J.) 7506–7516 (Association for Computational Linguistics, Online, 2020).

22\. Dagdelen, J. et al. Structured information extraction from scientific text with large language models. Nat Commun 15, 1418 (2024).

23\. Polak, M. P. & Morgan, D. Extracting accurate materials data from research papers with conversational language models and prompt engineering. Nat Commun 15, 1569 (2024).

24\. Fan, V., Qian, Y., Wang, A., Wang, A., Coley, C. W. & Barzilay, R. OpenChemIE: An Information Extraction Toolkit for Chemistry Literature. J. Chem. Inf. Model. 64, 5521–5534 (2024).

25\. Menick, J. et al. Teaching language models to support answers with verified quotes. Preprint at <https://doi.org/10.48550/arXiv.2203.11147> (2022).

26\. Bohnet, B. et al. Attributed Question Answering: Evaluation and Modeling for Attributed Large Language Models. Preprint at <https://doi.org/10.48550/arXiv.2212.08037> (2023).

27\. Wu, K. et al. An automated framework for assessing how well LLMs cite relevant medical references. Nat Commun 16, 3615 (2025).

28\. Wadden, D. et al. Fact or Fiction: Verifying Scientific Claims. in Proceedings of the 2020 Conference on Empirical Methods in Natural Language Processing (EMNLP) (eds Webber, B., Cohn, T., He, Y. & Liu, Y.) 7534–7550 (Association for Computational Linguistics, Online, 2020). doi:10.18653/v1/2020.emnlp-main.609.

29\. Wadden, D. et al. SciFact-Open: Towards open-domain scientific claim verification. in Findings of the Association for Computational Linguistics: EMNLP 2022 (eds Goldberg, Y., Kozareva, Z. & Zhang, Y.) 4719–4734 (Association for Computational Linguistics, Abu Dhabi, United Arab Emirates, 2022). doi:10.18653/v1/2022.findings-emnlp.347.

30\. Wang, Y. et al. Factcheck-Bench: Fine-Grained Evaluation Benchmark for Automatic Fact-checkers. in Findings of the Association for Computational Linguistics: EMNLP 2024 (eds Al-Onaizan, Y., Bansal, M. & Chen, Y.-N.) 14199–14230 (Association for Computational Linguistics, Miami, Florida, USA, 2024). doi:10.18653/v1/2024.findings-emnlp.830.

31\. Zhang, B. et al. A dataset for evaluating clinical research claims in large language models. Sci Data 12, 86 (2025).

32\. Yao, S. et al. ReAct: Synergizing Reasoning and Acting in Language Models. Preprint at <https://doi.org/10.48550/arXiv.2210.03629> (2023).

33\. Shinn, N., Cassano, F., Gopinath, A., Narasimhan, K. R. & Yao, S. Reflexion: language agents with verbal reinforcement learning. in Advances in Neural Information Processing Systems 36 (2023).

34\. Lála, J. et al. PaperQA: Retrieval-Augmented Generative Agent for Scientific Research. Preprint at <https://doi.org/10.48550/arXiv.2312.07559> (2023).

35\. Ghafarollahi, A. & Buehler, M. J. ProtAgents: protein discovery via large language model multi-agent collaborations combining physics and machine learning. Digital Discovery 3, 1389–1409 (2024).

36\. Ghafarollahi, A. & Buehler, M. J. SciAgents: Automating scientific discovery through multi-agent intelligent graph reasoning. Preprint at <https://doi.org/10.48550/arXiv.2409.05556> (2024).

37\. Chang, C.-Y. et al. MAIN-RAG: Multi-Agent Filtering Retrieval-Augmented Generation. in Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (eds Che, W., Nabende, J., Shutova, E. & Pilehvar, M. T.) 2607–2622 (Association for Computational Linguistics, Vienna, Austria, 2025). doi:10.18653/v1/2025.acl-long.131.

38\. M. Bran, A. et al. Augmenting large language models with chemistry tools. Nat Mach Intell 6, 525–535 (2024).

39\. Huang, Y. et al. Deep Research Agents: A Systematic Examination And Roadmap. Preprint at <https://doi.org/10.48550/arXiv.2506.18096> (2025).

40\. Xi, Y. et al. A Survey of LLM-based Deep Search Agents: Paradigm, Optimization, Evaluation, and Challenges. Preprint at <https://doi.org/10.48550/arXiv.2508.05668> (2025).

41\. Schick, T. et al. Toolformer: language models can teach themselves to use tools. Adv. Neural Inf. Process. Syst. 36 (2023).

42\. Wang, G. et al. Voyager: An Open-Ended Embodied Agent with Large Language Models. Transactions on Machine Learning Research <https://openreview.net/forum?id=ehfRiF0R3a> (2023).

43\. Mavroudis, V. LangChain v0.3. Preprint at <https://doi.org/10.20944/preprints202411.0566.v1> (2024).

44\. Hipp, D. R. *SQLite* \[Computer software\]. Available at <https://www.sqlite.org/> (accessed 14 July 2026).

45\. Douze, M. et al. The Faiss library. Preprint at <https://doi.org/10.48550/arXiv.2401.08281> (2024).

46\. Auer, C. et al. Docling Technical Report. Preprint at <https://doi.org/10.48550/arXiv.2408.09869> (2024).

47\. Hancom. *OpenDataLoader PDF*, version 2.0.2 \[Computer software\]. Available at <https://github.com/hancom-io/opendataloader> (accessed 14 July 2026).

48\. RDKit contributors. *RDKit: Open-source cheminformatics*, version 2023.09.6 \[Computer software\]. Available at <https://www.rdkit.org/> (accessed 14 July 2026).

49\. Lowe, D. M., Corbett, P. T., Murray-Rust, P. & Glen, R. C. Chemical name to structure: OPSIN, an open source solution. J Chem Inf Model 51, 739–753 (2011).

50\. Kinney, R. et al. The Semantic Scholar Open Data Platform. Preprint at <https://doi.org/10.48550/arXiv.2301.10140> (2023).

51\. van Santen, J. A. et al. The Natural Products Atlas: an open access knowledge base for microbial natural products discovery. ACS Cent Sci 5, 1824–1833 (2019).

52\. Polo, F. M. et al. Efficient multi-prompt evaluation of LLMs. Advances in Neural Information Processing Systems 37, 22483–22512 (2024).

53\. Song, Y., Wang, G., Li, S. & Lin, B. Y. The good, the bad, and the greedy: evaluation of LLMs should not ignore non-determinism. in *Proceedings of the 2025 Conference of the Nations of the Americas Chapter of the Association for Computational Linguistics: Human Language Technologies* 4195–4206 (Association for Computational Linguistics, 2025). doi:10.18653/v1/2025.naacl-long.211.

54\. Kim, H., Kim, D. & Kim, J. LLM-Driven Multi-Agent Curation and Expansion of Metal-Organic Frameworks Database. Preprint at <https://doi.org/10.48550/arXiv.2512.01693> (2025).

55\. Wang, Z. et al. Empowering biomedical evidence exploration and synthesis with deep knowledge graph research. Nat Mach Intell 8, 1142–1156 (2026). doi:10.1038/s42256-026-01266-0.
