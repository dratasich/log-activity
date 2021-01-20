#!/usr/bin/env python3

import argparse
import logging
import socket
from datetime import datetime
from typing import List, Optional

import pandas as pd
from aw_client import ActivityWatchClient
from aw_core.models import Event

from models import *

# time interval settings (which projects to consider and classify)
DATE_FROM = datetime.today().replace(day=1, hour=4, minute=0, second=0, microsecond=0)
DATE_TO = datetime.now()

# aw settings
BUCKET_WEB = f"aw-watcher-web-firefox"
BUCKET_GIT = f"aw-git-hooks_{socket.gethostname()}"

client = ActivityWatchClient("report-client")


# extract different projects from issues or git origins if no issues available
# get all git hook events
query = f"""
events = query_bucket('{BUCKET_GIT}');
RETURN = sort_by_timestamp(events);
"""
git = client.query(query, [(DATE_FROM, DATE_TO)])
hooks = hooks_to_dataframe([GitHook(**e["data"]) for e in git[0]])
issues = hooks["issue"] \
    .drop_duplicates() \
    .dropna()
projects = issues.loc[issues.str.contains(r"[A-Z]+-[0-9]+")] \
    .apply(lambda r: r.split('-')[0])


# get all window titles, project titles, etc.
query = f"""
events = query_bucket('{BUCKET_WEB}');
RETURN = sort_by_timestamp(events);
"""
web = client.query(query, [(DATE_FROM, DATE_TO)])
visits = visits_to_dataframe([WebVisit(**e["data"]) for e in web[0]])
# save title as list of words additionally
visits["words"] = visits["title"].str.split(r"[ ,/]")


# select x random samples for user to train
