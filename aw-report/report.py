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


def regexes(config_section: configparser.SectionProxy):
    return {
        category: re.compile(regex, re.IGNORECASE)
        for category, regex in config_section.items()
    }


# read and compile regexes from config
r_editor = regexes(config["projects"])
r_web = regexes(config["categories"])
r_window = regexes(config["apps"])


# %% Get events
client = ActivityWatchClient("report-client")


def aw_events(bucket: str, time_ranges: List[Tuple[datetime, datetime]], rename={}):
    query = f"""
    events = query_bucket('{bucket}');
    RETURN = sort_by_timestamp(events);
    """
    events = client.query(query, time_ranges)[0]
    df = pd.DataFrame([flatten_json(e, rename) for e in events])
    if not df.empty:
        df.timestamp = pd.to_datetime(df.timestamp)
    return df


def aw_categorize(
    df: pd.DataFrame, regexes: Dict[str, re.Pattern], columns, single=False
):
    """Categorizes each event of df given a regex per category."""
    if len(df) == 0:
        return

    def tags(s: str, regexes: Dict[str, re.Pattern]):
        return [c for c, r in regexes.items() if len(r.findall(s)) > 0]

    def first_match(s: str, regexes: Dict[str, re.Pattern]):
        for c, r in regexes.items():
            if len(r.findall(s)) > 0:
                return c
        return np.nan

    df["category"] = df.apply(
        lambda row: first_match(" ".join(row[columns]), regexes)
        if single
        else tags(" ".join(row[columns]), regexes),
        axis=1,
    )
    df["has_category"] = df.apply(
        lambda row: not (row.category is None or row.category is np.nan)
        if single
        else len(row.category) > 0,
        axis=1,
    )
    logger.debug(f"total: {len(df)}")
    logger.debug(f"has category: {len(df[df.has_category])}")
    logger.debug(f"missing category, e.g.:\n{df[~df.has_category][0:10]}")

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
    afk["afk"] = afk["afk_status"].apply(lambda s: s == "afk")
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

    # categorize events based on regex
    if len(web) > 0:
        logger.debug("Categorize website visits")
        web = aw_categorize(web, r_web, ["web_url", "web_title"])
        # categories surfed (time spent in category is not mutually exclusive!)
        logger.debug(web.explode("category").groupby("category").duration.sum())

    if len(edits) > 0:
        logger.debug("Categorize editor events")
        edits = aw_categorize(
            edits,
            r_editor,
            ["editor_project", "editor_file", "editor_language"],
            single=True,
        )
        # project percentage to active time based on editor events
        logger.debug(edits.groupby("category").duration.sum())

    if len(window) > 0:
        logger.debug("Categorize window events")
        window = aw_categorize(window, r_window, ["window_app"], single=True)
        # windows distribution (surfing more than programming? ;))
        logger.debug(window.groupby("category").duration.sum())

    # git commits
    if len(git) > 0:
        if args.commits_sort_by == "timestamp":
            print(git[git.git_hook == "post-commit"])
        elif args.commits_sort_by == "issue":
            # list of issues to rows (explode, ok, because we don't sum up duration)
            git[git.git_hook == "post-commit"] \
                .explode("git_issues") \
                .astype(str) \
                .drop_duplicates(["git_origin", "git_summary"]) \
                .groupby("git_issues") \
                .apply(lambda g: print(f"  {issue_to_string(g)}"))
