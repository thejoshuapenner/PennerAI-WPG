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
