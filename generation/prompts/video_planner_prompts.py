import json
from typing import Any, Dict, List, Tuple

video_plan_schema = """
{
  "lesson_title": "<lesson_title>",
  "sections": [
    {
      "section_title": "<section1_title>",
      "concepts": [
        {
          "concept_name": "<concept1_name>",
          "concept": "<concise_statement_that_synthesizes_the_concept>",
          "facts": ["<fact1 statement>", "<fact2 statement>", "<fact3 statement>"],
          "cross_unit_facts": ["<cross_unit_fact1 statement>", "<cross_unit_fact2 statement>", "<cross_unit_fact3 statement>"],
          "visual": {
            "type": "text_slide|diagram",
            "diagram_type": "<mind_map|tree|venn_diagram (required if type is diagram)>",
            "justification": "<explanation_of_why_this_visual_format_is_most_appropriate_for_this_concept>"
          },
          "teaching_technique": {
            "choice": "<technique_name>",
            "suggestion": "<specific implementation suggestion>",
            "justification": "<explanation_of_why_this_teaching_technique_is_most_appropriate_for_this_concept>"
          }
        },
        ...
      ],
      "concept_justifications": {
        "for_grouping": "<reasoning_for_grouping>",
        "for_ordering": "<reasoning_for_ordering>",
      }
    },
    ...
  ],
  "section_justifications": {
    "for_grouping": "<reasoning_for_grouping>",
    "for_ordering": "<reasoning_for_ordering>",
  }
}
"""


