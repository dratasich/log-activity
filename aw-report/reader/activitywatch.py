"""
Query ActivityWatch events.

- [aw-query docs](https://docs.activitywatch.net/en/latest/api/python.html#aw-query)
- Try queries locally: [aw local](http://localhost:5600/#/query)
"""

import logging
import re
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from aw_client import ActivityWatchClient

from utils import flatten_json


class ActivityWatchReader:
    def __init__(self, client: ActivityWatchClient):
        self._logger = logging.getLogger(__name__)
        self._client = client
        self.events = None

    def get(
        self,
        query,
        time_ranges: list[tuple[datetime, datetime]],
        rename: dict | None = None,
        metadata: dict | None = None,
    ):
        if rename is None:
            rename = {}
        if metadata is None:
            metadata = {}
        events = self._client.query(query, time_ranges)[0]
        df = pd.DataFrame([flatten_json(e, rename) for e in events])
        # add metadata info to each row
        for k, v in metadata.items():
            df[k] = v
        df["type"] = "activitywatch"
        # save
        self.events = df
        # transform for some extra columns for convenience
        self._map()

    def _map(self):
        if len(self.events) == 0:
            return  # nothing to map
        # change python timestamp to pandas timestamp
        self.events["timestamp"] = pd.to_datetime(
            self.events.timestamp, format="ISO8601"
        )
        # add date column from exact timestamp (= starting point of activity)
        self.events["date"] = self.events.timestamp.dt.date
        # add time = duration as timedelta
        self.events["time"] = self.events.duration.apply(lambda d: timedelta(seconds=d))

    def categorize(
        self,
        regexes: dict[str, re.Pattern],
        columns,
        single=False,
    ):
        if len(self.events) == 0:
            return
        self.events = self._categorize(self.events, regexes, columns, single)

    def _categorize(
        self,
        df,
        regexes: dict[str, re.Pattern],
        columns,
        single=False,
    ):
        """Categorizes each event of df given a regex per category."""
        if len(df) == 0:
            return df

        def tags(s: str, regexes: dict[str, re.Pattern]):
            return [c for c, r in regexes.items() if len(r.findall(s)) > 0]

        def first_match(s: str, regexes: dict[str, re.Pattern]):
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
                lambda row: not pd.isna(row.category)
                if single
                else len(row.category) > 0,
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
            return self.events[
                (self.events.timestamp >= pd.to_datetime(date[0]))
                & (self.events.timestamp <= pd.to_datetime(date[1]))
            ]
        except KeyError:
            self._logger.debug("no events within the range")


class ActivityWatchAFKReader(ActivityWatchReader):
    def get(self, time_ranges: list[tuple[datetime, datetime]]):
        query = """
        events = query_bucket(find_bucket("aw-watcher-afk_"));
        RETURN = sort_by_timestamp(events);
        """
        super().get(
            query,
            time_ranges,
            rename={"data": "afk"},
            metadata={"source": "aw-watcher-afk"},
        )
        self.events["afk"] = self.events["afk_status"].apply(lambda s: s == "afk")


class ActivityWatchEmacsReader(ActivityWatchReader):
    def get(self, time_ranges: list[tuple[datetime, datetime]]):
        query = """
        afk_events = query_bucket(find_bucket("aw-watcher-afk_"));
        events = query_bucket(find_bucket("aw-watcher-emacs_"));
        events = filter_period_intersect(events, filter_keyvals(afk_events, "status", ["not-afk"]));
        RETURN = sort_by_timestamp(events);
        """
        super().get(
            query,
            time_ranges,
            rename={"data": "editor"},
            metadata={"source": "aw-watcher-emacs"},
        )


class ActivityWatchIDEReader(ActivityWatchReader):
    def get(self, time_ranges: list[tuple[datetime, datetime]]):
        query = """
        afk_events = query_bucket(find_bucket("aw-watcher-afk_"));
        events = query_bucket(find_bucket("aw-watcher-window_"));
        events = filter_period_intersect(events, filter_keyvals(afk_events, "status", ["not-afk"]));
        events = filter_keyvals(events, "app", ["Code", "jetbrains-idea-ce"]));
        events = merge_events_by_keys(events, ["app", "title"]);
        RETURN = sort_by_timestamp(events);
        """
        super().get(
            query,
            time_ranges,
            rename={"data": "editor"},
            metadata={"source": "aw-watcher-window"},
        )


class ActivityWatchWebReader(ActivityWatchReader):
    def get(self, time_ranges: list[tuple[datetime, datetime]]):
        query = """
        window_events = query_bucket(find_bucket("aw-watcher-window_"));
        web_events = query_bucket(find_bucket("aw-watcher-web"));
        web_events = filter_period_intersect(web_events, filter_keyvals(window_events, "app", ["Firefox", "Chrome"]));
        merged_events = merge_events_by_keys(web_events, ["url", "title"]);
        RETURN = sort_by_duration(merged_events);
        """
        super().get(
            query,
            time_ranges,
            rename={"data": "web"},
            metadata={"source": "aw-watcher-web"},
        )


class ActivityWatchGitReader(ActivityWatchReader):
    def get(self, time_ranges: list[tuple[datetime, datetime]]):
        query = """
        events = query_bucket(find_bucket("aw-git-hooks_"));
        RETURN = sort_by_timestamp(events);
        """
        super().get(
            query,
            time_ranges,
            rename={"data": "git"},
            metadata={"source": "aw-git-hooks"},
        )

    def categorize_issues(
        self,
        regex_for_issues: dict[str, re.Pattern],
        regex_for_repos: dict[str, re.Pattern],
    ):
        if len(self.events) == 0:
            return

        commits = (
            self.events[self.events.git_hook == "post-commit"]
            .explode("git_issues")
            .reset_index(drop=True)
        )

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
