import sys
sys.path.insert(0, ".")
from ahp_tool import bipolar_to_saaty, score_6_to_9, run_ahp, compute_ud, ud_smoothed
import json

# Mes comparaisons bipolaires comme AvioSys (prudent, ingénieur)
bipolar = [2, 3, 2, -1, -1, 1]  # (0,1), (0,2), (0,3), (1,2), (1,3), (2,3)

comparisons = {
    (0, 1): bipolar_to_saaty(bipolar[0]),
    (0, 2): bipolar_to_saaty(bipolar[1]),
    (0, 3): bipolar_to_saaty(bipolar[2]),
    (1, 2): bipolar_to_saaty(bipolar[3]),
    (1, 3): bipolar_to_saaty(bipolar[4]),
    (2, 3): bipolar_to_saaty(bipolar[5]),
}

result = run_ahp(comparisons, n=4)

# Mes scores de gravité [1, 6]
scores_ui = [3, 2, 3, 4]
scores_9 = [score_6_to_9(s) for s in scores_ui]

ud_raw = compute_ud(result.weights, scores_9)
ud_smoothed_val = ud_smoothed(None, ud_raw, rho=0.3)

print(f"CR: {result.consistency_ratio:.4f}")
print(f"Is consistent: {result.is_consistent}")
print(f"Weights: {list(result.weights)}")
print(f"Lambda max: {result.lambda_max:.4f}")
print(f"CI: {result.consistency_index:.4f}")
print(f"Scores 9-point: {scores_9}")
print(f"UD raw: {ud_raw:.4f}")
print(f"UD smoothed: {ud_smoothed_val:.4f}")
print(f"Attempts: 1")
