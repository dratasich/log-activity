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
from typing import Dict, List, Optional

import pandas as pd
from aw_client import ActivityWatchClient
from dateutil.tz import tzlocal

from utils import *

# %% Settings
BUCKET_AFK = f"aw-watcher-afk_{socket.gethostname()}"
BUCKET_WINDOW = f"aw-watcher-window_{socket.gethostname()}"
BUCKET_WEB = f"aw-watcher-web-firefox"
BUCKET_EDITOR = f"aw-watcher-editor_{socket.gethostname()}"
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

logging.basicConfig(format="[%(asctime)-15s] [%(levelname)-5s] %(message)s")
logger = logging.getLogger(__name__)
if args.verbose:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


# Advanced configuration
config = configparser.ConfigParser()
config.read("config.ini")
if not config.has_section("projects"):
    logger.warning("No configuration for project mapping (fill `config.ini`)!")


# %% Helpers


def str_date(date: datetime):
    return date.astimezone(tz=tzlocal()).strftime("%Y-%m-%d")


def str_time(date: datetime):
    if date is None:
        return "00:00"
    return date.astimezone(tz=tzlocal()).strftime("%H:%M")


def round_timedelta(tm: timedelta, round_to_s=timedelta(minutes=15).total_seconds()):
    tm_rounded = timedelta(
        seconds=int((tm.total_seconds() + round_to_s / 2) / (round_to_s)) * (round_to_s)
    )
    logger.debug(f"{round_to_s}s-rounded {tm} to {tm_rounded}")
    return tm_rounded


def round_datetime(tm: datetime, round_to_min=15):
    tm_rounded = tm + timedelta(minutes=float(round_to_min) / 2)
    tm_rounded -= timedelta(
        minutes=tm_rounded.minute % round_to_min,
        seconds=tm_rounded.second,
        microseconds=tm_rounded.microsecond,
    )
    logger.debug(f"{round_to_min}s-rounded {tm} to {tm_rounded}")
    return tm_rounded


def issue_to_string(i: pd.DataFrame):
    issue = i.iloc[0].git_issues
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
        summary = f" ({'; '.join(repos)})"
    return f"{issue if issue != 'None' and issue != 'nan' else 'other'}{summary}"


# %% Get events
client = ActivityWatchClient("report-client")


def aw_events(bucket: str, time_ranges: [(datetime, datetime)], rename={}):
    query = f"""
    events = query_bucket('{bucket}');
    RETURN = sort_by_timestamp(events);
    """
    events = client.query(query, time_ranges)[0]
    df = pd.DataFrame([flatten_json(e, rename) for e in events])
    if not df.empty:
        df.timestamp = pd.to_datetime(df.timestamp)
    return df