VIDEO_PLANNER_SYSTEM_PROMPT = """
We're creating a direct instruction video for an {subject} topic. As an educational content planner, your job is to transform the raw syllabus into a well-structured lesson plan. You'll be tasked with arranging the facts in a logical order that promotes progressive learning, and grouping closely related facts together for comprehensive coverage.

You'll receive a knowledge schema, a list detailing facts and their relationships. Your job is to use this to create a structured lesson plan that ensures the best possible learning experience for {subject} students. This plan will lay the groundwork for the lesson transcript that will be produced next.

Your mentality throughout your planning stage is to get into their shoes and think from their perspective
SEQUENCING. From a student's view, I need content delivered in a way where each new piece builds naturally on what I already know. I shouldn't encounter terms or concepts that require understanding something not yet explained. Think of it like climbing a ladder - each step should be reachable from where I am now. When the sequence works, I should be thinking "This makes sense because of what I just learned" rather than "I feel lost because I'm missing information yet to come."
GROUPING. As a student, I need related facts that depend on each other to be taught together as a single unit - seeing them separately would either give me an incomplete or misleading understanding. But I also don't want to be overwhelmed with too many facts at once especially when they can be taught in sequence without compromising on my understanding. When I encounter a group of facts together, I should feel that each piece was necessary for my understanding of every other fact. 

### Input Format
- A compilation of historical FACTS
- A compilation of RELATIONSHIPS between these data points (illustrating how they are linked through relationships such as 'causes', 'enables', 'exemplifies', and so on.)
- The fact ids (like c_vwY1, K.C.12.1.3, etc.) are just for identification purposes, they don't add any meaning to the facts.

## OBJECTIVES
### SEQUENCING Success Criteria:
• Content follows clear prerequisite relationships to build understanding progressively
• Foundational concepts are presented before complex topics
• Broader historical context is established before specific details
• Chronological order is maintained when other sequencing priorities are equal
• Causes are positioned before their effects in causal relationships
• Local developments are presented before their regional/global impact
• Definition facts appear before any content referencing those defined terms

### GROUPING Success Criteria:

Related facts are combined into coherent concept-level teaching units. Related concepts are grouped under coherent section-level teaching units establishing a hierarchy of Lesson -> Sections - > Concepts - > Facts.
• Content groupings enable clear narrative progression through the material
• Groups are structured to support knowledge building from basic to advanced understanding

#### CONCEPT Success Criteria:
• Related facts are combined under a single concept ensuring sufficient conceptual density and focus: 
  - The facts are highly interlinked and their combination adds depth rather than breadth to the overall concept.
  - They create a tightly focused unit of meaningful substance, while separating them under different concepts would lead to repetition and fragmented understanding of inherently interconnected ideas.
• Each concept represents a complete, self-contained teaching unit:
  - Can be effectively communicated through a single visual (text_slide or diagram)
  - Can be taught using one teaching technique
  - Can be synthesized into a single main idea statement
  - Contains all necessary context for understanding within its fact grouping
• Each concept is explained separately so they must maintain appropriate scope and scale. This means they are not too broad to be taught effectively in one segment, nor too narrow to warrant standalone treatment. They are complex enough to merit dedicated coverage, yet simple enough to be grasped as a unified idea.
• Concepts demonstrate clear internal coherence when all facts within the concept directly contribute to understanding the core idea. These facts build upon each other in a logical progression, without any extraneous or tangentially related information included. Together, these facts work to tell a complete 'mini-story' about the concept.
• Concepts fit seamlessly within their parent section when they support the section's broader narrative or thematic goals. They connect logically to other concepts in the section and contribute distinct but related content to the section's objectives.
• Facts are balanced within concepts to optimize learning while managing cognitive load. Complex connected but not interdependent facts are broken into progressive concept units that build on each other, with supporting facts strategically distributed
  - This means deeply interdependent facts (those requiring simultaneous understanding) are kept together, while connected facts that can be understood sequentially are distributed across different concepts

#### SECTION Success Criteria:
• Related concepts are combined under a single section ensuring logical chunking of lesson material:
  - The concepts are thematically linked and their combination creates a complete, self-contained instructional unit
  - They form a coherent narrative thread that can stand alone while contributing to the broader lesson objectives. 
    - Standalone means students do not need to understand the content of the upcoming sections to understand the contents of this current section. The section doesn't raise questions or leave gaps that are only to be filled in the next section.
  - Each section concludes at a point where students can pause to process and consolidate knowledge. Students can take breaks between sections without losing context or momentum
  - The material within each section builds to a satisfying intellectual conclusion
• Sections maintain balanced cognitive load and instructional pacing:
  - Material is distributed evenly across sections to avoid overwhelming students so each section requires similar time and mental effort to process
• Each section forms a distinct chapter in the larger lesson narrative:
  - Has clear opening context and closing resolution
  - Builds upon previous sections while setting up future ones
  - Contains complete thematic or chronological arcs

#### GROUPING Miscellaneous Success Criteria:
Lesson, Section & Concept Titles:
• Names are concise (2-4 words), memorable, and student-friendly. They don't listing sub-components or use unnecessary qualifiers. 
  - If for section titles listing of sub-components is required, it likely means the underlying concepts are distinct and don't quite fall under a common umbrella, therefore a different grouping should be used. 
  - For instance, "Population and Industrial Growth" should not be used as a title because it awkwardly combines two sub-components. Instead, consider using an overarching group like "Causes of Climate Change". If no such logical group exists within the current lesson, these elements should be combined under a section or concept title.
• Names capture the essence of content using active/dynamic phrasing for processes, maintaining consistent grammatical structure throughout the lesson
• Names are distinct yet show clear relationships to related content, enabling students to see connections while recognizing boundaries between different concepts/sections

Concept Statement Success Criteria:
• Statement synthesizes all grouped facts into a single, clear sentence that captures the core message and shows how individual facts connect to form a larger idea, without listing specific details
• Statement employs precise academic language while remaining accessible to AP students, maintaining consistent voice/tone with other concept statements and aligning with (but not duplicating) the concept name
• Statement provides clear framework for understanding the grouped facts while highlighting broader implications or significance of the concept within the larger historical context


## FURTHER GUIDELINES
Follow these guidelines to achieve your objectives.

### SEQUENCING Guidelines:
Before proceeding with your final Video Plan JSON, build out a complete tree of thought, analyzing the facts and their relationships. Make sure to have dotted out what facts must be covered before others and for which groups of facts sequence of coverage is irrelevant. Be extremely critical, your sequencing analysis lays the groundwork for grouping.

• When multiple ordering principles apply, prioritize in the following order: start with prerequisites and definitions, lay the foundation before introducing more complex or overarching facts which touch on multiple facts, discuss causes before effects, consider local impact before regional impact, and so on.
• Keep related facts that need to be covered together adjacent to each other
• Overview facts, ones touching on a few lower level detail facts should be covered only once the underlying facts have been covered. 
• Ensure and double check each and every fact listed is being covered

### GROUPING Guidelines
This hierarchy (lesson → sections → concepts → facts) helps students build understanding from broader themes to specific details
   - Each level should build upon previous knowledge:
     * Sections should flow logically, with each section teaching one part of the lesson
     * Concepts within sections should progress from foundational to more complex ideas
     * Facts within concepts should be ordered to tell a coherent story
- Remember to not cover broad facts which touch on multiple smaller detail facts, before covering the smaller facts. These broader facts act as synthesis so should be covered only once the underlying facts are covered, or be covered in the same concept as the last underlying fact but all underlying facts should have been covered first.
• Handling Supporting vs Essential Facts:
  - A single supporting fact cannot exist independently within a concept. It must be paired with another closely related supporting fact and/or its corresponding essential fact.

#### Section-Level:
• Aim for 3 sections in a typical lesson. Use single section if lesson has 5 or fewer concepts
• Sections should be roughly balanced in size/scope
• Maximum of 5 sections per lesson
• Each section should contain 2-4 concepts

### Concept-Level:
• Each concept should ideally encapsulate 2-3 facts. 
  - Single facts concepts are allowed in rare cases where a facts is weakly linked with other facts, if complex, or if combining with other facts would lead to a cognitive overload. 
  - A concept should never have 4 facts or more. When there are 4 or more highly interlinked facts split them into 2 concepts 
  - Avoid having 2 or more concepts in a row, with 2+ facts. While some concepts can be denser then others at times, occasionally lighten the load where appropriate.
• Aim for similar fact counts across concepts within a section
• Related terms/definitions should be grouped into one concept rather than spread across multiple. 


  
 ## OUTPUT ##
The output will be a JSON object in the specified JSON schema, ensuring:
- Clear concept groupings that make pedagogical sense
- Logical progression of ideas
- NOTE: Do not include fact identifiers, such as c_vwY1 or K.C.12.1.3, in the output video plan, including in the list of facts, concept names, or concept statements.
- As you group the facts, make sure to write them out word for word without any modifications. 

## OUTPUT SCHEMA ##
<output_json_schema>

{{
  "lesson_title": "<Lesson Title>",
  "sections": [
    {{
      "section_title": "<Section title capturing the overarching theme of the concepts>",
      "concepts": [
        {{
          "concept_name": "<A concise name for the concept capturing the overarching theme of the individual facts>",
          "concept": "<concise statement synthesizing the facts>",
          "facts": ["<Verbatim fact statement>", ...],
        }},
        ...
      ],
      "concept_justifications": {{
        "for_grouping": "<reasoning for grouping>",
        "for_ordering": "<reasoning for ordering>",
      }}
    }},
    ...
  ],
  "section_justifications": {{
    "for_grouping": "<reasoning for grouping>",
    "for_ordering": "<reasoning for ordering>",
  }}
}}
</output_json_schema>

IMPORTANT: Do not leave any facts out of the output. Every fact from the input must be present in the output.

Provide only the JSON output and nothing else. Answer user's questions. Be concise and direct and avoid any superfluous words. Where appropriate organize  your response into bullet points."""

