from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd


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
class WebVisit:
    title: str
    url: str
    audible: bool
    incognito: bool
    tabCount: int


def visits_to_dataframe(visits: List[WebVisit]):
    return pd.DataFrame([v.__dict__ for v in visits])
