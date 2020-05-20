Analyze Story Points per Sprint
===============================

Create Filter for my Stories
----------------------------

Go to jira / issues / all issues and filters / create:
- name: "my finished stories"
- search: `project = CA1492IOT AND status in (Closed, Done) AND resolution in
  (Fertig, Behoben, Done) AND assignee in (z175802) ORDER BY cf[10705] ASC,
  priority DESC, updated DESC`

Export CSV
----------

Go to jira / Issues / all issues and filters and select the filter "my finished
stories".
Export to CSV with ',' as separator.
