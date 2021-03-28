import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple

from dateutil.tz import tzlocal


class WorkingHours():

    def __init__(
            self,
            actual_start: datetime,
            actual_end: datetime,
            active: timedelta,
    ):
        self._logger = logging.getLogger(__name__)
        self.hours, self.lunch_incl = WorkingHours.align_hours(active)
        self.start, self.end = WorkingHours.align_range(actual_start, actual_end, self.hours)

    def align_hours(active: timedelta):
        # consider lunch break (a must when time >= 6h)
        lunch_incl = False
        working_hours = active
        working_hours_incl_lunch = working_hours
        if active >= timedelta(hours=6):
            lunch_incl = True
            working_hours_incl_lunch += timedelta(minutes=30)
        # round to 15min
        working_hours_incl_lunch = WorkingHours._round_timedelta(working_hours_incl_lunch)
        return working_hours_incl_lunch, lunch_incl

    def align_range(actual_start: datetime, actual_end: datetime, active: timedelta, round=True):
        """Converts start and end of today to something that is allowed and reflects active time."""
        # round
        if round:
            actual_start = WorkingHours._round_datetime(actual_start)
            actual_end = WorkingHours._round_datetime(actual_end)

        weekday = actual_start.isoweekday()
        # ignore Kernzeit on weekends
        if weekday == 6 or weekday == 7:
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

        if actual_start <= start_max and actual_start + active >= end_min:
            # actual timings within Kernzeit
            return actual_start, actual_start + active
        elif active < end_min - start_max:
            # worked not enough today
            return start_max, start_max + active
        elif actual_start > start_max:
            # worked enough but started late, so shift start to the left ;)
            return start_max, start_max + active
        else:
            return end_min - active, end_min

    def _round_timedelta(tm: timedelta, round_to_s=timedelta(minutes=15).total_seconds()):
        tm_rounded = timedelta(
            seconds=int((tm.total_seconds() + round_to_s / 2) / (round_to_s)) * (round_to_s)
        )
        return tm_rounded

    def _round_datetime(tm: datetime, round_to_min=15):
        tm_rounded = tm + timedelta(minutes=float(round_to_min)/2)
        tm_rounded -= timedelta(
            minutes=tm_rounded.minute % round_to_min,
            seconds=tm_rounded.second,
            microseconds=tm_rounded.microsecond,
        )
        return tm_rounded

    def str_time(date: datetime):
        if date is None:
            return "00:00"
        return date.astimezone(tz=tzlocal()).strftime("%H:%M")

    def str_delta(time: timedelta):
        h = int(time.total_seconds() / 3600)
        m = int((time.total_seconds() % 3600) / 60)
        return f"{h:02}:{m:02}"
