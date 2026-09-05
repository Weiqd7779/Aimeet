import os

os.environ["MOCK_MODE"] = "true"
# Legacy alert tests (knowledge-base conflicts, slide mismatch) exercise the full alert
# set; the product default keeps only inconsistencies, covered in test_consistency.py.
os.environ["ALERTS_INCONSISTENCY_ONLY"] = "false"
