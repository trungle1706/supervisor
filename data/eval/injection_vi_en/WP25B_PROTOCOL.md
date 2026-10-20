# WP25b protocol (written before the final run)

Model 1.1.0. Binding rules:

1. heldout.jsonl, evasion.jsonl and adversarial.jsonl are sealed (SEALED.json, hashes in the model card and in a test).
2. Tuning uses only the template pools train (A), dev (B) and the new pool train_b (C). Folds are grouped by
   pool, a pool being a set of template families that no other pool shares: leave-one-pool-out, 3 folds
   (A+B -> C, A+C -> B, B+C -> A). Mean and spread over the folds are reported.
3. Targets are unchanged: recall 8500 bp, false alarm on benign hard negatives 500 bp, precision 9000 bp.
   The latency target moves from p95 2 ms to **p95 5 ms per call** (reviewer recommendation). It is written here
   before the run.
4. Threshold rule (per surface, from the out-of-fold scores of the 3 folds): strict = smallest threshold with
   false alarm <= 800 bp, balanced <= 500 bp, lenient <= 300 bp; pause (global) <= 50 bp. Rounded up to 50 bp.
5. The final weights are trained on all three pools (the committed train.jsonl, dev.jsonl, train_b.jsonl);
   the card data hashes match those files.
6. The held-out and evasion sets are run once, at the end. The result is published whatever it is.
