import pandas as pd

df1 = pd.read_csv('../data/train1.csv')
df2 = pd.read_csv('../data/train2.csv')

merged_df = pd.merge(df1, df2, on='timestep', how='outer')

# Optional: Save to a new CSV file
merged_df.to_csv("merged_data.csv", index=False)