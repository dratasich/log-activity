# To add a new cell, type '# %%'
# To add a new markdown cell, type '# %% [markdown]'

# %%
import pandas as pd


# %%
data = pd.read_csv("my-finished-stories.csv", sep=',')
data.head()

# %%
# Find column containing story points and rename
columnStoryPoints = [key for key in data.keys() if "Story Points" in key][0]
data["Story Points"] = data[columnStoryPoints]

# %%
# Number of sprints
data["Sprint"].nunique()


# %%
# Distribution of Story Points
data.hist("Story Points")


# %%
data["Story Points"].value_counts()


# %%
# filter columns of interest without NaN values
points_per_sprint = data[["Story Points", "Sprint"]].dropna()
# remove "Sprint "
points_per_sprint["Sprint"] = points_per_sprint["Sprint"].apply(lambda s: int(str(s).replace("Sprint", "").strip()))
# fibonacci to linear story points
unique_points = sorted(data["Story Points"].unique())
points_per_sprint["Points (linear)"] = points_per_sprint["Story Points"].apply(lambda p: unique_points.index(p)+1)
# no points at all
points_per_sprint["Count"] = 1
points_per_sprint.head()


# %%
# Sum of points per sprint
points_per_sprint.groupby("Sprint").sum().plot()


# %%
# Number of stories per sprint
points_per_sprint.groupby("Sprint")["Count"].sum().plot()


# %%
# Stories had more points at the beginning
col = "Story Points"
for col in ["Story Points", "Points (linear)"]:
    points_per_sprint.groupby("Sprint").agg(
        min=(col, min),
        max=(col, max),
        mean=(col, lambda x: x.mean())
    ).plot()


# %%


