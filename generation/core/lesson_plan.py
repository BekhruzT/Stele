def get_unit_lesson_plan(unit_title, lesson_plan):
    for _unit_title, unit_lesson_plan in lesson_plan.get("Units", {}).items():
        if _unit_title == unit_title:
            return unit_lesson_plan


def get_chapter_lesson_plan(unit_title, chapter_title, lesson_plan):
    unit_lesson_plan = get_unit_lesson_plan(unit_title, lesson_plan)
    for _chapter_title, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
        if _chapter_title == chapter_title:
            return chapter_lesson_plan


def get_section_lesson_plan(unit_title, chapter_title, section_title, lesson_plan):
    chapter_lesson_plan = get_chapter_lesson_plan(unit_title, chapter_title, lesson_plan)
    for _section_title, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
        if _section_title == section_title:
            return section_lesson_plan


def get_subsection_lesson_plan(unit_title, chapter_title, section_title, subsection_title, lesson_plan):
    section_lesson_plan = get_section_lesson_plan(unit_title, chapter_title, section_title, lesson_plan)
    for _subsection_title, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
        if _subsection_title == subsection_title:
            return subsection_lesson_plan


def remove_concepts(lesson_plan):
    new_lesson_plan = lesson_plan.copy()
    for _, unit_lesson_plan in new_lesson_plan.get("Units", {}).items():
        for _, chapter_lesson_plan in unit_lesson_plan.get("Chapters", {}).items():
            for _, section_lesson_plan in chapter_lesson_plan.get("Sections", {}).items():
                if "Concepts" in section_lesson_plan:
                    del section_lesson_plan["Concepts"]
                for _, subsection_lesson_plan in section_lesson_plan.get("Subsections", {}).items():
                    del subsection_lesson_plan["Concepts"]
    return new_lesson_plan
