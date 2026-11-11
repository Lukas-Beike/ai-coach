## 1. Schema and upgrade

- [x] 1.1 Define the canonical product table (origin, fetch time, details; own EAN unique) as schema v27 and drop the mirror table from fresh databases
- [x] 1.2 Add the v26 upgrade step: rebuild the product table, move every mirror row, merge foods with an own product's EAN into it, drop the mirror table, log the counts
- [x] 1.3 Accept the frozen v26 shape for version 26 and register its step

## 2. Runtime

- [x] 2.1 Read and write stored database foods as canonical products and keep their stored fields unchanged on read
- [x] 2.2 Restrict own-product reads and writes to origin `own`
- [x] 2.3 Fill only empty fields of an own product from a food with its EAN, on lookup and on save

## 3. Export, purge and docs

- [x] 3.1 Drop the mirror table from export and purge; export format version 18
- [x] 3.2 Update README, nutrition, operations and schema-history docs

## 4. Evidence

- [x] 4.1 Populated baseline upgrade, rollback on failure with retry, and same-build restart (SQLite gate and SQLCipher matrix)
- [x] 4.2 Repository tests for read-back, own-product precedence and absorption