date = args.date
while date < DATE_TO:
    logger.debug(f">>> {date}")
    current_day = (date, date + timedelta(days=1))

    logger.debug(f"get aw events of {current_day}")
    # window bucket shows the current/active application
    window = aw_events(BUCKET_WINDOW, [current_day], rename={"data": "window"})
    # active time in front of the PC (afk..away-from-keyboard)
    afk = aw_events(BUCKET_AFK, [current_day], rename={"data": "afk"})
    afk["afk"] = afk["afk_status"].apply(lambda s: s == "afk")
    # duration of web events cannot be used to calculate project time
    # on window change, the events do not end :(
    web = aw_events(BUCKET_WEB, [current_day], rename={"data": "web"})
    # events from editors
    # on window change the event ends, as expected, i.e. events show active time (per file)
    # https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.DataFrame.append.html
    edits = pd.concat(
        [
            aw_events(
                BUCKET_EDITOR.replace("editor", editor),
                [current_day],
                rename={"data": "editor"},
            )
            for editor in ast.literal_eval(config["buckets"]["editors"])
        ],
        ignore_index=True,
    )
    git = aw_events(BUCKET_GIT, [current_day], rename={"data": "git"})

    # step for next day
    date = date + timedelta(days=1)

    # new week formatting
    weekday = date.weekday()
    if weekday == 1:
        print("{:-^80}".format(f" Week {date.isocalendar()[1]} "))

    if len(afk) == 0:
        # no events at all on this day
        continue

    # active time
    active = timedelta(seconds=afk[~afk.afk].duration.sum())
    short_pause = timedelta(minutes=5)
    active_incl_short_pauses = timedelta(
        seconds=afk[~afk.afk | (afk.duration < short_pause.seconds)].duration.sum()
    )
    logger.debug(
        f"not-afk: {active}, with pauses < {short_pause.seconds}s: {active_incl_short_pauses}"
    )
    working_hours = active_incl_short_pauses
    if active_incl_short_pauses >= timedelta(hours=6):
        logger.debug(f"add 30min break")
        working_hours += timedelta(minutes=30)
    working_hours_rounded = round_timedelta(working_hours)

    # start and end of day
    start = round_datetime(afk.iloc[0].timestamp)
    end = round_datetime(
        afk.iloc[-1].timestamp + timedelta(seconds=afk.iloc[-1].duration)
    )

    print(
        f"{str_date(start)} {start.strftime('%a')}"
        + f" | {str_time(start)} - {str_time(end)}"
        + f" ({working_hours_rounded})"
    )

    # categorize web and edits based on regex
    regexes = {
        category: re.compile(regex, re.IGNORECASE)
        for category, regex in config["categories"].items()
    }

    def categories(s: str, regexPerCategory: Dict[str, re.Pattern]):
        return [c for c, r in regexPerCategory.items() if len(r.findall(s)) > 0]

    regexes_proj = {
        p: re.compile(r, re.IGNORECASE) for p, r in config["projects"].items()
    }

    def project(s: str, regexPerProject: Dict[str, re.Pattern]):
        for p, r in regexes_proj.items():
            if len(r.findall(s)) > 0:
                return p
        return None

    logger.debug("Categorize website visits")
    web["categories"] = web.apply(
        lambda row: categories(row.web_url + row.web_title, regexes), axis=1
    )
    web["is_categorized"] = web.apply(lambda row: len(row.categories) > 0, axis=1)
    logger.debug(f"total: {len(web)}")
    logger.debug(f"categorized: {len(web[web.is_categorized])}")
    logger.debug(f"missing categorization, e.g.:\n{web[~web.is_categorized][0:10]}")

    logger.debug("Categorize editor events")
    edits["categories"] = edits.apply(
        lambda row: categories(
            row.editor_project + row.editor_file + row.editor_language, regexes
        ),
        axis=1,
    )
    edits["is_categorized"] = edits.apply(lambda row: len(row.categories) > 0, axis=1)
    logger.debug(f"total: {len(edits)}")
    logger.debug(f"categorized: {len(edits[edits.is_categorized])}")
    logger.debug(
        f"missing categorization, e.g.:\n{edits[~edits.is_categorized][0:10]}"
    )
    edits["project"] = edits.apply(
        lambda row: project(
            row.editor_project + row.editor_file + row.editor_language, regexes_proj
        ),
        axis=1,
    )
    edits["has_project"] = edits.apply(lambda row: row.project is not None, axis=1)
    logger.debug(f"assigned to a project: {len(edits[edits.has_project])}")
    logger.debug(f"missing a project, e.g.:\n{edits[~edits.has_project][0:10]}")

    # windows distribution (surfing more than programming? ;))
    regexes_apps = {
        p: re.compile(r, re.IGNORECASE) for p, r in config["apps"].items()
    }

    def app(s: str, regexes: Dict[str, re.Pattern]):
        for c, r in regexes.items():
            if len(r.findall(s)) > 0:
                return c
        return None

    logger.debug("Categorize window events")
    window["app"] = window.apply(
        lambda row: app(row.window_app, regexes_apps),
        axis=1,
    )
    window["has_app"] = window.apply(lambda row: row.app is not None, axis=1)
    logger.debug(f"total: {len(window)}")
    logger.debug(f"categorized: {len(window.has_app)}")
    logger.debug(f"missing categorization, e.g.:\n{window[~window.has_app][0:10]}")
    logger.debug(window.groupby("app").duration.sum())

    # categories surfed (time spent in category is not mutually exclusive!)
    logger.debug(web.explode("categories").groupby("categories").duration.sum())

    # project percentage to active time based on editor events
    logger.debug(edits.groupby("project").duration.sum())

    # git commits
    if len(git) > 0:
        if args.commits_sort_by == "timestamp":
            print(git[git.git_hook == "post-commit"])
        elif args.commits_sort_by == "issue":
            # list of issues to rows (explode, ok, because we don't sum up duration)
            git[git.git_hook == "post-commit"].explode("git_issues") \
                .astype(str) \
                .drop_duplicates(["git_origin", "git_summary"]) \
                .groupby("git_issues") \
                .apply(lambda g: print(f"  {issue_to_string(g)}"))
