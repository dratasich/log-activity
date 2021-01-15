#!/usr/bin/env python3

# %% Imports
import argparse
import logging
import os.path
import socket
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from aw_client import ActivityWatchClient
from aw_core.models import Event

# %% Settings
BUCKET_AFK = f"aw-watcher-afk_{socket.gethostname()}"
BUCKET_GIT = f"aw-git-hooks_{socket.gethostname()}"
DATE_FROM = datetime.today().replace(day=1, hour=4, minute=0, second=0, microsecond=0)
DATE_TO = datetime.now()

# arguments
desc = "List activities per date."
parser = argparse.ArgumentParser(description=desc)
parser.add_argument(
    "-c",
    "--commits-sort-by",
    choices=["issue", "timestamp"],
    default="timestamp",
    help=f"""Print commits either per issue or print all commits ordered by time.""",
)
parser.add_argument(
    "-f",
    "--from",
    dest="date",
    default=DATE_FROM,
    type=lambda d: datetime.strptime(d, "%Y-%m-%d").replace(
        hour=4, minute=0, second=0, microsecond=0
    ),
    help=f"""Start date. Defaults to {DATE_FROM} (first day of the current month).""",
)
parser.add_argument(
    "-v", "--verbose", action="store_true", help="Verbose logging (debug)."
)
args = parser.parse_args()

if args.verbose:
    logging.basicConfig(level=logging.DEBUG)


# %% Helpers


def str_date(date):
    return date.astimezone().strftime("%Y-%m-%d")


def str_time(date):
    if date is None:
        return "00:00"
    return date.astimezone().strftime("%H:%M")


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


def to_dataframe(hooks: List[GitHook]):
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


def issue_to_string(i: pd.DataFrame):
    issue = i.iloc[0].issue
    summary = ""
    titles = i[["origin", "summary"]].mask(i.summary.eq("None")).dropna()
    if len(titles) > 0:
        repos = []
        titles.groupby("origin").apply(
            lambda o: repos.append(
                os.path.basename(o.iloc[0].origin).split(".")[0]
                + ": "
                + ", ".join(o.summary)
            )
        )
        summary = f" ({'; '.join(repos)})"
    return f"{issue if issue != 'None' else 'other'}{summary}"


# %% Get events
client = ActivityWatchClient("report-client")

date = args.date
while date < DATE_TO:
    query = f"""
    events = query_bucket('{BUCKET_AFK}');
    RETURN = sort_by_timestamp(events);
    """
    afk = client.query(query, [(date, date + timedelta(days=1))])
    query = f"""
    events = query_bucket('{BUCKET_GIT}');
    RETURN = sort_by_timestamp(events);
    """
    git = client.query(query, [(date, date + timedelta(days=1))])
    date = date + timedelta(days=1)

    # new week formatting
    weekday = date.weekday()
    if weekday == 1:
        print("{:-^80}".format(f" Week {date.isocalendar()[1]} "))

    if len(afk[0]) == 0:
        # no events at all on this day
        continue

    # start and end of day
    first_event = Event(**afk[0][0])
    last_event = Event(**afk[0][-1])
    active = timedelta(
        seconds=sum([e["duration"] for e in afk[0] if e["data"]["status"] == "not-afk"])
    )
    print(
        f"{str_date(first_event.timestamp)} {first_event.timestamp.strftime('%a')}"
        + f" | {str_time(first_event.timestamp)} - {str_time(last_event.timestamp + last_event.duration)}"
        + f" (not-afk {active})"
    )

    # git commits
    if len(git[0]) > 0:
        hooks = [GitHook(**e["data"]) for e in git[0]]
        if args.commits_sort_by == "timestamp":
            [print(h) for h in hooks if h.hook == "post-commit"]
        elif args.commits_sort_by == "issue":
            df = to_dataframe(hooks)
            commits = (
                df[df.hook == "post-commit"]
                .astype(str)
                .drop_duplicates(["origin", "summary", "issue"])
                .groupby("issue")
                .apply(lambda g: print(f"  {issue_to_string(g)}"))
            )
