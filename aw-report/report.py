#!/usr/bin/env python3

# %% Imports
import argparse
import ast
import configparser
import logging
import os.path
import re
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
from aw_client import ActivityWatchClient
from dateutil.tz import tzlocal

from models.activities import Activities
from models.working_hours import WorkingHours
from reader.activitywatch import (ActivityWatchGitReader, ActivityWatchReader,
                                  ActivityWatchWebReader)
from reader.m365calendar import M365CalendarReader
from utils import *

# %% Settings
BUCKET_AFK = f"aw-watcher-afk_{socket.gethostname()}"
BUCKET_EDITOR = f"aw-watcher-editor_{socket.gethostname()}"
BUCKET_GIT = f"aw-git-hooks_{socket.gethostname()}"
vienna = pytz.timezone("Europe/Vienna")
DATE_FROM = vienna.localize(datetime.today().replace(day=1, hour=4, minute=0, second=0, microsecond=0))
DATE_TO = vienna.localize(datetime.now())

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
    type=lambda d: vienna.localize(datetime.strptime(d, "%Y-%m-%d").replace(
        hour=4, minute=0, second=0, microsecond=0
    )),
    help=f"""Start date. Defaults to {DATE_FROM} (first day of the current month).""",
)
parser.add_argument(
    "-v", "--verbose", action="store_true", help="Verbose logging (debug)."
)
parser.add_argument(
    "-t", "--time-only", action="store_true",
    help="Print only come and go, and total time per day."
)
parser.add_argument(
    "-m",
    "--meetings",
    type=str,
    default=f"{DATE_FROM.strftime('%Y-%m')}_m365calendar.json",
)
args = parser.parse_args()
DATE_RANGE = (args.date, DATE_TO)

logging.basicConfig(format="[%(levelname)-5s] %(message)s")
logger = logging.getLogger(__name__)
if args.verbose:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


# Advanced configuration
config = configparser.ConfigParser()
config.read("config.ini")


# %% Helpers


def str_date(date: datetime):
    return date.astimezone(tz=tzlocal()).strftime("%Y-%m-%d")


def str_time(date: datetime):
    if date is None:
        return "00:00"
    return date.astimezone(tz=tzlocal()).strftime("%H:%M")


def str_delta(time: timedelta):
    h = int(time.total_seconds() / 3600)
    m = int((time.total_seconds() % 3600) / 60)
    return f"{h:02}:{m:02}"


def issue_to_string(i: pd.DataFrame):
    issue = str(i.iloc[0].git_issues)
    summary = ""
    titles = i[["git_origin", "git_summary"]].mask(i.git_summary.eq("None")).dropna()
    if len(titles) > 0:
        repos = []
        titles.groupby("git_origin").apply(
            lambda o: repos.append(
                os.path.basename(o.iloc[0].git_origin).split(".")[0]
                + ": "
                + ", ".join(o.git_summary)
            )
        )
        summary = "; ".join(repos)
    if issue == "None" or issue == "nan":
        return f"{summary}"
    else:
        return f"{issue} ({summary})"


# %% Get events
client = ActivityWatchClient("report-client")
# active time in front of the PC (afk..away-from-keyboard)
logger.debug(f"aw: get afk events")
afk_all = ActivityWatchReader(client)
afk_all.get([BUCKET_AFK], [DATE_RANGE], rename={"data": "afk"})
afk_all.events["afk"] = afk_all.events["afk_status"].apply(lambda s: s == "afk")
# events from editors
# on window change the event ends, as expected, i.e. events show active time (per file)
# https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.append.html
logger.debug(f"aw: get editor events")
edits_all = ActivityWatchReader(client)
edits_all.get([BUCKET_EDITOR.replace("editor", e) for e in ast.literal_eval(config["buckets"]["editors"])],
              [DATE_RANGE], rename={"data": "editor"})
logger.debug(f"aw: get git events")
git_all = ActivityWatchGitReader(client)
git_all.get([BUCKET_GIT], [DATE_RANGE], rename={"data": "git"})
logger.debug(f"aw: get web events")
web_all = ActivityWatchWebReader(client)
web_all.get([""], [DATE_RANGE], rename={"data": "web"})

# %% Categorize via regexes
def regexes(config_section: configparser.SectionProxy):
    return {
        category: re.compile(regex, re.IGNORECASE)
        for category, regex in config_section.items()
    }

# read and compile regexes from config
r_editor = regexes(config["project.editors"])
r_git_repos = regexes(config["project.repos"])
r_git_issues = regexes(config["project.issues"])
r_web = regexes(config["project.websites"])

