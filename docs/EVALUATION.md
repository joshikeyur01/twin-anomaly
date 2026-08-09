# Evaluation

Rule baseline vs Isolation Forest on the twin-anomaly corpus. Higher recall is better; lower normal-FPR is better. Both detectors fit on the same 157 normal-train windows and score the same evaluation set (68 held-out normal + 330 fault windows), features v0.1.0.

| metric | rule | isoforest |
| --- | --- | --- |
| recall · dropout | 0.88 | 0.93 |
| recall · encoder | 0.47 | 0.20 |
| recall · friction | 0.00 | 0.61 |
| recall · stuck | 0.00 | 0.41 |
| **precision** | 0.99 | 0.99 |
| **normal FPR** | 0.01 | 0.01 |

- **Recall** is per fault kind: the fraction of that fault's windows flagged anomalous.
- **Precision**: of all flagged windows, the fraction truly faulty.
- **Normal FPR**: of held-out normal windows, the fraction flagged.

Thresholds come from each artefact's manifest (99th-percentile normal budget), never service config. Regenerate with notebooks 02 then 04.
