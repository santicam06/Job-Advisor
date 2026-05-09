

from typing import List
from pydantic import BaseModel, Field


class ResumeProfile(BaseModel):
    hard_skills: List[str] = Field(
        description=(
            'IT knowledge abilities such as: Programming languages, frameworks, tools, platforms'
        ),
        default=["Not listed."],
    )
    soft_skills: List[str] = Field(
        description="Attributes such as: Communication, leadership, collaboration, problem-solving, etc...",
        default=["Not listed."],
    )
    work_experience: List[str] = Field(
        description="Roles worked in, companies, durations/periods, key responsibilities and achievements",
        default=["Not listed."],
    )
    education: List[str] = Field(
        description="Degrees, masters or other post graduate qualifications, institutions names, relevant coursework",
        default=["Not listed."],
    )
    certifications_and_training: List[str] = Field(
        description="Professional certifications from institutions or online portals, completed short-term courses",
        default=["Not listed."],
    )
    projects_and_accomplishments: List[str] = Field(
        description="Notable projects, quantifiable achievements, portfolio items, professional collaborations, important contributions to open source repositories, etc...",
        default=["Not listed."],
    )
    keywords_and_domain_expertise: List[str] = Field(
        description=(
            'Industry-specific terminology, methodologies '
        ),
        default=["Not listed."],
    )
