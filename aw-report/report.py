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
from dateutil.tz import tzlocal

from aw_client import ActivityWatchClient
from models.activities import Activities
from models.working_hours import WorkingHours
from reader.activitywatch import (ActivityWatchGitReader, ActivityWatchReader,
                                  ActivityWatchWebReader)
from reader.m365calendar import M365CalendarReader
from utils import *
from writer.working_time import WorkingTimeWriter

# %% Settings
BUCKET_AFK = f"aw-watcher-afk_{socket.gethostname()}"
BUCKET_EDITOR = f"aw-watcher-editor_{socket.gethostname()}"
BUCKET_GIT = f"aw-git-hooks_{socket.gethostname()}"
DATE_FROM = datetime.today().astimezone(tz=tzlocal()).replace(day=1, hour=4, minute=0, second=0, microsecond=0)
DATE_TO = datetime.now().astimezone(tz=tzlocal())

# arguments
desc = "List activities per date."
parser = argparse.ArgumentParser(description=desc)
parser.add_argument(
    "-f",
    "--from",
    dest="date",
    default=DATE_FROM,
    type=lambda d: datetime.strptime(d, "%Y-%m-%d").replace(
        hour=4, minute=0, second=0, microsecond=0
    ).astimezone(tz=tzlocal()),
    help=f"""Start date. Defaults to {DATE_FROM} (first day of the current month).""",
)
parser.add_argument(
    "-v", "--verbose", action="store_true", help="Verbose logging (debug)."
)
parser.add_argument(
    "-m",
    "--meetings",
    type=str,
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

logger.debug("aw: categorize events")
edits_all.categorize(r_editor, ["editor_project", "editor_file", "editor_language"], single=True)
git_all.categorize_issues(r_git_issues, r_git_repos)
web_all.categorize(r_web, ["web_url", "web_title"], single=True)


# load calendar (not synced in aw)
if args.meetings is not None:
    logger.debug("calendar: read m365 json")
    calendar = M365CalendarReader(args.meetings)

# working time per date
short_pause = timedelta(minutes=10)
afk = afk_all.events
afk = afk[~afk.afk | (afk.duration < short_pause.seconds)] \
    .groupby("date") \
    .agg({"duration": sum, "timestamp": [min, max]})
# align working hours
afk[["active", "lunch_incl"]] = afk.apply(
    lambda r: WorkingHours.align_hours(timedelta(seconds=r["duration", "sum"])),
    result_type="expand",
    axis=1,
)
afk[["start", "end"]] = afk.apply(
    lambda r: WorkingHours.align_range(
        r["timestamp", "min"].to_pydatetime(),
        r["timestamp", "max"].to_pydatetime(),
        r["active", ""].to_pytimedelta()),
    result_type="expand",
    axis=1,
)
wt = WorkingTimeWriter(afk)
wt.save()
logger.debug(f"wrote working time to file")

# activities per date and project
activities = Activities()
activities.add_df(edits_all.events, {"category": "project", "editor_project": "desc"})
activities.add_df(git_all.events, {"category": "project", "git_summary": "desc"})
activities.add_df(web_all.events, {"category": "project", "web_title": "desc"})
if args.meetings is not None:
    activities.add_df(calendar.events_within(DATE_RANGE), {"subject": "desc", "categories": "project", "duration": "time"})

activities.save()
logger.debug(f"wrote activities to file")
