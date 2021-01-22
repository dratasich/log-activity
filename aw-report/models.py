from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd


# flatten json, e.g., `data` in aw events
def flatten_json(y):
    out = {}

    def flatten(x, name=""):
        if type(x) is dict:
            for a in x:
                flatten(x[a], a)
        else:
            out[name] = x

    flatten(y)
    return out


@dataclass
class Event:
    id: int
    duration: float
    timestamp: datetime

    def __post_init__(self):
        self.timestamp = datetime.fromisoformat(str(self.timestamp))

    @property
    def timedelta(self):
        return timedelta(seconds=duration)


@dataclass
class Afk(Event):
    status: str
    afk: bool = field(init=False)

    def __post_init__(self):
        self.timestamp = datetime.fromisoformat(str(self.timestamp))
        self.afk = self.status == "afk"


@dataclass
class GitHook:
    hook: str
    origin: Optional[str] = None
    branch: Optional[str] = None
    summary: Optional[str] = None
    issues: List[str] = field(default_factory=list)

    def __str__(self):
        issue_list = f" ({', '.join(self.issues)})" if len(self.issues) > 0 else ""
        return f"  - {self.origin} ({self.branch}): {self.summary}{issue_list}"


@dataclass
class GitHookDto:
    hook: str
    origin: Optional[str] = None
    branch: Optional[str] = None
    summary: Optional[str] = None
    issue: Optional[str] = None


def hooks_to_dataframe(hooks: List[GitHook]):
    # flatten issue list
    hooksDto = []
    for h in hooks:
        new_dict = h.__dict__.copy()
        issues = new_dict.pop("issues")
        # no issues referenced
        if len(issues) == 0:
            hooksDto.append(GitHookDto(**new_dict))
            continue
        # add a row for each issue
        for i in issues:
            new_dict["issue"] = i
            hooksDto.append(GitHookDto(**new_dict))
    return pd.DataFrame([h.__dict__ for h in hooksDto])


@dataclass
class WebVisit(Event):
    title: str
    url: str
    audible: bool
    incognito: bool
    tabCount: int
    categories: List[str] = field(default_factory=list)
    project_excl: Optional[str] = field(init=False, default=None)

    def __post_init__(self):
        self.timestamp = datetime.fromisoformat(str(self.timestamp))


def visits_to_dataframe(visits: List[WebVisit]):
    return pd.DataFrame([v.__dict__ for v in visits])


@dataclass
class Edit(Event):
    language: str
    project: str
    file: str
    categories: List[str] = field(default_factory=list)
    project_excl: Optional[str] = field(init=False, default=None)

    def __post_init__(self):
        self.timestamp = datetime.fromisoformat(str(self.timestamp))
