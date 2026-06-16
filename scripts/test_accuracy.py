import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

print("=== CHECKING PREDICTIVE POWER ===")
df = pd.read_parquet("/home/ubuntu/faith-workspace/vfl-empire/data/unified_ml_matrix.parquet")

features = [
    'day', 'prev_tension', 'archetype_goals',
    'h_rank', 'h_tier', 'h_quota', 'h_gd',
    'a_rank', 'a_tier', 'a_quota', 'a_gd',
    'poisson_hxG', 'poisson_axG',
    'odds_cluster', 'o15', 'o25', 'gg', 'u35'
]

X = df[features].fillna(0)
y = df['target_1x2']

clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
scores = cross_val_score(clf, X, y, cv=5)
print(f"Random Forest Accuracy: {scores.mean():.4f} (+/- {scores.std() * 2:.4f})")

clf.fit(X, y)
importances = clf.feature_importances_
print("\nFeature Importances:")
for f, imp in sorted(zip(features, importances), key=lambda x: x[1], reverse=True):
    print(f"  {f}: {imp:.4f}")
