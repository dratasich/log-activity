Report
======

Reads events from buckets per day and prints:

- [x] start and end of first and last afk-event (login and shutdown)
- [x] active time (sum of not-afk durations)
  - [x] add afk < 5min (e.g., 5-10min per hour is ok)
  - [x] add 30min for lunch
  - [x] round to 0:15
        (add an option to distinguish between report and aw summary)
- [ ] distribute active time to aw projects
- [x] git issues and commits (aw-git-hooks events)
  - [x] duplicates of (git-repo, summary) are removed
    (may happen on `git commit ammend or reword`)
- [x] time spent in meetings
  - [x] read exported calendar (json fetched via GraphAPI)
  - [ ] window events containing "MS Teams"
  - [ ] meetings watcher reading MS outlook calendars (ical or via selenium)
- [ ] pomodoro (project, summary)

Usage
-----

Save working time and activities (including meetings) since 2021-05-12 by:
```bash
$ ./report.py -f 2021-05-12 -m m365_calendar.json
```

See `./report.py -h` for usage.

## Export calendar

GraphAPI query:
```
# get bearer token from https://developer.microsoft.com/en-us/graph/graph-explorer
# specify top=200 to get all elements at once (assuming you have less than 200 meetings in a month ;)
curl -X GET -H 'Authorization: Bearer <token>' --url 'https://graph.microsoft.com/v1.0/me/calendarview?startdatetime=2022-08-01T00:00:00.000Z&enddatetime=2022-09-01T00:00:00.000Z&$orderby=start/dateTime&$select=start,end,categories,subject,isAllDay,showAs&$top=200' | jq '.value' > 2022-08_m365calendar.json
```
