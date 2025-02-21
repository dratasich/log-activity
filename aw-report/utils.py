"""Helpers for pandas dataframes."""


# flatten json, e.g., `data` in aw events
# https://towardsdatascience.com/flattening-json-objects-in-python-f5343c794b10
def flatten_json(y, map: dict | None = None):
    if map is None:
        map = {}
    out = {}

    def rename(name):
        if name in map:
            return map[name]
        return name

    def flatten(x, name=""):
        if type(x) is dict:
            for a in x:
                flatten(x[a], rename(name) + rename(a) + "_")
        else:
            out[name[:-1]] = x

    flatten(y)
    return out
