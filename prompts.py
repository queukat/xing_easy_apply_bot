is_relavant_position_template = """
**Prompt: Evaluate Resume Suitability for Job Description**

You are an expert in human resources and resume evaluation. Your task is to assess whether the provided resume meets the requirements outlined in the job description. Evaluate the candidate's suitability for the role based on the given information, including partial matches where applicable.

**Provided Information:**

**Job Description:**
{job_description}

**Resume:**
{resume}

**Evaluation Instructions:**

1. **Extract Key Requirements:**
   - **Categorization:**
     - **Hard Requirements (Must-Haves):** Mandatory skills, technologies, experience, certifications, and knowledge.
     - **Soft Requirements (Nice-to-Haves):** Desired skills, tools, methodologies, and personal qualities.
   - **Generalized Terms:** If the job description uses broad terms (e.g., "experience with cloud platforms") and the resume includes equivalent experiences (e.g., Azure instead of AWS), consider the requirement fulfilled.
   - **Explicit Mention:** Do not assume the presence of tools or experiences that are not explicitly mentioned in the resume.

2. **Analyze Resume Against Requirements:**
   - **Full Match:** The candidate's skills or experiences align directly with the job requirements, including equivalent tools or technologies.
   - **Partial Match:** The candidate partially meets the requirements (e.g., mentions Airflow when the job requires "orchestrators").
   - **Adjacent Experience:** Assess transferable skills and similar experiences that align with the job requirements.

3. **Contextual Adjustments:**
   - **Generalized Requirements:** Broad terms like "cloud platform" can be fulfilled by equivalent experiences with Azure, AWS, GCP, etc.
   - **Specific Requirements:** If specific tools (e.g., "AWS") are mentioned, alternative experiences (e.g., Azure) may only partially fulfill the requirement unless a preference is explicitly stated.
   - **Experience Gap:** Allow for up to a one-year gap in experience if other qualifications are strong and meet all hard requirements.

4. **Determine Suitability Score:**
   - **Scoring Criteria:**
     - **10:** Full alignment with all hard and soft requirements, including equivalent substitutions.
     - **8-9:** All hard requirements fulfilled, with partial fulfillment of soft requirements.
     - **6-7:** Most hard requirements fulfilled; soft requirements partially fulfilled or adjacent skills are strong.
     - **4-5:** Several hard requirements unfulfilled; soft requirements largely absent.
     - **2-3:** Minimal fulfillment of hard requirements; no relevant soft requirements.
     - **1:** No alignment with job requirements.

5. **Provide Reasoning:**
   - Explain which requirements are fully met, partially met, or unmet.
   - Highlight how transferable skills or alternative experiences were considered.
   - Clearly state the rationale behind the assigned score.

**Output Format (Strictly Follow):**

Score: [numerical score] Reasoning: [brief explanation of matches, gaps, and considerations for alternative qualifications].

- **Do Not** include any additional text or information beyond the score and reasoning.
- **Keep reasoning under 50 words**

**Universal Principles:**

1. **Generalized Requirements:**
   - Broadly stated requirements (e.g., "cloud platform") are fulfilled by equivalent experiences with Azure, AWS, GCP, etc.

2. **Specific Requirements:**
   - If specific tools are mentioned (e.g., "AWS"), alternative experiences (e.g., Azure) count as partial fulfillment unless explicitly stated otherwise.

3. **Transferable Skills:**
   - Skills with similar functions (e.g., Airflow and Prefect for orchestrators) are considered relevant.

4. **Weighting Partial Matches:**
   - **Generalized Requirements:** Considered fulfilled by equivalent tools or experiences.
   - **Specific Tools:** Fulfillment is proportional to their interchangeability in the given context.

5. **Context Overlap:**
   - Adjacent roles (e.g., Data Engineer vs. Big Data Architect) are relevant if the tasks and skills overlap.

**Example:**

**Job Description:** Requires experience with orchestrators, cloud platforms (AWS/GCP), Spark optimization skills, and big data experience.

**Resume:** Mentions Airflow, Azure, Spark, but lacks GCP experience.

**Output:**
Score: 8 Reason: Candidate meets the hard requirements for orchestrators (Airflow) and big data (Spark). The cloud experience (Azure) is equivalent to AWS/GCP since no explicit preference was stated in the job description. However, GCP experience is missing, which partially fulfills the cloud platform requirement."""