logger.debug("aw: categorize editor events")
edits_all.categorize(r_editor, ["editor_project", "editor_file", "editor_language"], single=True)
git_all.categorize_issues(r_git_issues, r_git_repos)
web_all.categorize(r_web, ["web_url", "web_title"], single=True)


# load calendar (not synced in aw)
calendar = M365CalendarReader(args.meetings)

# working time per date
short_pause = timedelta(minutes=10)
afk = afk_all.events
afk = afk[~afk.afk | (afk.duration < short_pause.seconds)] \
    .groupby("date") \
    .agg({"duration": sum, "timestamp": [min, max]}) \
    .copy()

# activities per date and project
activities = Activities()
activities.add_df(edits_all.events, {"category": "project", "timestamp": "date", "duration": "time"})

activities.save()
logging.debug(f"wrote projects to file")


date = args.date
while date < DATE_TO:
    logger.debug(f">>> {date}")
    current_day = (date, date + timedelta(days=1))
    projects = Activities()

    logger.debug(f"filter aw events of {current_day}")
    afk = afk_all.events_within(current_day).copy()
    edits = edits_all.events_within(current_day).copy()
    git = git_all.events_within(current_day).copy()
    web = web_all.events_within(current_day).copy()

    # step for next day
    date = date + timedelta(days=1)

    # new week formatting
    weekday = date.weekday()
    if weekday == 1:
        print("{:=^80}".format(f" Week {date.isocalendar()[1]} "))
    else:
        print("{:-^80}".format(""))

    if len(afk) == 0:
        # no events at all on this day
        continue

    # active time
    active = timedelta(seconds=afk[~afk.afk].duration.sum())
    active_incl_short_pauses = timedelta(
        seconds=afk[~afk.afk | (afk.duration < short_pause.seconds)].duration.sum()
    )
    logger.debug(
        f"not-afk: {active}, with pauses < {short_pause.seconds}s: {active_incl_short_pauses}"
    )

    wh = WorkingHours(
        afk.iloc[0].timestamp,
        afk.iloc[-1].timestamp + timedelta(seconds=afk.iloc[-1].duration),
        active_incl_short_pauses,
    )

    print(
        f"{str_date(wh.start)} {wh.start.strftime('%a'):^6}"
        + f" | {str_delta(wh.hours)}"
        + f" | {str_time(wh.start)} - {str_time(wh.end)}"
        + f"{' (incl. lunch)' if wh.lunch_incl else ''}"
    )

    if args.time_only:
        continue

    # project percentage to active time based on editor events
    if len(edits) > 0:
        logger.debug(edits.groupby("category").duration.sum())
        edits.groupby("category").apply(
            lambda g: projects.add_item(
                g.iloc[0].category, current_day[0], timedelta(seconds=g.duration.sum())
            )
        )
        logger.debug(f"project considering editors:\n{projects}")

    # meetings
    meetings = calendar.events_from(current_day[0])
    if meetings is not None and len(meetings) > 0:
        # add info to projects
        meetings.groupby("categories").apply(
            lambda g: projects.add_item(
                g.iloc[0].categories,
                current_day[0],
                g.duration.sum(),
                "meetings: " + ", ".join(g.subject.to_list()),
            )
        )

    # git commits
    if len(git) > 0:
        if args.commits_sort_by == "timestamp":
            print(git[git.git_hook == "post-commit"])
        elif args.commits_sort_by == "issue":
            git.groupby(["category"]) \
                .apply(
                    lambda g: projects.add_item(
                        g.iloc[0].category,
                        current_day[0],
                        desc=", ".join(g.groupby("git_issues").apply(lambda i: issue_to_string(i)))
                    )
                )

    # web visits
    if len(web) > 0:
        web.groupby("category").apply(
            lambda g: projects.add_item(
                g.iloc[0].category,
                current_day[0],
                timedelta(seconds=g.duration.sum()),
                ", ".join(
                    g[g.duration >= timedelta(minutes=5).total_seconds()]
                    .sort_values(by="duration")
                    .tail()
                    .web_title.drop_duplicates()
                    .to_list()
                ),
            )
        )
        logger.debug(f"web:\n{web.groupby('category').duration.sum()}")

    # print time and description per projects
    projects = projects.aggregate(current_day)
    # TODO: round time and add other
    for p in projects.index:
        info = projects.loc[p]
        print(f"  {p[1]:<15} | {str_delta(info.time)} | {info.desc}")
