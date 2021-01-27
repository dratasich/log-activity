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

logging.basicConfig(format="[%(levelname)-5s] %(message)s")
logger = logging.getLogger(__name__)
if args.verbose:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)


# Advanced configuration
config = configparser.ConfigParser()
config.read("config.ini")


# Output
def project_reset():
    return pd.DataFrame(columns=["project", "time", "git"]).set_index("project")


def project_add(project: str, time: timedelta = timedelta(seconds=0), git: str = ""):
    if project in projects.index:
        projects.loc[project].time += time
        projects.loc[project].git += str(git)
    else:
        projects.loc[project] = {"time": time, "git": str(git)}


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


def come_and_go(actual_start: datetime, actual_end: datetime, active: timedelta):
    """Converts start and end of today to something that is allowed and reflects active time."""
    weekday = actual_start.isoweekday()
    # ignore Kernzeit on weekends
    if weekday == 6 or weekday == 7:
        logger.debug(f"ignore Kernzeit as it is {actual_start.strftime('%A')}")
        return actual_start, actual_start + active
    # Kernzeit
    # Mon-Thu min is 09:00 - 15:00
    isotoday = actual_start.date().isoformat()
    start_max, end_min = (
        datetime.fromisoformat(f"{isotoday}T09:00:00").astimezone(tz=tzlocal()),
        datetime.fromisoformat(f"{isotoday}T15:00:00").astimezone(tz=tzlocal()),
    )
    if weekday == 5:  # Fri min is 09:00 - 12:00
        end_min = datetime.fromisoformat(f"{isotoday}T12:00:00").astimezone(
            tz=tzlocal()
        )
    # actual timings within Kernzeit?
    if actual_start <= start_max and actual_start + active >= end_min:
        return actual_start, actual_start + active
    # worked enough today?
    elif active < end_min - start_max:
        logger.warning(
            f"Kernzeit-Violation ({str_time(actual_start)} - {str_time(actual_end)}, active={str_delta(active)})"
        )
        return start_max, start_max + active
    # worked enough but started late, so shift start to the left ;)
    elif actual_start > start_max:
        return start_max, start_max + active
    else:
        logger.error(
            f"missed a case ({str_time(actual_start)} - {str_time(actual_end)}, active={str_delta(active)})"
        )
        return end_min - active, end_min


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


def regexes(config_section: configparser.SectionProxy):
    return {
        category: re.compile(regex, re.IGNORECASE)
        for category, regex in config_section.items()
    }


# read and compile regexes from config
r_editor = regexes(config["project.editors"])
r_git_repos = regexes(config["project.repos"])
r_git_issues = regexes(config["project.issues"])


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
    df: pd.DataFrame,
    regexes: Dict[str, re.Pattern],
    columns,
    single=False,
):
    """Categorizes each event of df given a regex per category."""
    if len(df) == 0:
        return df

    def tags(s: str, regexes: Dict[str, re.Pattern]):
        return [c for c, r in regexes.items() if len(r.findall(s)) > 0]

    def first_match(s: str, regexes: Dict[str, re.Pattern]):
        for c, r in regexes.items():
            if len(r.findall(s)) > 0:
                return c
        return np.nan

    df_category = df.dropna(subset=columns).apply(
        lambda row: first_match(" ".join(row[columns]), regexes)
        if single
        else tags(" ".join(row[columns]), regexes),
        axis=1,
    )
    if len(df_category) == 0:
        logger.warning(f"failed to assign a single category given {columns}")
        df["category"] = np.nan
    else:
        df["category"] = df_category
    df["has_category"] = df.apply(
        lambda row: not pd.isna(row.category) if single else len(row.category) > 0,
        axis=1,
    )
    logger.debug(f"total: {len(df)}")
    logger.debug(f"has category: {len(df[df.has_category])}")
    if len(df[df.has_category]) < len(df):
        logger.debug(f"missing category, e.g.:\n{df[~df.has_category][0:10]}")

    return df


date = args.date
while date < DATE_TO:
    logger.debug(f">>> {date}")
    current_day = (date, date + timedelta(days=1))
    projects = project_reset()

    logger.debug(f"get aw events of {current_day}")
    # active time in front of the PC (afk..away-from-keyboard)
    afk = aw_events(BUCKET_AFK, [current_day], rename={"data": "afk"})
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
    come, go = come_and_go(start, end, working_hours_rounded)

    print(
        f"{str_date(start)} {start.strftime('%a'):^6}"
        + f" | {str_delta(working_hours_rounded)}"
        + f" | {str_time(come)} - {str_time(go)}"
    )

    # project percentage to active time based on editor events
    if len(edits) > 0:
        logger.debug("Categorize editor events")
        edits = aw_categorize(
            edits,
            r_editor,
            ["editor_project", "editor_file", "editor_language"],
            single=True,
        )
        logger.debug(edits.groupby("category").duration.sum())
        edits.groupby("category").apply(
            lambda g: project_add(
                g.iloc[0].category, timedelta(seconds=g.duration.sum())
            )
        )
        logger.debug(f"project considering editors:\n{projects}")

    # git commits
    if len(git) > 0:
        if args.commits_sort_by == "timestamp":
            print(git[git.git_hook == "post-commit"])
        elif args.commits_sort_by == "issue":
            # prepare list of issues
            commits = git[git.git_hook == "post-commit"].explode("git_issues")
            # categorize git commits according to issues or repos
            giti = aw_categorize(
                commits.copy(),
                r_git_issues,
                columns=["git_issues"],
                single=True,
            )
            gitr = aw_categorize(
                commits.copy(),
                r_git_repos,
                columns=["git_origin"],
                single=True,
            )
            # update NaNs of category column (issue first, then repo)
            giti.update(gitr)  # !!has_category probably invalidated!!
            # add description from git to project
            (
                giti.astype(str)
                # .drop_duplicates(["git_origin", "git_commit"])
                .drop_duplicates(["git_origin", "git_summary"])
                .groupby(["category"])
                .apply(
                    lambda g: project_add(g.iloc[0].category, git=issue_to_string(g))
                )
            )

    # print time and description per projects
    projects.time = projects.time.apply(lambda t: round_timedelta(t))
    project_add(
        "other",
        working_hours_rounded
        - (projects.time.sum() if len(projects) > 0 else timedelta(seconds=0)),
    )
    for p in projects.index:
        info = projects.loc[p]
        print(f"  {p:<15} | {str_delta(info.time)} | {info.git}")
