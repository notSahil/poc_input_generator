---
name: data-engineer
description: Best practices for data processing, pandas memory optimization, and data pipeline robustness.
---

# Data Engineering Guidelines

When this skill is activated for data manipulation (especially with Pandas/Numpy):

## 1. Pandas Efficiency
- **NEVER use `.iterrows()`**. Always prefer vectorized operations.
- If vectorization is impossible, use `.apply()` or `.itertuples()`.
- Use `np.where()` or `np.select()` for conditional column creation.

## 2. Memory Optimization
- Explicitly downcast numeric types (e.g., `float64` to `float32` or `int32`) when large datasets are involved.
- Convert low-cardinality string columns to `category` dtype to save memory.

## 3. Defensive Data Processing
- Always validate incoming data. Check for expected columns before processing.
- Explicitly handle missing values (`NaN`, `None`). State whether you are dropping them (`dropna`) or filling them (`fillna`).

## 4. Method Chaining
- Where possible and readable, use Pandas method chaining (e.g., `.assign()`, `.pipe()`, `.query()`) to prevent intermediate variable bloat.
