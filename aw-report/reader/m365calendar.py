import logging
from typing import Dict, List, Optional, Tuple

import pandas as pd


class M365CalendarReader():

    def __init__(self, filename: str):
        self._logger = logging.getLogger(__name__)
        self.events = self.__read(filename)

    def __read(self, filename: str):
        # load calendar
        try:
            calendar = pd.read_json(filename, orient="records")
        except:
            self._logger.warning("failed to read meetings")
            return None
        # convert datetimes (from GraphAPI)
        calendar["startWithTimeZone"] = pd.to_datetime(calendar.start.apply(lambda r: r['dateTime']+'Z'))
        calendar["endWithTimeZone"] = pd.to_datetime(calendar.end.apply(lambda r: r['dateTime']+'Z'))
        # filter columns
        calendar = calendar[
            ["subject", "startWithTimeZone", "endWithTimeZone", "categories", "isAllDay", "showAs"]
        ]
        # explode and filter categories (if len(categories) > 1, take only one)
        calendar = (
            calendar.explode("categories")
            .dropna()
            .drop_duplicates(["subject", "startWithTimeZone", "endWithTimeZone"])
        )
        # drop private events
        calendar = calendar[calendar["categories"] != "privat"]
        # calculate event duration
        calendar = calendar.astype(
            {"startWithTimeZone": "datetime64[ns, Europe/Vienna]", "endWithTimeZone": "datetime64[ns, Europe/Vienna]"}
        )
        calendar["duration"] = calendar["endWithTimeZone"] - calendar["startWithTimeZone"]
        # add date column for grouping per day
        calendar["date"] = calendar["startWithTimeZone"].dt.date
        # add source information
        calendar["source"] = filename
        calendar["type"] = "calendar"
        return calendar

    def events_within(self, date):
        # meetings
        if self.events is None:
            return
        else:
            return self.events[(self.events.startWithTimeZone >= date[0])
                               & (self.events.startWithTimeZone <= date[1])]
