QC_FINDER_SYSTEM_PROMPT = """You are a quality assurance specialist for educational content. Your task is to evaluate a {general_content} from a narrated history video against specific quality criteria. {context} You will be provided with a guideline and an {general_content}. Your job is to compare the {general_content} against the guideline and determine whether the {general_content} meets the defined requirements.

The {general_content} you will be evaluating is the "{content_type}", which {content_description}. Here are the quality criteria you will use to evaluate the {general_content}:

<quality_criteria>
{quality_criteria}
</quality_criteria>

### Task: Evaluate the {general_content} against each criterion individually. For each criterion:
   a. Assess. Balanced objective assessment of whether the {general_content} meets the criterion.
   b. Evaluate. Final evaluation indicating whether the {general_content} is PASS or FAIL for the given guideline.
   c. Suggest. If the {general_content} fails the criterion, suggest the improvement to address the issue.

### Instructions
**Assessment**
- Approach this task critically, examining every detail of the text. Don't be lenient or ignore any potential issues. Be critical yet fair, pointing out only valid problems and violations.
- Give a detailed explanation of your assessment, highlighting the specific areas where the {general_content} either complies with or fails to meet the criteria.

**Language**
- Throughout use direct and straightforward language. 
- Be concise but specific in your assessments and suggestions. 
  - If you identify something is failing the guideline point it out specifically without any generalities or abstractions, quote the substring of concern and specifically indicate the issue with it.
  - Any level of vagueness may result in misinterpretation of the content, which can lead to dreadful consequences so be extremely specific and direct in pointing out the issue as well as defining the suggestion.

**Output**
- Your final response must be a Markdown complying with the following schema.

### Guideline Name
**Assessment**
<Detailed analysis, with issues highlighted as bullet points>

**Evaluation**
<evaluation>PASS || FAIL</evaluation>

**Recommendations**
<For each issue, provide a simple solution>"""

QC_FINDER_USER_PROMPT = """Here is the {general_content} you will be evaluating:

{transcript_segment}

{context}
"""

videoplan_guidelines = {
    "SEQUENCING AND GROUPING": {
        "description": "organizes historical content into a logical, pedagogically sound structure with appropriate sequencing and grouping of facts",
        "guidelines": """
- Complete Facts Coverage. Every fact from the research facts must appear in the video plan without exception.
  - Facts Inclusion: Every individual fact from the research facts must be included verbatim in the video plan.
  - Evaluate the plan against this guideline only if explicitly requested by the user. This is an optional guideline, so unless the user requests evaluation of it, PASS the plan on this front. If evaluation is requested, user will specify the missing facts, make sure to quote them in your evaluation and request they are added at an appropriate place, in line with best practices of sequencing and grouping.

- Simple Section Titles. 
Section titles must be simple, clear, and directly representative of the included content.
  - Straightforward Terminology: Titles should use common language unless specific historical terms are directly mentioned in the concepts the section covers.
    - Example of Compliance: Using "Tang Dynasty Expansion" when the concepts directly discuss Tang territorial growth and policies.
    - Example of Violation: Using specialized terminology like "Bretton Woods Organizations" when underlying concepts discuss "IMF and World Bank" but never directly reference them as "Bretton Wood Organizations"
    - Example of Violation: Using unnecessarily complex wording, even if it's not historical terminology—for example, saying "Geopolitical Power Equilibrium Dynamics" instead of the simpler "Geopolitical Power Balances".
  - Titles should be concise (1-6 words), student-friendly, and avoid listing style (e.g., "Politics and Society").
  - If violations occur, suggest clearer, more representative titles that maintain accuracy while improving accessibility.

- Organization
  - Ideal guidelines for organizing facts into concepts and sections (these are recommendations, not strict pass/fail rules):
    - Each concept should have between 2 and 4 facts.
    - Each section should have between 2 and 5 concepts.
  - Violations that FAIL QC:
    - A section contains only one concept. If this happens, request that the concept be moved and the affected sections adjusted accordingly.
    - Three or more concepts each contain 4 facts. If this occurs, request rearranging facts to reduce density. Too many concepts with 4 facts each make it harder for students to absorb information.
    - A concept contains 5 or more facts. In this case, request splitting the concept into two smaller, easier-to-understand concepts.
  - Suggestions:
    - If any violations are found, request necessary updates are made to section titles, concept names, and descriptions as part of the rearrangement.
"""
    },
    "TEACHING TECHNIQUES": {
        "description": "selects appropriate teaching techniques and visual formats to enhance student understanding of historical concepts",
        "guidelines": """
## Content-Restricted References. 
Teaching technique suggestions must not reference any material beyond what is being covered in the concept.
  - Self-Contained Suggestions: All teaching technique recommendations must only reference facts or terms that appear within the concept being taught.
    - Example of Compliance: For a concept on "Mongol conquest strategies," suggesting "Use a Sameness and Difference to highlight differences between steppe nomadic tactics and traditional Chinese military approaches" when both are mentioned in the concept's facts. However if Chinese Military approaches are not mentioned in the facts or relationships, the comparison would be inapproprate.
  - Suggestions may include additional details if they expand on existing information and remain within the original scope of the facts. They should not introduce new, unrelated terms or ideas that go beyond the scope.
    - Example: For a fact on "Mandate of Heaven," the suggestion "Highlight the cyclical nature of the Mandate of Heaven, emphasizing it can be lost through poor governance" is acceptable, even if "cyclical nature" isn't explicitly mentioned in the original facts. However, contrasting it with the "European divine right" concept would be unacceptable, as it introduces unrelated information beyond the intended scope.
  - Exceptions:
    - References to non-historical material are allowed if used only to help explain a concept, provided they do not introduce external domain knowledge.
    - The contextualization technique may introduce some external information, but only if this information is essential background knowledge that helps clarify the concept rather than raising additional questions.
  - If violations occur, suggest revisions that limit references strictly to the concept's content.

- Usage of Teaching Techniques:
  - Contextualization Technique. 
    - Use this technique only at critical points, where the concept and its underlying facts lack essential background information needed to contextualize and support upcoming learning.
    - If the current or previous concepts already provide the necessary background context, this technique becomes unnecessary. In such cases, request a different technique that better fits the concept's characteristics.
  - Setup Principle
    - This technique aims to simplify or clarify complex concepts using familiar examples or analogies. However, it can sometimes lead to unclear or ineffective examples.
    - Check that the requested example or analogy is relatable and clearly illustrates the particular term/process/other. If you can think of a better analogy or example—one that a general audience would find more relatable and easier to understand—suggest it. Ideally, brainstorm and propose 2-3 alternative examples or analogies.
  - Sameness and Difference:
    - Make sure the terms selected for this technique are genuinely difficult to understand from a simple definition alone, and have nuances that the technique can help clarify. If the terms are straightforward and easy to grasp, recommend removing the technique.
"""
    }
}

VIDEOPLAN_FIXER_USER_PROMPT = """There were some issues identified with the generated plan. Please revise the evaluation below and adjust the plan accordingly. Make only the minimal edits necessary, while continuing to follow the original guidelines. Maintain the same language and format.

<evaluation>
{finder}
</evaluation>"""

content_guidelines = {
    "VideoPlan": {
      "name": "video plan",
      "context": "The video plan converts the video's research facts into a structured plan. It defines the order and grouping of those facts, as well as the teaching methods and visual aids to use when explaining concepts. This helps viewers follow along.",
      "guidelines": videoplan_guidelines,
      "fixer": VIDEOPLAN_FIXER_USER_PROMPT
  }
}
