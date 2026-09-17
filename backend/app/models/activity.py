from __future__ import annotations
from datetime import date, datetime
from typing import Literal, Any
from pydantic import BaseModel, Field

ActivityType=Literal['investigation','confirmation','implementation','effect','consolidation']
class ActivityEntry(BaseModel):
    event_id:str
    project_id:str
    event_type:ActivityType
    revision:int=Field(ge=1)
    title:str=''
    object:str=''
    owner:str=''
    activity_start:date|None=None
    activity_end:date|None=None
    uploaded_at:datetime|None=None
    measures:list[dict[str,Any]]=Field(default_factory=list)
    observations:str=''
    mechanism:str=''
    contribution_note:str=''
    status:Literal['actual','planned','pending']='pending'

class ActivityInput(BaseModel):
    event_id:str|None=None
    event_type:ActivityType
    title:str=''; object:str=''; owner:str=''; activity_start:date|None=None; activity_end:date|None=None; uploaded_at:datetime|None=None
    measures:list[dict[str,Any]]=Field(default_factory=list); observations:str=''; mechanism:str=''; contribution_note:str=''; status:Literal['actual','planned','pending']='pending'
    expected_revision:int=Field(ge=0)