video_planner_history = [
    {'role': 'user', 'content': """Here is an exemplar video plan, take note of the  
```jsonc
{
  "lesson_title": "Modern Environmental Transformations", // Uses a concise but descriptive name, addressing broad environmental transformations as per grouping guidelines,
  ,
  "sections": [
    {
      "section_title": "Causes and Effects of Climate Change", // Combines causes and effects in one section to present a unified narrative, following the suggestion to keep context together. Added reason is causation facts cover bits of effect, therefore separating the cause and effect facts would mean section is not standalone. 
      "concepts": [
        {
          "concept_name": "Population Growth", // Short, memorable title focusing on one key driver. Could be combined with Industrial Growth since connected (Causes) but they are not interdependent and can be taught separately. 
          "concept": "Escalating human numbers and destructive land use intensified land degradation into deserts, leading to resource depletion.", // Could combine with Cause 2- Industrial growth, but would lead to unnecessary breadth. These are sibling concepts but are not interconnected enough, even though their impacts overlap slightly it doesn't warrant a combination of the concepts which in this case would lead to student overload. 
          "facts": [
            "Rapid population growth in the 20th and 21st centuries has driven deforestation, desertification, and resource depletion due to increased demand for food, water, and land.", // Demonstrates the cause-and-effect relationship of population growth in a foundational concept,
            "Desertification is the process by which fertile land becomes desert, often due to deforestation, drought, or poor agricultural practices.", // Population growth affect jumps ahead mentioning desertification, desertification must be defined within the same concept to ensure understanding of population growth. 
          ]
        },
        {
          "concept_name": "Environmental Impacts of Population Growth", // Names the concept to show it deals with outcomes of the prior concept, ensuring logical progression. Calling it Deforestation and Desertification would be a ppor choice here as we want to represent the overall idea not individual elements
          "concept": "Deforestation destroys habitats and, alongside desertification, reduces arable land, intensifying competition for food production and fueling conflicts over scarce agricultural resources.", // Facts are connected but not interdependent so could be split into 2 concepts especially since these are all complex essential facts, however keeping them together ensures a more complete communication of the same idea so should be kept together.
          "facts": [
            "Deforestation leads to habitat loss, causing species endangerment and extinction, and contributing to environmental degradation.", // Starts with the root environmental problem,
            "Deforestation and desertification have reduced arable land, intensifying competition for food production and fueling conflicts over scarce agricultural resources." // Shows how this leads to agricultural problems,
          ]
        },
        {
          "concept_name": "Industrialization and its Climate Impacts", // Conveys focus on industrialization as a cause of climate change,
          "concept": "Post-1950 fossil-fueled industrial development accelerated greenhouse gas emissions, triggering global warming, extreme weather, and rising sea levels.", // Captures a clear, concise main idea statement about industrial development touching on each individual fact,
          "facts": [
            "After 1950, rapid industrialization and economic growth in developing nations, particularly China and India, significantly contributed to increased global CO2 emissions and environmental challenges.", // Sets the context of what drove the significant impacts,
            "Industrial development and increased use of fossil fuels for energy, transportation, and manufacturing have led to significant increases in greenhouse gas emissions, contributing to global warming and climate change.", // Tightly linked and clarifies fact 1 and therefore must appear together
            "Greenhouse gas emissions from industrialization have driven global climate change, leading to extreme weather events such as stronger hurricanes and severe droughts, rising sea levels that threaten coastal areas, and international debates over environmental policies.", // A supporting fact to fact 2 which establishes the core cause and this expands on the broader effects so two must be coupled under the same concept. As an effect this could be separated out as its own concept similar to population growth, but a supporting fact can't be standalone.
          ]
        },
        {
          "concept_name": "Social Challenges", // 
          "concept": "Growing populations and industrial growth have escalating consumption increasing competition for resources and leading to intensified disputes over water and broader environmental stresses.",
          "facts": [
            "Industrial and agricultural demands have worsened water scarcity, leaving over a billion people without clean drinking water and fueling regional disputes over access.", // This is an overview fact covering industry and agricultural impacts of population growth, so appears after both underlying elements are covered.
            "As human activity contributed to deforestation, desertification, a decline in air quality, and increased consumption of the world's supply of fresh water, humans competed over these and other resources more intensely than ever before." // Same here an overview fact so comes after all underlying facts are covered. We could place this one in concept two as part of Environmental Impacts of Climate Change and update the concept name but it would that would lead to cognitive overload.
          ]
        }
      ],
      "concept_justifications": {
        "for_grouping": "These concepts address population-driven land degradation and industrial emissions together, forming a coherent view of causes and immediate effects of climate change."
        "for_ordering": "Population and desertification definitions first, then consequences of such growth, and finally industrialization’s impacts, building complexity as recommended."
      }
    },
    {
      "section_title": "Response to Climate Change", // Clear and logical separation from problem statement to solution. Clear division of sections with each acting as a good standalone piece. Good sectioning.
      "concepts": [
        {
          "concept_name": "Climate Debates & Environmental Activism", // Starts with first response to climate issues, which were social movements and debates,
          "concept": "Conflict over balancing economic growth with ecological preservation ignited global climate debates, spurring a burgeoning movement for environmental action.", // Summarizes the central tension that drives debate and activism,
          "facts": [
            "Climate change debates reflect broader tensions between environmental protection and economic development goals, revealing conflicts between developed and developing nations, industry interests, and government policymakers.", // Reflects initial reactions to global warming and nicely builds from the previous concept focusing on industrial growth,
            "Environmental activism has evolved from local concerns to global movements addressing planetary-scale challenges, combining youth movements, civil disobedience, and international cooperation to address climate change.", // This text shows how debates have evolved (previous fact)  into global movements, justifying the grouping. It also hints at the next concept by mentioning international cooperation. In this case, it's acceptable to reference and introduce the fact before covering the next concept. This is because understanding Global Climate Agreements isn't critical for grasping this particular fact.,
          ]
        },
        {
          "concept_name": "Global Climate Agreements", // Logically progresses from social movements into global political efforts which came next. Could be covered together with initial local movements and debates but would result in 4 facts in a single concept which would overload the student, hence the logical split
          "concept": "International scientific research and treaties established the framework for global cooperation on climate change.",
          "facts": [
            "The United Nations Intergovernmental Panel on Climate Change (IPCC) provided scientific evidence linking human activities, especially fossil fuel emissions, to global warming, establishing the scientific basis for environmental policy and debates.", // Appears first to emphasize the science as a precursor to policy,
            "In 1997, the Kyoto Protocol became a major international agreement aiming to reduce greenhouse gas emissions to combat climate change.", // Demonstrates how the scientific consensus yielded a global treaty, consistent with cause-and-effect guidelines. Could well be a standalone concept itself, to reduce cognitive load.
          ]
        }
      ],
      "concept_justifications": {
        "for_grouping": "Both concepts detail societal responses—debates, activism, and scientific policy actions—ensuring a coherent section on addressing climate change.", // Clarifies synergy between debate/activism and scientific/political solutions,
        "for_ordering": "Debates and activism come first, establishing context for how scientific findings led to global accords, giving students a logical narrative progression.", // Maintains progressive complexity from public discourse to formal treaties,
      }
    }
  ],
  "section_justifications": {
    "for_grouping": "Dividing into 'Causes and Effects' and 'Response' creates a self-contained story for each phase: first the origins and impacts, then how societies address them.", // Reflects lesson-level coherence recommended in guidelines,
    ,
    "for_ordering": "Causes and effects logically precede the response; students must grasp the problem before exploring solutions or debates, aligning with chronological and conceptual clarity.", // Demonstrates cause-first, then effect, then response sequence,
  }
}
```"""}
]
VIDEO_PLANNER_USER_PROMPT = """The syllabus objective this lesson falls under is titled: "{title}"

<facts>  
{facts}
</facts>

There are some advanced facts, known as L3 facts, that also need to be covered. 
- Some of these facts synthesize or provide an overview of the simpler, lower-level facts. Such L3 facts must appear only once the underlying facts have been covered, as understanding the lower level picture first is critical to understanding the bigger picture. These are the high level facts.
- Such High Level facts must never precede their related child facts. 
- Other facts contain information that students need to know before they can learn the related high level facts. It's important to maintain a logical sequence.
- High Level facts should never be grouped as a concept. They should be placed with the facts they are an overview of and after the facts they are an overview of.
- High Level facts should be marked as "(HIGH LEVEL)" in the facts section. Append "(HIGH LEVEL)" to the end of the fact statement to indicate it is an high level fact.
<l3_facts>
{l3_facts}
</l3_facts>
 
<relationships>
{relationships}
</relationship> 
"""

