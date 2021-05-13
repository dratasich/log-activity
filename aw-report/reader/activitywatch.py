import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from aw_client import ActivityWatchClient
from dateutil.tz import tzlocal
from utils import *


class ActivityWatchReader():

    def __init__(self, client: ActivityWatchClient):
        self._logger = logging.getLogger(__name__)
        self._client = client
        self.events = None

    def get(self, buckets: List[str], time_ranges: List[Tuple[datetime, datetime]], rename={}):
        for bucket in buckets:
            query = f"""
            events = query_bucket('{bucket}');
            RETURN = sort_by_timestamp(events);
            """
            events = self._client.query(query, time_ranges)[0]
            df = pd.DataFrame([flatten_json(e, rename) for e in events])
            # add metadata info
            df["source"] = bucket
            df["type"] = "activitywatch"
            if self.events is None:
                self.events = df
            else:
                self.events.append(df)
        # transform for some extra columns for convenience
        self._map()

    def _map(self):
        # change python timestamp to pandas timestamp
        self.events.loc[:, "timestamp"] = pd.to_datetime(self.events.timestamp)
        # add date column from exact timestamp (= starting point of activity)
        self.events.loc[:, "date"] = self.events.timestamp.dt.floor("d")
        # add time = duration as timedelta
        self.events.loc[:, "time"] = self.events.duration.apply(lambda d: timedelta(seconds=d))

    def categorize(
            self,
            regexes: Dict[str, re.Pattern],
            columns,
            single=False,
    ):
        if len(self.events) == 0:
            return
        self.events = self._categorize(self.events, regexes, columns, single)

    def _categorize(
            self,
            df,
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
            self._logger.warning(f"failed to assign a single category given {columns}")
            df.loc[:, "category"] = np.nan
            df.loc[:, "has_category"] = False
        else:
            df.loc[:, "category"] = df_category
            df.loc[:, "has_category"] = df.apply(
                lambda row: not pd.isna(row.category) if single else len(row.category) > 0,
                axis=1,
            )
        self._logger.debug(f"total: {len(df)}")
        self._logger.debug(f"has category: {len(df[df.has_category])}")
        if len(df[df.has_category]) < len(df):
            self._logger.debug(f"missing category, e.g.:\n{df[~df.has_category][0:10]}")

        return df

    def events_within(self, date):
        if self.events is None or len(self.events) == 0:
            return self.events
        try:
            return self.events[(self.events.timestamp >= pd.to_datetime(date[0]))
                               & (self.events.timestamp <= pd.to_datetime(date[1]))]
        except KeyError as e:
            logger.debug(f"no events within the range")


class ActivityWatchWebReader(ActivityWatchReader):

    def get(self, bucket: str, time_ranges: List[Tuple[datetime, datetime]], rename={}):
        query = f"""
        window_events = query_bucket(find_bucket("aw-watcher-window_"));
        web_events = query_bucket(find_bucket("aw-watcher-web"));
        web_events = filter_period_intersect(web_events, filter_keyvals(window_events, "app", ["Firefox", "Chrome"]));
        merged_events = merge_events_by_keys(web_events, ["app", "title"]);
        RETURN = sort_by_timestamp(web_events);
        """
        events = self._client.query(query, time_ranges)[0]
        df = pd.DataFrame([flatten_json(e, rename) for e in events])
        # add metadata info
        df["source"] = "aw-watcher-web"
        df["type"] = "activitywatch"
        self.events = df
        self._map()


class ActivityWatchGitReader(ActivityWatchReader):

    def categorize_issues(
            self,
            regex_for_issues: Dict[str, re.Pattern],
            regex_for_repos: Dict[str, re.Pattern],
    ):
        if len(self.events) == 0:
            return

        commits = self.events[self.events.git_hook == "post-commit"].explode("git_issues").reset_index(drop=True)

        # abort if no post-commits
        if len(commits) == 0:
            return

        # categorize git commits according to issues or repos
        giti = self._categorize(
            commits.copy(),
            regex_for_issues,
            columns=["git_issues"],
            single=True,
        )
        gitr = self._categorize(
            commits.copy(),
            regex_for_repos,
            columns=["git_origin"],
            single=True,
        )
        # update NaNs of category column (issue first, then repo)
        giti.update(gitr)  # !!has_category probably invalidated!!
        # re-write has_category  # make it valid again
        giti.loc[:, "has_category"] = giti.apply(
            lambda row: not pd.isna(row.category),
            axis=1,
        )
        # drop duplicates
        giti = giti.drop_duplicates(["git_origin", "git_issues", "git_summary"])
        # reset git events
        self.events = giti
