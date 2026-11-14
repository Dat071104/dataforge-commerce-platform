# Week 1–6 learning closures

## Polars and Pandas parity

The fixed fixture proves the selected read, filter, join, group, and Parquet outputs are identical. The seven-repeat timing helper reports median and population standard deviation for this tiny fixture only; it does not establish a speedup or justify replacing the repository's Pandas baseline. Choose a library from measured behavior on the actual workload and available team tooling.

## Week 1 script scheduling example

Example crontab entry (illustrative only; this lab does not run it):

```cron
15 6 * * * /usr/bin/env bash /opt/dataforge/scripts/week1_fetch_csv.sh --output-dir /var/lib/dataforge/week1 >> /var/log/dataforge-week1.log 2>&1
```

## SSH in five lines

1. SSH encrypts a terminal session between the local client and a remote host.
2. Verify the server host key fingerprint before trusting a new host.
3. Prefer a scoped key and agent; never share or commit a private key.
4. `ssh user@host` opens the remote shell; `-i` and `-p` select a key or port when needed.
5. This mini-lab uses no remote host; the command is explanatory, not executed.