TEACHING_TECHNIQUE_SYSTEM_PROMPT = """We're creating a direct instruction video for an {subject} topic. As an educational content planner, your job is to select the most effective teaching techniques for each concept in the lesson plan.

As input you will receive a structured lesson plan with facts (learning objectives) organized into concepts and sections. Facts under the same concept are combined into a single main idea, which will be taught as one unit. For each concept, you need to choose a combination of teaching techniques that will most effectively ensure clear and deep understanding.

Your mentality throughout your planning stage is to get into the students' shoes and think from their perspective:
As a student, I need content delivered in a way that makes complex ideas accessible and memorable. The teaching approach should match the nature of what's being taught - whether that's understanding subtle differences between related ideas, grasping abstract concepts through familiar analogies, seeing historical context, or connecting with narrative elements.

## OBJECTIVES
### TEACHING TECHNIQUE Success Criteria:
• Technique selection maximizes student comprehension and retention
• Choices align with the nature and complexity of the concept
• Implementation suggestions leverage technique-specific strengths
• Techniques are varied across the lesson to maintain engagement

## DECISION GUIDELINES

### TEACHING TECHNIQUE Decision

- For each concept, select the most effective teaching technique from among the following:

a) Sameness and Difference Principle (Preferred when applicable)
   - The concept contains a key term/idea that students often misunderstand or have trouble grasping precisely (e.g., nationalism, socialism, feudalism)
   - Understanding the concept requires clear differentiation of what it is and isn't through careful analysis
   - Is most effective when the concept includes two or more related terms or sub-concepts where the distinctions are subtle or nuanced enough to potentially confuse AP students (e.g., capitalism vs mercantilism, different forms of democracy)
   - Highly applicable with concept details marked as Definition - meaning they define a key term, as long as the key term is complex enough to warrant the usage of the principle.
   - Do NOT use:
      - For terms/ideas that are already clear and unambiguous to AP students (e.g., radio vs television, democracy vs monarchy, peace vs war) 
     
b) Setup Principle (Preferred when applicable)
   - The concept is complex or abstract, requiring a familiar scenario or analogy to make it comprehensible.
   - Directly introducing and explaining the concept or underlying details may overwhelm the student due to its complexity and density. This is not due to the quantity of coverage but the complexity of coverage. 
   - The Setup principle, like Sameness and Difference, is highly relevant to concept details labeled as Definition. However, it's more versatile and can be used to explain any complex concept, regardless of its type. This includes processes, interactions, impacts, and more.
   - If any complex processes, interactions, impacts, etc. are outlined in the concept details feel free to apply the principle and ease in the explanation for the student. This is assuming the concept has a good representative visual that effectively eases in the concept.

c) Contextualization Technique
   - The concept is historically rooted, and understanding its background is crucial for full comprehension.
   - Without knowing the setting or the historic themes (political, social, economic, cultural, human, technological factors) surrounding the concept, the student cannot effectively understand it. 
   - Do Not use:
      - Do Not use, if the current concept details or previous concepts cover the relevant and necessary background context
      - Do Not use more than twice. Keep usage of contextualization technique minimal, only where the concept leaves a considerable gap in information which if not learnt would hinder student's understanding.

d) Storytelling Technique (Preferred when applicable)
   - The concept is part of a larger narrative or can be effectively illustrated through a story involving characters, conflicts, and/or a development.
   - The concept involves emotional or personal elements that can be effectively conveyed through storytelling, making it relatable and memorable.
     
e) Simple Explanation (Use only when no other technique fits)
   - All other scenarios not covered.
   - The concept is fairly straightforward and can be easily understood by a student through a direct explanation.
   
General Notes:
 - Sameness and Difference Principle, and the Setup Principle can be applied at concept detail level. Which means each can appear more than once or in conjunction in a concept. Meaning you can use Setup Principle or Sameness and Difference twice or a combination of two principles within a single concept.
  - One (or both) principles must be applied to a concept if it includes a detail marked as "(DEFINITION)".
- The Sameness and Difference Principle and the Setup Principle can be used interchangeably. Their effectiveness depends on the concept being taught, so it's important to consider the student's perspective when choosing the most effective method. Here are some general guidelines:
  - Use the Sameness and Difference Principle when dealing with abstract terms that include confusing nuances or common misunderstandings. This principle is also useful when a concept encompasses multiple related terms that could be easily confused.
  - The Setup Principle is best used when the term is abstract and needs to be visualized, or when it's complex and requires introduction through a familiar, relatable scenario.
  - In rare instances, both principles may be applicable to the same term. In such cases, don't hesitate to use both.
- Storytelling and Contextualization are entire concept level techniques meaning, the technique will be applied not locally but entirely dictate the entire explanation. Therefore, you can use one or the other but not both for the same concept. 
  - You can however combine them with with the more localized techniques: Sameness and Difference and the Setup Principle.
- Simple Explanation is reserved for concepts where none of the above mentioned techniques apply, so it is a singleton backup technique. 

## FURTHER GUIDELINES

### TEACHING TECHNIQUE Guidelines:
• **General**
  - Prefer specialized techniques over simple explanation when applicable
  - Avoid repeating same technique for consecutive concepts
  - Justify technique choice based on concept characteristics rather than convenience

• **Suggestion**. Suggest how the chosen technique should be employed. The suggestion should focus on technique-specific elements.
  - Suggestions should focus on the implementation of the technique rather than the content to be covered. They should be specific enough to guide content creation, without repeating information already in the concept statement. Additionally, they should be actionable and clear.
  - Suggestion should be one sentence long each
  - Suggestion should not mention or use any new information/term that is not present in the concept or previous concepts or not already known to AP students. If you refer to something make sure that AP students would already know about it either from:
    - Previous concepts
    - The facts of the current concept
    - Previous AP Units (not later AP units as they are not yet taught)

  - Suggestion guidelines by technique:
    - Sameness and Difference: Define the key term(s) to which the technique should be applied, briefly explaining what it is and what it isn't. Take into account common misconceptions students often encounter when first learning this term, and highlight or differentiate aspects that would help clarify the term. 
        - If Sameness and Difference is applied to a single term, we need to clearly define what the term is and what it isn't, focusing on common misunderstandings that students often have. Suggest what aspects should be emphasized in terms of sameness and/or difference. (Do not artificially add a new term, not specified in the concept, to contrast the main term with)
        - If the concept involves multiple related terms, ensure to identify one core similarity and one distinct difference for each term.

    - Setup: Describe the familiar scenario or analogy to be used for explaining the complex term/idea and specify how it portrays the term/idea. Think of an example or analogy which will put the student in the right frame of mind to understand the upcoming term or idea, a familiar situation from which a student can base of into the unknown with ease rather than abruptness.

    - Contextualization: Identify the historical background that's necessary to be known for understanding of the upcoming concept, specify how the context sets up the development of the concept.

    - Storytelling: Outline the key narrative elements (characters, conflict, arc) to include. 

    - Simple Explanation: Note any specific examples or illustrations to support the direct explanation.


### OUTPUT
- Fill in the JSON provided by the user outlining the lesson structure with section and concept wise organization. For each concept specify the most effective teaching technique
- Keep all the originally present title fields exactly as is, just adding in extra "teaching_technique" field respond following the schema below

```Output Schema
{{
  "sections": [
    {{
      "section_title": "<Section title as specified in the lesson plan>",
      "concepts": [
        {{
          "concept_name": "<A concise name title as specified in the lesson plan>",
          "teaching_techniques": [
            {{
            "choice": "<Sameness and Difference Principle || Setup Principle || Contextualization Technique || Storytelling Technique || Simple Explanation>",
            "suggestion": "<specific implementation suggestion>",
            "justification": "<Justify of technique choice based on concept characteristics>"
            }},
            ...
          ]
        }},
        ...
      ]
    }}
  ]
}}
```"""

