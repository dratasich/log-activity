import logging
import os.path
from datetime import datetime, timedelta
from typing import Dict, Tuple

import pandas as pd


class Activities():

    def __init__(self,
                 meetings=pd.DataFrame(columns=["date", "project",
                                                "duration", "subject"]),
                 git=pd.DataFrame(columns=["date",
                                           "project", "git_issues",
                                           "git_origin",
                                           "git_summary", "time"]),
                 ):
        # input activities
        self._meetings = meetings
        self._git = git
        # aggregate and map to activities
        self._aggregate()

    def fill(self, working_hours: Dict[datetime, float]):
        raise RuntimeError("not yet implemented")

    def _aggregate(self):
        """Aggregate inputs to activities per day with one-line description."""
        # final activity structure
        self._columns = ["date", "project", "desc", "duration"]
        a = pd.DataFrame(columns=self._columns, index=[])
        # aggregate inputs per day and project (adds a desc column)
        # meetings
        if self._meetings.index.size > 0:
            m = self._meetings.groupby(["date", "project"]).agg(
                {
                    "duration": 'sum',
                    "subject": ", ".join,
                }
            )
            m = m.reset_index()
            m.loc[:, "desc"] = "meetings: " + m.loc[:, "subject"]
            # add to result table
            a = pd.concat([a if not a.empty else None, m.loc[:, self._columns]])

        # git issues
        if self._git.index.size > 0:
            g = self._git
            g["git_repo"] = g["git_origin"].apply(lambda o: os.path.basename(o).split('.')[0])
            # to keep the commits without issue, fill NaNs
            g = g.fillna({"git_issues": "other"})
            # increase time for coding
            g.loc[:, 'time'] = g['time'].apply(lambda d: max(d, timedelta(minutes=15)))
            # sum up
            g = g.groupby(["date", "category", "git_issues", "git_repo"]).agg(
                {
                    "time": 'sum',
                    "git_summary": ", ".join,
                }
            )
            g = g.reset_index()
            g.loc[:, "git_summary"] = g.loc[:, "git_repo"] + ": " + g.loc[:, "git_summary"]
            g = g.reset_index().groupby(["date", "category", "git_issues"]).agg(
                {
                    "time": 'sum',
                    "git_summary": "; ".join
                }
            )
            g = g.reset_index()
            g.loc[:, "desc"] = g.loc[:, "git_issues"] + " (" + g.loc[:, "git_summary"] + ")"
            g = g.rename(columns={"category": "project", "time": "duration"})
            # add to result table
            a = pd.concat([a if not a.empty else None, g.loc[:, self._columns]])
        # aggregate all inputs per day and project
        a = a.groupby(["date", "project"]).agg(
            {
                "duration": 'sum',
                "desc": "; ".join
            }
        )
        self.activities = a.reset_index()

    def save(self, filename="activities.csv"):
        if len(self.activities) == 0:
            return

        a = self.activities.sort_values(["date", "project", "duration"])

        # round time to 15min
        a["duration"] = a["duration"].apply(lambda t: t.round("15min"))

        # format time columns
        a["hours"] = a["duration"].apply(lambda t: t.total_seconds()/3600)
        a["duration"] = a["duration"].apply(lambda t: Activities.__str_delta(t.to_pytimedelta()))

        a.to_csv(filename, index=False, columns=["date", "project", "duration", "hours", "desc"])

    def __str_delta(time: timedelta):
        h = int(time.total_seconds() / 3600)
        m = int((time.total_seconds() % 3600) / 60)
        return f"{h:02}:{m:02}"
