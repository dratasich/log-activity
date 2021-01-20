#!/usr/bin/env python3

# %% Imports
import argparse
import logging
import os.path
import socket
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from aw_client import ActivityWatchClient
from aw_core.models import Event

from models import *

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
    logging.basicConfig(
        level=logging.DEBUG, format="[%(asctime)-15s] [%(levelname)-5s] %(message)s"
    )


# %% Helpers


def str_date(date):
    return date.astimezone().strftime("%Y-%m-%d")


def str_time(date):
    if date is None:
        return "00:00"
    return date.astimezone().strftime("%H:%M")


def round_timedelta(tm: timedelta, round_to_s=timedelta(minutes=15).total_seconds()):
    tm_rounded = timedelta(
        seconds=int((tm.total_seconds() + round_to_s / 2) / (round_to_s)) * (round_to_s)
    )
    logging.debug(f"{round_to_s}s-rounded {tm} to {tm_rounded}")
    return tm_rounded


def round_datetime(tm: datetime, round_to_min=15):
    tm_rounded = tm + timedelta(minutes=float(round_to_min) / 2)
    tm_rounded -= timedelta(
        minutes=tm_rounded.minute % round_to_min,
        seconds=tm_rounded.second,
        microseconds=tm_rounded.microsecond,
    )
    logging.debug(f"{round_to_min}s-rounded {tm} to {tm_rounded}")
    return tm_rounded


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

    # active time
    active = timedelta(
        seconds=sum([e["duration"] for e in afk[0] if e["data"]["status"] == "not-afk"])
    )
    short_pause = timedelta(minutes=5)
    active_incl_short_pauses = active + timedelta(
        seconds=sum(
            [
                e["duration"]
                for e in afk[0]
                if e["data"]["status"] == "afk" and e["duration"] < short_pause.seconds
            ]
        )
    )
    logging.debug(
        f"not-afk: {active}, with pauses < {short_pause.seconds}s: {active_incl_short_pauses}"
    )
    working_hours = active_incl_short_pauses
    if active_incl_short_pauses >= timedelta(hours=6):
        logging.debug(f"add 30min break")
        working_hours += timedelta(minutes=30)
    working_hours_rounded = round_timedelta(working_hours)

    # start and end of day
    first_event = Event(**afk[0][0])
    last_event = Event(**afk[0][-1])
    start = round_datetime(first_event.timestamp)
    end = round_datetime(last_event.timestamp + last_event.duration)

    print(
        f"{str_date(start)} {start.strftime('%a')}"
        + f" | {str_time(start)} - {str_time(end)}"
        + f" ({working_hours_rounded})"
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
                .drop_duplicates(["origin", "summary"])
                .groupby("issue")
                .apply(lambda g: print(f"  {issue_to_string(g)}"))
            )