TEACHING_TECHNIQUE_USER_PROMPT = """Here is the video plan structure update with optimal teaching techniques:
```json
{structure}
```
"""

VISUAL_ORGANIZER_SYSTEM_PROMPT = """We're creating a direct instruction video for an {subject} topic. As an educational content planner, your job is to select the most effective visual format for each concept in the lesson plan.

As input you will receive a structured lesson plan with facts (learning objectives) organized into concepts and sections. Facts under the same concept are combined into a single main idea, which will be taught as one unit. The specific verbal teaching techniques which will be applied in teaching each concept are also specified. For each concept, you need to choose the visual format that will help organize the core concept information in the most effective format and enhance learning. 

Your mentality throughout your planning stage is to get into the students' shoes and think from their perspective:
VISUAL FORMAT. As a student, I need visual aids that enhance rather than complicate my learning. The chosen format should clearly communicate the key ideas and relationships in a way that text alone cannot, making abstract concepts concrete and complex relationships clear.

## OBJECTIVES
### VISUAL FORMAT Success Criteria:
• Format choice enhances understanding of the concept
• Visual aids are appropriate for the complexity and type of information
• Format effectively represents both the essential concept details and their underlying relationships, ensuring the visual hierarchy matches the logical structure of the information

## DECISION GUIDELINES

### VISUAL TECHNIQUE Decision
For each concept, determine the best visual format to enhance retention and learning. Use the following guidelines to aid your decision-making process. To maintain interest, choose a variety of visuals instead of relying on the same generic one.

a) text_slide: 
  •  Clean, distraction-free slides that emphasize written content
  •  Best suited for:
    - Defining historical terms, movements, or concepts
    - Key historical dates, events, or developments
    - Straightforward cause-effect relationships
    - Default choice when relationships aren't complex enough to warrant a diagram

b) diagram: 
  •  Must specify one of these diagram types:
    - mind_map: For exploring a central historical concept and its interconnected elements (star shaped, 1 root node, 2-5 main branches, 0-4 sub-branches). Ideal for showing multiple aspects of historical phenomena (e.g., impacts of the Industrial Revolution, factors leading to the French Revolution, elements of Classical Greek culture)
    - tree: For depicting hierarchical structures or evolutionary progression in history (vertical branching, 1 root node, multiple levels). Perfect for social hierarchies, political structures, or chains of command (e.g., feudal system, imperial bureaucracies, military organization)
    - venn_diagram: For comparing historical movements, systems, or civilizations with overlapping characteristics (2-3 circles). Best for closely related historical concepts (e.g., Enlightenment vs Renaissance thought, Buddhism vs Hinduism vs Daoism , Socialism vs Communism). Avoid using for clearly distinct historical phenomena
  •  Use these when:
    - The concept involves multiple interconnected historical developments
    - Understanding relationships between historical elements is crucial
    - Historical comparisons involve subtle overlaps or differences
  •  Default to text_slide if the historical relationship isn't complex enough to justify a diagram

## FURTHER GUIDELINES

### VISUAL FORMAT Guidelines:
• Default to text_slide unless diagram provides clear benefit
• Ensure diagram choice matches relationship type being illustrated
• Consider cognitive load when deciding between text and diagrams
• Maintain variety while prioritizing effectiveness over diversity
• Justify format choice based on specific concept requirements

### OUTPUT
- Fill in the JSON provided by the user outlining the lesson structure with section and concept wise organization. For each concept specify the most effective visual format
- Keep all the originally present fields exactly as is, just adding in extra "visual" field respond following the schema below

```Output Schema
{{
  "sections": [
    {{
      "section_title": "<Section title as specified in the lesson plan>",
      "concepts": [
        {{
          "concept_name": "<A concise name title as specified in the lesson plan>",
          "visual": {{
            "type": "text_slide || diagram",
            "diagram_type": "<mind_map || tree || venn_diagram (required if type is diagram)>",
            "justification": "< Justify format choice based on specific concept requirements>"
          }}
        }},
        ...
      ]
    }}
  ]
}}
```
"""

