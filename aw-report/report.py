#!/usr/bin/env python3

# %% Imports
from aw_core.models import Event
from aw_client import ActivityWatchClient
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List


# %% Settings
BUCKET_AFK = "aw-watcher-afk_nils"
BUCKET_GIT = "aw-git-hooks_nils"
DATE_FROM = datetime.today().replace(day=1, hour=4, minute=0, second=0, microsecond=0)
DATE_TO = datetime.now()


# %% Helpers

def str_date(date):
    return date.strftime('%Y-%m-%d')

def str_time(date):
    if date is None:
        return "00:00"
    return date.strftime('%H:%M')

@dataclass
class GitCommit:
    hook: str
    origin: str = "unknown origin"
    branch: str = "unknown branch"
    summary: str = "no summary"
    issues: List[str] = field(default_factory=list)


# %% Get events
client = ActivityWatchClient("report-client")

date = DATE_FROM
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
    active = timedelta(seconds=sum([e['duration'] for e in afk[0] if e['data']['status'] == "not-afk"]))
    print(f"{str_date(first_event.timestamp)} {first_event.timestamp.strftime('%a')}"
          + f" | {str_time(first_event.timestamp)} - {str_time(last_event.timestamp)}"
          + f" (not-afk {active})"
          )

    # git commits
    if len(git[0]) > 0:
        commits = [GitCommit(**e['data']) for e in git[0] if e['data']['hook'] == "post-commit"]
        [print(f"  - {c.origin}: {c.summary} ({', '.join(c.issues)})") for c in commits]
