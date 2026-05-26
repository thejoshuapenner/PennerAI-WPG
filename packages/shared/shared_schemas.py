from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date

class FindingSchema(BaseModel):
    report_num: str = Field(description="WA SAO audit report number")
    jurisdiction: str = Field(description="The audited agency/jurisdiction name")
    type: str = Field(description="Audit type (e.g. Financial, Accountability)")
    category: str = Field(description="Audit category (e.g. Procurement, Internal Controls)")
    summary: str = Field(description="1-2 sentence overview of findings")
    root_cause: Optional[str] = Field(None, description="The identified cause of the failure")
    dollar_impact: int = Field(0, description="Estimated financial impact in USD")
    embedding: Optional[List[float]] = Field(None, description="1536-dim semantic representation")

class MeetingActionSchema(BaseModel):
    event_id: str
    jurisdiction: str
    committee: Optional[str] = None
    meeting_date: Optional[date] = None
    key_action: str
    dollar_amount: int = 0
    vote_outcome: Optional[str] = None

class MergedActionSchema(BaseModel):
    event_id: str
    jurisdiction: str
    committee: Optional[str] = None
    meeting_date: Optional[date] = None
    key_action: str
    vendor: Optional[str] = None
    dollar_amount: int = 0
    vote_outcome: Optional[str] = None
    embedding: Optional[List[float]] = None

class ProcessedIntentSchema(BaseModel):
    file_id: str
    jurisdiction: str
    meeting_date: Optional[date] = None
    event_id: Optional[str] = None
    doc_type: Optional[str] = None
    item_number: Optional[str] = None
    agenda_item_title: str
    key_action: str
    vendor: Optional[str] = None
    dollar_amount: int = 0
    vote_outcome: Optional[str] = None
    primary_entity: Optional[str] = None
    embedding: Optional[List[float]] = None

class AlertSubscriptionSchema(BaseModel):
    name: str
    email: str
    topics: str
    jurisdiction: Optional[str] = None
    query: Optional[str] = None

class JurisdictionSchema(BaseModel):
    name: str
    entity_type: str
    county: Optional[str] = None
    population: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

class BudgetSchema(BaseModel):
    jurisdiction_name: str
    entity_type: str
    fiscal_year: int
    total_revenue: float
    total_expenditures: float
    fund_balance_beginning: Optional[float] = None
    fund_balance_ending: Optional[float] = None
    source_url: Optional[str] = None

class BudgetItemSchema(BaseModel):
    category_type: str
    major_category: str
    amount: float
    account_code: Optional[str] = None
    description: Optional[str] = None
    embedding: Optional[List[float]] = None

class GrantSchema(BaseModel):
    grant_title: str
    grant_id: Optional[str] = None
    awarding_agency: str
    recipient_jurisdiction: str
    recipient_entity_type: Optional[str] = None
    award_amount: float
    award_date: Optional[date] = None
    performance_period_start: Optional[date] = None
    performance_period_end: Optional[date] = None
    purpose_category: Optional[str] = None
    funding_source: Optional[str] = None
    source_url: Optional[str] = None
    embedding: Optional[List[float]] = None

class SchoolDistrictFinancialsSchema(BaseModel):
    district_name: str
    fiscal_year: int
    enrollment: Optional[float] = None
    total_revenue: float
    total_expenditures: float
    levy_amount: Optional[float] = None
    special_education_spending: Optional[float] = None
    federal_funding_amount: Optional[float] = None
    source_url: Optional[str] = None
    embedding: Optional[List[float]] = None