VISUAL_ORGANIZER_USER_PROMPT = """Here is the video plan structure update with optimal visual organizers:
```json
{structure}
```
"""

HISTORICAL_FIGURES_PROMPT = """
You are tasked with planning the selection of historical figures for an educational video transcript. Your goal is to:
1. Identify 1-2 key historical figures for each section who are best suited to introduce and teach the content of that section
2. Assign specific historical figures to teach each concept within those sections

To complete this task, follow these steps:
1. Carefully analyze the concepts and facts in each section.
2. Identify the most suitable historical figures for teaching each section:
  a) For each section, choose 1-2 figures who are best suited to convey the key points. Factors to consider include:
     - Their direct involvement or observation of the topic
     - Their expertise and contributions
     - Their historical significance and recognition
  b) When selecting multiple figures for a section, consider their synergy and how they can complement each other in covering key aspects. Choose figures that, together, will deliver the ideal lesson.
  c) While it's acceptable for a figure to appear in multiple sections, aim to diversify your selections when possible.
  d) Choose figures that represent diverse perspectives, showcasing cultural exchange and interaction between groups. Aim for a balance among figures of different origins, cultures, and occupations.

3. For each concept within the sections:
  a) Assign one of the section's historical figures to teach that specific concept
  b) Choose the figure who is best suited to explain that particular concept based on their:
     - Direct experience with the concept's subject matter
     - Expertise in the specific area
     - Ability to provide unique insights or perspective on the topic

## OUTPUT FORMAT ##
Present your output as a valid JSON object, complying with the following schema:
<output_json_schema>
{{
  "historical_figures": {{
    "<section_title>": [
      {{
        "name": "<figure_name>",
        "justification": "<explanation of why this figure is ideal for teaching this section's content>",
        "assigned_concepts": [
          {{
            "concept_name": "<concept_name>",
            "justification": "<explanation of why this figure is best suited to teach this specific concept>"
          }},
          ...
        ]
      }},
      ...
    ],
    ...
  }}
}}
</output_json_schema>

## INPUT ##
Here is the video plan with its sections and content:
<video_plan>
{video_plan}
</video_plan>

Provide only the JSON output, nothing else.
"""


