#!/usr/bin/env python3

# %% Imports
from aw_client import ActivityWatchClient
from datetime import datetime


# %% Settings
BUCKET_AFK="aw-watcher-afk_nils"

# %% Init
client = ActivityWatchClient("report-client")

# %% Helpers
def toDate(date: str):
    return datetime.fromisoformat(date)

# %% Get all events from afk bucket
query = f"RETURN = query_bucket('{BUCKET_AFK}');"
res = client.query(query, [(toDate("2020-12-26"), toDate("2020-12-27"))])

# %%
client.disconnect()
