#!/usr/bin/env python3

import socket
from datetime import datetime

from aw_client import ActivityWatchClient
from sklearn.model_selection import train_test_split

from models import *

# time interval settings (which projects to consider and classify)
DATE_FROM = datetime.today().replace(day=1, hour=4, minute=0, second=0, microsecond=0)
DATE_TO = datetime.now()

# aw settings
BUCKET_WEB = "aw-watcher-web-firefox"
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
issues = hooks["issue"].drop_duplicates().dropna()
projects = issues.loc[issues.str.contains(r"[A-Z]+-[0-9]+")].apply(
    lambda r: r.split("-")[0]
)


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
X_train, X_test = train_test_split(visits, train_size=2, random_state=1)


# ask user about a fitting category
def train(x):
    print(f"---\nCategories from your git issues: {projects.to_list()}")
    print(x[["title", "url"]])
    return input("Category: ")


# train
y_train = X_train.apply(lambda r: train(r), axis=1)

X = X_train.copy()
X["label"] = y_train
print(X)