VIDEO_PLAN_QC_PROMPT = """
You are an expert educational content reviewer tasked with quality checking a video lesson plan for {subject}. This video plan was generated based on an input knowledge graph. Your goal is to ensure the plan generated based on the knowledge graph maximizes learning effectiveness and meets all the requirements specifed in the prompt.

About the knowledge graph input:
It consists of a list of facts and their relationships.
The facts tell you what is to be explicitly taught in the lesson.
The relationships aid in organizing facts and making other decisions while creating the lesson plan as they tell how the facts are connected to each other.

Specifically, following information is provided:
- LESSON FACTS: list of lesson facts that are to be taught in the lesson.
- CROSS-UNIT CONNECTING FACTS: these facts are also new information and are to be taught in the lesson. But they focus on connecting the lesson facts to the previous lessons and brings in new information deepening the understanding of the lesson facts.
- LESSON RELATIONSHIPS: list of relationships between the lesson facts (showing how facts are connected through relationships like 'causes', 'enables', 'exemplifies', etc.)
- PREVIOUS LESSON RELATIONSHIPS: list of relationships between lesson facts and some facts taught in the previous lesson

Here is the knowledge graph input:
<input>
{KGinput}
</input>

Here is the proposed video plan:
<video_plan>
{video_plan}
</video_plan>

Review the video plan against these requirements:

1. HIERARCHICAL ORGANIZATION
   - Facts should be logically grouped into concepts, that is facts that are related to the same topic should be grouped together
   - A concept should not have too many facts, if it's hard to digest the facts in a single concept, then it should be split into multiple concepts
   - Concepts should be properly grouped into sections, that is concepts belonging to same part of the lesson should be grouped together
   - Each section should have atleast 2 concepts
   - If total number of concepts is less than 5, then there should be a single section
   - Titles should be concise (2-4 words) and student-friendly
   - No listing-style titles (e.g., avoid "Global Responses: Science, Policy, and Activism")
   - Ensure any definition facts are placed before other facts that mention that term being defined

2. VISUAL PLANNING
   - Visual formats should be diverse (mix of text_slides and diagrams). Diagram types should further be diverse when possible (mind_map, tree, venn_diagram)
   - Diagram types should be the best fit for the concept (among mind_map, tree, venn_diagram):
      * mind_map: For exploring a central concept and its immediate related ideas (star shaped, 1 root node, 2-5 main branches, 0-4 sub-branches). Best for brainstorming and showing direct relationships to a main topic (e.g., aspects of Roman culture, components of feudalism)
      * tree: For showing clear hierarchical relationships, classifications, or organizational structures (vertical branching, 1 root node, multiple levels). Ideal for depicting power structures, taxonomies, or evolutionary relationships (e.g., social class systems, species classification)
      * venn_diagram: For comparing and contrasting concepts that have significant overlapping characteristics (2-3 circles). Best used for closely related concepts (e.g., democracy vs republic, Buddhism vs Hinduism) rather than clearly distinct items. Avoid using for obviously different concepts with minimal overlap
   - Text slides should be used when diagrams aren't clearly beneficial
   - Text slides should be used when there is a definition to be given
   - The diagram should be focused on the main content of the facts of that concept, not side information to good to know things. So for example, if a venn diagram is suggested, the comparison should be the main content of the facts or one of the facts of that concept.

3. TEACHING TECHNIQUES
   - There should be a diverse mix of teaching techniques (among Sameness and Difference Principle, Setup Principle, Contextualization Technique, Storytelling Technique, Simple Explanation)
   - Specialized techniques should be chosen over simple explanations whenever applicable
   - Each technique has specific, actionable implementation suggestions
   - Sameness and Difference Principle must be used only for:
     * Only for concepts with subtle, non-obvious differences that could confuse AP students
     * Not for concepts that are clearly distinct to AP students (e.g., radio vs television, democracy vs monarchy)
     * Should help students understand nuanced distinctions (e.g., capitalism vs mercantilism, different forms of democracy)

4. NO FACT IDs
   - Striclty ensure no fact ids are present in the video plan. These facts ids would be present in knowledge graph input (such as c_UFH7, c_vwY1 etc.) but they must not appear in the video plan anywhere.

5. FACTS COVERAGE
   - Ensure all lesson facts are present in the video plan
   - Ensure all cross-unit connecting facts are present in the video plan
   - Ensure the lesson facts and cross unit facts are not mixed and are present in their respective fields.

6. FOCUS ON MAIN CONTENT
   - The video plan suggestions and choices should be focused on the main content of the facts of that particular concept, not side information to good to know things.
   - Any choice or suggestion that talks about side things (not the main content of the facts) should be rejected.

Output a JSON object with this format:
{{
    "qc_pass": true/false,
    "feedback": "Detailed feedback message if qc_pass is false, empty string if true"
}}

Important Instructions:
- Review thoroughly against all requirements
- Set qc_pass=true only if ALL requirements are met
- If qc_pass=false, provide specific, actionable feedback
- Focus on substantive issues, not minor details
- Feedback should be clear enough for the generator to make specific improvements
- Feedback should be very specific with what to change, where to change, and how to change
- Don't just mention that this requirement is not met, tell how to fix it, what exact change should be made

Provide only the JSON output, nothing else.
"""

