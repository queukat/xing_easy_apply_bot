is_relavant_position_template = """
Prompt: Evaluate Resume Suitability for Job Description

Act as an expert HR evaluator. Go beyond keyword matching: build an internal Requirement–Evidence Matrix and a Responsibility Mapping before scoring. Do NOT reveal steps or the matrix.

---

Provided Information

Job Description
{job_description}

Resume
{resume}

---

Definitions (for internal use only)
• Requirement–Evidence Matrix columns: [ID, Type(Hard/Soft), Quoted JD requirement, Criticality(Must/StrongPlus/Nice), VendorSpecific(Y/N), Years/Level(if any), EvidencePresent(Y/N), EvidenceSource(Title/Bullets/Projects/Certs), EvidenceSnippet(≤10 words), Recency(YYYY–YYYY), DepthSignals(scale/ownership/outcome/real-time/security), Match(full/partial/missing), Notes].
• Responsibility Mapping: map top 5–8 JD responsibilities to explicit resume evidence (≤12 words each) or mark missing.
• Irrelevant Hard: mark a Hard as Irrelevant if it appears in <25 % of the remaining Hard requirements AND is absent from the top-5 JD responsibilities; convert to Soft.
• Irrelevant-to-Soft Safeguard: Soft points gained from such converted skills can never raise the Composite Fit above 8.
• ANY_OF Hard Set: when JD lists X / Y / Z as alternatives, group them as one Hard-Set. If any single item is evidenced → Set=Full; if none → Set=Missing. Partial is not used at the set level (but track evidence at item level).
• Clarify Gate: if a skill seems Irrelevant by rule above BUT appears in ≥2 JD responsibilities, trigger a one-question clarification to the requester before scoring. If no answer is available, default conservatively: treat it as Relevant (keep as Hard). You may add “[ClarifyGate]” token in Reasoning.

---

Evaluation Instructions

0) Disqualifiers (check first):
   • Mandatory language / work authorization (no sponsorship) / security clearance / mandatory on-site-if-stated.
   • If explicitly required and contradicted/absent in the resume → Score: 0.
   Reasoning: Required {{language/authorization/clearance/location}} missing.

1) Extract Requirements and fill the Matrix (explicit mentions only; no assumptions):
   • Hard: mandatory skills/tech/years/certs/knowledge.
   • Soft: desired tools/methods/behaviors.
   • Broad terms (“cloud platform”) → any major vendor (AWS/Azure/GCP/OCI) = full.
   • Named vendor (e.g., “AWS”) → alternatives = partial unless “or equivalent” is stated.
   • Detect ANY_OF Hard Sets per Definitions.

2) Depth Profile (use to inform scoring):
   • Seniority/ownership; scale/latency/real-time; domain/regulatory; recency (≤24 months); quantified outcomes; consistency (no double-count, flag contradictions).

3) Normalize Experience:
   • Years: resume ≥ req → full; gap ≤1y → full; gap >1y & ≤20% of req → partial; else missing.
   • Adjacent roles (e.g., Data Engineer ↔ Data Architect) → partial unless duties clearly match.

4) Dual Scoring (compute both internally):
   • Core Fit (Hard-only, before caps): sum Hard (including ANY_OF sets) as full +2 | partial +1 | missing +0; scale to 0–5.
   • Composite Fit (Hard+Soft+Depth): Hard as above; Soft full +1 | partial +0.5 | missing +0; use depth as a tie-breaker only.

5) Caps & Flags 
   • 5.1 Validation: apply Irrelevant Hard rule. Convert such Hard → Soft.  
     Irrelevant-to-Soft Safeguard: Soft points gained cannot lift Composite Fit above 8.
   • 5.2 ANY_OF Hard Set: score each set per Definitions (Full if any item evidenced; Missing if none).
   • 5.3 Non-negotiable Hard = Hard remaining after 5.1–5.2 (i.e., relevant, non-alternative must-haves).
   • 5.4 If any Non-negotiable Hard = missing → cap Composite Fit at 5 and append [Override: missing hard = <list>].
   • 5.5 If ≥2 Hard are partial (score=1), cap Composite Fit at 8.
   • 5.6 Clarify Gate: if triggered and unanswered, treat the disputed skill as Relevant (Hard) and you may include “[ClarifyGate]” in Reasoning. Prefer lower score under ambiguity.

6) Output Calibration (1–10 on Composite Fit after caps):
   • 9–10: All Non-negotiable Hard fully met; most Soft met; strong depth.
   • 7–8: All Non-negotiable Hard met; Soft partially met; adequate depth.
   • 5–6: Most Hard met with gaps; mixed Soft; uneven depth.
   • 3–4: Several Hard missing/mostly unfulfilled.
   • 1–2: Minimal Hard matches or severe gaps.
   • 0: Applied in step 0.

7) Reasoning (strict, ≤50 words):
   • Name top full matches, key partial/missing (label non-negotiable if any), decisive depth factor(s).
   • Include 1–2 micro-quotes (≤10 words), e.g., JD “3+ years” vs CV “Python 3+ years”.
   • If step 5.4 applied, include [Override: …]. If Clarify Gate default used, you may add “[ClarifyGate]”.
   • If >50 words → truncate to ≤50.

8) Exclusions (unless JD marks as must):
   • Compensation, start date, general location/visa, travel/relocation.

---

Output Format (Strictly Follow)

Score: [numerical score from Composite Fit after caps]
Reasoning: [≤50 words; concise matches/gaps; depth signals; include [Override: …] if applied; optional “[ClarifyGate]”]

---

Universal Principles

• Broad ≠ specific: broad “cloud” → any major vendor = full; named vendor → alternatives = partial unless “equivalent”.
• Depth matters: scale/recency/outcomes/ownership can refine ties but not invent skills.
• Soft cannot compensate missing Non-negotiable Hard.
• Determinism: ties/ambiguity → choose the lower score.
"""
