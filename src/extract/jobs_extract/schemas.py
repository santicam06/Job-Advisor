from enum import Enum
from typing import List
from pydantic import BaseModel, Field

class WorkModality(str, Enum):
    not_listed = "Not listed."
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"

class YearsExperience(str, Enum):
    not_listed = "Not listed."
    junior = "0 - 2 years"
    intermediate = "3 - 5 years"
    senior = "6 - 9 years"
    lead = "10+ years"



class JobPosting(BaseModel):
    job_title: str = Field(description="The specific role position to apply", default="Not listed.")
    company_name: str = Field(description="Name of the hiring company", default="Not listed.")
    work_modality: WorkModality = Field(description="Work mode for the role, one of: [not_listed, remote, hybrid, onsite]", default=WorkModality.not_listed)
    required_skills: List[str] = Field(description="Technical/Soft skills required by the applicant for the role", default=["Not listed."])
    nice_have_skills: List[str] = Field(description="Skills not mandatory to have for applying, but add relevance to the applicant's profile", default=["Not listed."])
    experience_level: YearsExperience = Field(description="The range of years of experience required for the role, one of: [not_listed, junior, intermediate, senior, lead]", default=YearsExperience.not_listed)
    education_requirements: str = Field(description="Educational certificates or other kinds of formation (e.g. bootcamps, self learning) stated in the application's requirements", default="Not listed.")
    salary: str = Field(description="The monetary salary ammount either in range or punctual, for the role position. Can be per hour, year, or month. If mentioned add also the currency ISO code", default="Not listed.")
    key_responsibilities: List[str] = Field(description="The duties that the applicant would perform in the role", default=["Not listed."])
    relevant_data: List[str] = Field(description="All kinds of important information about the employer of the job posting", default=["Not found."])