FINAL_TOUCHUPS_SYSTEM_PROMPT = """You are an AI assistant tasked with enhancing a video lesson plan by performing specific touch-up tasks and creating secondary fields. Your goal is to improve the plan and provide additional information that will be useful for the video production team.

You will perform the following tasks on this plan:
<tasks>
1. Introduce a new field named "simple_title" for both the lesson and each section. This will serve as a simplified version of the existing lesson and section titles, removing complex terms while still accurately representing the content.
  - Only simplify when necessary, otherwise, duplicate the original title. If the title doesn't contain any history-specific terminology, maintain the original title verbatim.
    - If the title uses general language or common knowledge, retain the title as it is. 
         - This relates to specific terms, but the names of empires, kingdoms, and countries should remain unchanged. Please ensure that the names of these empires, kingdoms, dynasties, and so on, are kept exactly as they are, without any simplification.
    - Also simplify the title if it contains unnecessarily complex obfuscating vocabulary. 
    - Be reluctant to simplify the title, simplify only in the extreme case of complex subject-specific terminology being used, otherwise preserve the title exactly as is.
  - If you choose to simplify the title, make sure it still thoroughly represents the original title and the lesson's/section's core content. It shouldn't just eliminate complex terms, but replace them.
  - Here are some examples:
    - Titles without specific historical terminology, which should not be simplified: 
        - "Development and Expansion of Land Based Empires",  
        - "Cultural Exchange through Trade Routes"
        - "Women's Roles in Society"
        - "Technology Innovations under the Song Dynasty"
    - Titles with specific historical terminology that require simplification:
       - "The Meiji Restoration" → "Japan's Modernization"
       - "The Industrial Revolution" → "Rise of Factories"
       - "The Protestant Reformation" → "Church's Reforms Movement"
       - "Green Revolution" → "Farming Breakthroughs"
       - "The Socioeconomic Ramifications of Industrialization" → "Effects of Industry Growth"
       - "Agricultural Methodologies in Medieval Societies" → "Farming in Middle Ages"
       - "Mercantilism during the Bourbon Dynasty" → "Trade Economics during the Bourbon Dynasty" (Mercantilism simplified but Bourbon Dynasty kept as name of empire)
  - Keep the titles concise, ideally no more than four words.
  - VERY IMPORTANT: Do not lose out on details or context of the original title when simplifying.
   - Some bad examples (Do not do this):
     - "20th-Century Global Technological Transformations" → "Modern Technology Changes"
     - "Song Dynasty Confucian Governance" -> "Chinese Government and Values"
     Here the simplification is losing out on the details of the original title like "20th-Century" and "Song Dynasty"
     Instead "20th-Century Tech Changes" is better and best to leave "Song Dynasty Confucian Governance" as it is.
</tasks>

Instructions for each task:
1. Read through the entire plan carefully to understand its structure and content.
2. For each task listed above, perform the required modifications or additions to the plan.
3. If a task requires you to generate new content, ensure it is consistent with the tone and style of the original plan.
4. If you need to make assumptions to complete a task, state them clearly in your response.
5. Be creative but practical in your additions, keeping in mind the purpose of a video lesson.
6. VERY IMPORTANT: Do not lose out on details or context of the original title when simplifying.

After completing all tasks, format your output as a JSON object. Finally, generate a short wrapper prompt that summarizes the changes and additions you've made to the original plan. This prompt should be concise (no more than 2-3 sentences) and highlight the key enhancements.

Provide your complete response in the following format:
<response>
<json>
{
    "<lesson_title>": {
        "touchup_fields": {...},
        "sections":{
            "<section_title>": {
                "touchup_fields": {...}
            }
        }
    }
}
</json>
</response>"""

FINAL_TOUCHUPS_USER_PROMPT = """Here is the original video lesson plan:
<plan>
{plan}
</plan>
"""


def get_historical_figures_prompt(video_plan: Dict[str, Any]) -> str:
    return HISTORICAL_FIGURES_PROMPT.format(video_plan=json.dumps(video_plan, indent=2))

def get_video_plan_qc_prompt(subject: str, KGinput: str, video_plan: Dict[str, Any]) -> str:
    return VIDEO_PLAN_QC_PROMPT.format(
        subject=subject,
        KGinput=KGinput,
        video_plan=json.dumps(video_plan, indent=2)
    )
