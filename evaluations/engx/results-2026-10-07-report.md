# engx Phase A/B report

### lead-q3coder30b-q4km-nothink - THINKING_OFF
model `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | FAIL | 3 | 112 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H02-cron-next | 1 | FAIL | 3 | 48 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 1 | FAIL | 3 | 127 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | FAIL | 3 | 44 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H05-retry | 1 | FAIL | 3 | 59 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 1 | FAIL | 3 | 122 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 29 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 1 | FAIL | 3 | 68 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | FAIL | 3 | 61 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 1 | PASS | 1 | 12 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | FAIL | 3 | 114 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H02-cron-next | 2 | FAIL | 3 | 55 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 2 | FAIL | 3 | 158 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H04-build-order | 2 | FAIL | 3 | 40 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H05-retry | 2 | FAIL | 3 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 2 | FAIL | 3 | 36 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 44 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 103 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | FAIL | 3 | 51 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 2 | PASS | 1 | 10 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | FAIL | 3 | 114 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H02-cron-next | 3 | FAIL | 3 | 54 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 3 | FAIL | 3 | 121 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 3 | FAIL | 3 | 37 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H05-retry | 3 | FAIL | 3 | 38 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 3 | FAIL | 3 | 39 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 36 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 101 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | FAIL | 3 | 39 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 3 | PASS | 1 | 7 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |

validated 3/30 (10.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 26, 'SERVING_CONFIGURATION_FAILURE': 1}; failed attempts by class: {'MODEL_CAPABILITY': 80, 'SERVING_CONFIGURATION_FAILURE': 1}

### deep-q35-27b-q4km-nothink - THINKING_OFF
model `Qwen3.5-27B-Q4_K_M`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 137 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 2 | 175 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 1 | FAIL | 3 | 521 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | PASS | 1 | 125 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 48 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 46 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 256 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H08-glob | 1 | FAIL | 3 | 479 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | PASS | 1 | 54 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 28 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 1 | 135 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 2 | PASS | 2 | 175 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 2 | FAIL | 3 | 680 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 2 | PASS | 1 | 61 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 46 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 115 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 467 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 1 | 54 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 28 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | PASS | 1 | 135 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 2 | 188 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 3 | FAIL | 3 | 577 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 3 | PASS | 1 | 64 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 1 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 36 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 115 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 477 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 53 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 28 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |

validated 21/30 (70.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 8, 'SERVING_CONFIGURATION_FAILURE': 1}; failed attempts by class: {'MODEL_CAPABILITY': 23, 'SERVING_CONFIGURATION_FAILURE': 7}

### c-q38-27b-q4km - THINKING_OFF
model `c-q38-27b-q4km`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | FAIL | 3 | 287 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H02-cron-next | 1 | FAIL | 3 | 299 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 1 | PASS | 2 | 477 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 1 | PASS | 1 | 159 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 2 | 82 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 56 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | PASS | 1 | 42 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H08-glob | 1 | FAIL | 3 | 347 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | PASS | 1 | 70 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 30 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 3 | 294 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 2 | FAIL | 3 | 299 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 2 | PASS | 2 | 477 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 2 | FAIL | 3 | 251 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H05-retry | 2 | PASS | 2 | 83 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 56 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | PASS | 1 | 42 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H08-glob | 2 | FAIL | 3 | 309 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 1 | 70 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 33 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | FAIL | 3 | 285 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H02-cron-next | 3 | PASS | 1 | 97 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 3 | PASS | 2 | 476 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 3 | PASS | 3 | 271 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 2 | 83 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 65 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | PASS | 1 | 42 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H08-glob | 3 | FAIL | 3 | 336 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 70 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 29 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |

validated 22/30 (73.3%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 8}; failed attempts by class: {'MODEL_CAPABILITY': 34}

### c-q36-35b-a3b-q4km - THINKING_OFF
model `c-q36-35b-a3b-q4km`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 53 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 1 | 35 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 1 | FAIL | 3 | 157 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | PASS | 1 | 21 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 2 | 24 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 2 | 62 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 99 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H08-glob | 1 | FAIL | 3 | 146 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | PASS | 1 | 22 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 2 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 3 | 148 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 2 | PASS | 2 | 108 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 2 | FAIL | 3 | 216 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H04-build-order | 2 | PASS | 1 | 20 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 2 | 23 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 15 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | PASS | 3 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H08-glob | 2 | FAIL | 3 | 144 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 3 | 81 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 2 | 37 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | PASS | 3 | 152 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 2 | 70 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 3 | FAIL | 3 | 192 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 3 | PASS | 1 | 20 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 2 | 23 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 14 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 66 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 102 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | FAIL | 3 | 62 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 3 | PASS | 2 | 47 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |

validated 21/30 (70.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 7, 'SERVING_CONFIGURATION_FAILURE': 2}; failed attempts by class: {'MODEL_CAPABILITY': 40, 'SERVING_CONFIGURATION_FAILURE': 4}

### c-flashnext-gsq-1gpu - THINKING_OFF_CTX32K
model `c-flashnext-gsq-1gpu`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 134 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 3 | 224 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 1 | FAIL | 3 | 381 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | PASS | 1 | 94 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 42 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 2 | 67 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 64 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 1 | PASS | 2 | 225 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H09-ledger-root-cause | 1 | PASS | 1 | 59 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 2 | 60 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 1 | 104 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 2 | PASS | 2 | 146 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 2 | PASS | 1 | 129 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 2 | PASS | 1 | 62 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 40 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 2 | 66 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 62 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 583 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 1 | 60 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 25 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | PASS | 1 | 101 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 3 | 221 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H03-json-patch | 3 | PASS | 1 | 127 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 3 | PASS | 1 | 60 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 1 | 40 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 2 | 65 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 61 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 508 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 57 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 34 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |

validated 24/30 (80.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 6}; failed attempts by class: {'MODEL_CAPABILITY': 28}

### c-glm47flash-q4km-r2 - THINKING_OFF
model `c-glm47flash-q4km-r2`, max_tokens 4096, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | FAIL | 3 | 408 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H02-cron-next | 1 | FAIL | 3 | 114 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 1 | FAIL | 3 | 342 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | FAIL | 3 | 565 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H05-retry | 1 | FAIL | 3 | 52 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 1 | FAIL | 3 | 563 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 47 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 1 | FAIL | 3 | 155 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | FAIL | 3 | 77 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 1 | FAIL | 3 | 38 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H01-semver-range | 2 | FAIL | 3 | 239 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H02-cron-next | 2 | FAIL | 3 | 127 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H03-json-patch | 2 | FAIL | 3 | 272 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H04-build-order | 2 | FAIL | 3 | 564 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H05-retry | 2 | FAIL | 3 | 51 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 2 | PASS | 1 | 31 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 372 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 584 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | FAIL | 3 | 75 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 2 | FAIL | 3 | 45 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H01-semver-range | 3 | FAIL | 3 | 207 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H02-cron-next | 3 | FAIL | 3 | 134 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H03-json-patch | 3 | FAIL | 3 | 395 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 3 | FAIL | 3 | 119 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H05-retry | 3 | FAIL | 3 | 50 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H06-allocate | 3 | FAIL | 3 | 828 | n/r | n/r | n/r | n/r | yes | visible | length | MODEL_CAPABILITY |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 47 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 330 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | FAIL | 3 | 75 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H10-perf-report | 3 | FAIL | 3 | 47 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |

validated 1/30 (3.3%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 29}; failed attempts by class: {'MODEL_CAPABILITY': 87}

### t-q35-27b-q4km - THINKING_ON_UNBOUNDED
model `t-q35-27b-q4km`, max_tokens 16384, reasoning_budget None, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | FAIL | 3 | 2600 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H02-cron-next | 1 | FAIL | 3 | 2597 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H03-json-patch | 1 | PASS | 3 | 2593 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 1 | FAIL | 3 | 2089 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H05-retry | 1 | PASS | 1 | 148 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 156 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 971 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 1 | FAIL | 3 | 1119 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H09-ledger-root-cause | 1 | PASS | 1 | 136 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 96 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 3 | 1240 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H02-cron-next | 2 | FAIL | 3 | 2597 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H03-json-patch | 2 | PASS | 3 | 2593 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 2 | PASS | 2 | 1176 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 148 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 160 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 971 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 1149 | n/r | n/r | n/r | n/r | yes | format | length | SERVING_CONFIGURATION_FAILURE |
| H09-ledger-root-cause | 2 | PASS | 1 | 134 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 69 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H01-semver-range | 3 | FAIL | 3 | 2599 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H02-cron-next | 3 | FAIL | 3 | 2598 | n/r | n/r | n/r | n/r | no | format | length | SERVING_CONFIGURATION_FAILURE |
| H03-json-patch | 3 | PASS | 3 | 2576 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H04-build-order | 3 | FAIL | 3 | 1976 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H05-retry | 3 | PASS | 1 | 148 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 94 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 971 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 401 | n/r | n/r | n/r | n/r | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 133 | n/r | n/r | n/r | n/r | yes | hidden | stop | - |
| H10-perf-report | 3 | FAIL | 3 | 1036 | n/r | n/r | n/r | n/r | yes | hidden | stop | MODEL_CAPABILITY |

validated 16/30 (53.3%); failed task-runs by terminal class: {'SERVING_CONFIGURATION_FAILURE': 8, 'MODEL_CAPABILITY': 6}; failed attempts by class: {'SERVING_CONFIGURATION_FAILURE': 33, 'MODEL_CAPABILITY': 18}

### b-q35-27b-q4km - THINKING_ON_BOUNDED_4096
model `b-q35-27b-q4km`, max_tokens 16384, reasoning_budget 4096, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 3 | 559 | 3733 | 4114 | 2152 | yes | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 2 | 333 | 1909 | 4114 | 1207 | yes | yes | hidden | stop | - |
| H03-json-patch | 1 | PASS | 2 | 511 | 3057 | 4114 | 3036 | yes | yes | hidden | stop | - |
| H04-build-order | 1 | PASS | 1 | 238 | 1105 | 4114 | 822 | yes | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 147 | 1553 | 2510 | 545 | no | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 229 | 1075 | 4114 | 651 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 279 | 1844 | 2774 | 762 | no | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 1 | FAIL | 3 | 580 | 3088 | 4114 | 1822 | yes | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | PASS | 1 | 113 | 1818 | 1266 | 1055 | no | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 85 | 1547 | 1260 | 476 | no | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 2 | 660 | 2593 | 4114 | 2481 | yes | yes | hidden | stop | - |
| H02-cron-next | 2 | FAIL | 3 | 404 | 2377 | 4114 | 1257 | yes | yes | visible | stop | MODEL_CAPABILITY |
| H03-json-patch | 2 | PASS | 2 | 511 | 3064 | 4114 | 3036 | yes | yes | hidden | stop | - |
| H04-build-order | 2 | PASS | 1 | 239 | 1095 | 4114 | 838 | yes | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 147 | 1550 | 2510 | 545 | no | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 194 | 1075 | 3391 | 649 | no | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 271 | 1847 | 2774 | 762 | no | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 2 | FAIL | 3 | 523 | 2905 | 4114 | 1736 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 2 | 334 | 2069 | 4114 | 1056 | yes | yes | hidden | stop | - |
| H10-perf-report | 2 | FAIL | 3 | 510 | 1564 | 4114 | 446 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H01-semver-range | 3 | PASS | 3 | 612 | 3924 | 4115 | 2473 | yes | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 2 | 543 | 2022 | 4114 | 1354 | yes | yes | hidden | stop | - |
| H03-json-patch | 3 | PASS | 2 | 511 | 3054 | 4114 | 3036 | yes | yes | hidden | stop | - |
| H04-build-order | 3 | PASS | 1 | 238 | 1093 | 4114 | 822 | yes | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 1 | 147 | 1551 | 2510 | 545 | no | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 130 | 1076 | 2072 | 649 | no | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 450 | 1845 | 4114 | 744 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | FAIL | 3 | 568 | 2985 | 4114 | 1774 | yes | yes | visible | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 3 | 382 | 1823 | 4114 | 1060 | yes | yes | hidden | stop | - |
| H10-perf-report | 3 | FAIL | 3 | 515 | 1579 | 4114 | 467 | yes | yes | hidden | stop | MODEL_CAPABILITY |

validated 21/30 (70.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 9}; failed attempts by class: {'REASONING_BUDGET_EXHAUSTION': 4, 'MODEL_CAPABILITY': 36}

### b-q38-27b-q4km - THINKING_ON_BOUNDED_4096
model `b-q38-27b-q4km`, max_tokens 16384, reasoning_budget 4096, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 379 | 4265 | 4114 | 1205 | yes | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 1 | 363 | 1545 | 4114 | 1019 | yes | yes | hidden | stop | - |
| H03-json-patch | 1 | FAIL | 3 | 1513 | 4799 | 4114 | 2715 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | PASS | 1 | 342 | 1384 | 4114 | 739 | yes | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 329 | 1772 | 4114 | 533 | yes | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 323 | 1331 | 4114 | 480 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | PASS | 1 | 325 | 1462 | 4114 | 492 | yes | yes | hidden | stop | - |
| H08-glob | 1 | PASS | 3 | 1263 | 3226 | 4114 | 1704 | yes | yes | hidden | stop | - |
| H09-ledger-root-cause | 1 | PASS | 1 | 361 | 2034 | 4114 | 954 | yes | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 336 | 1774 | 4114 | 614 | yes | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 1 | 388 | 1563 | 4114 | 1360 | yes | yes | hidden | stop | - |
| H02-cron-next | 2 | PASS | 1 | 372 | 1536 | 4114 | 1142 | yes | yes | hidden | stop | - |
| H03-json-patch | 2 | FAIL | 3 | 1515 | 4763 | 4114 | 2715 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 2 | PASS | 1 | 336 | 1371 | 4114 | 659 | yes | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 328 | 1764 | 4114 | 520 | yes | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 325 | 1321 | 4114 | 509 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | PASS | 1 | 324 | 1458 | 4114 | 492 | yes | yes | hidden | stop | - |
| H08-glob | 2 | PASS | 3 | 1253 | 3215 | 4114 | 1663 | yes | yes | hidden | stop | - |
| H09-ledger-root-cause | 2 | PASS | 1 | 369 | 2025 | 4114 | 1066 | yes | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 326 | 1770 | 4114 | 482 | yes | yes | hidden | stop | - |
| H01-semver-range | 3 | PASS | 1 | 398 | 1564 | 4114 | 1507 | yes | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 3 | 1203 | 3154 | 4114 | 1469 | yes | yes | hidden | stop | - |
| H03-json-patch | 3 | FAIL | 3 | 1514 | 4755 | 4114 | 2715 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 3 | PASS | 1 | 344 | 1383 | 4114 | 765 | yes | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 1 | 328 | 1768 | 4114 | 520 | yes | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 322 | 1321 | 4114 | 473 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | PASS | 1 | 324 | 1468 | 4114 | 492 | yes | yes | hidden | stop | - |
| H08-glob | 3 | FAIL | 3 | 1307 | 3402 | 4116 | 1897 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 361 | 2025 | 4114 | 954 | yes | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 322 | 1769 | 4114 | 420 | yes | yes | hidden | stop | - |

validated 26/30 (86.7%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 4}; failed attempts by class: {'MODEL_CAPABILITY': 18}

### b-q36-35b-a3b-q4km - THINKING_ON_BOUNDED_4096
model `b-q36-35b-a3b-q4km`, max_tokens 16384, reasoning_budget 4096, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 106 | 4450 | 4114 | 1774 | yes | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 2 | 186 | 1609 | 4114 | 1014 | yes | yes | hidden | stop | - |
| H03-json-patch | 1 | FAIL | 3 | 355 | 2999 | 4114 | 2549 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H04-build-order | 1 | PASS | 2 | 170 | 1251 | 4114 | 835 | yes | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 81 | 1287 | 4114 | 515 | yes | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 80 | 935 | 4114 | 541 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | PASS | 1 | 79 | 1074 | 4114 | 475 | yes | yes | hidden | stop | - |
| H08-glob | 1 | FAIL | 3 | 273 | 1716 | 4114 | 1070 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 1 | PASS | 2 | 179 | 1482 | 4114 | 953 | yes | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 79 | 1313 | 4114 | 374 | yes | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 2 | 207 | 1667 | 4114 | 1757 | yes | yes | hidden | stop | - |
| H02-cron-next | 2 | FAIL | 3 | 278 | 2158 | 4114 | 1152 | yes | yes | visible | stop | MODEL_CAPABILITY |
| H03-json-patch | 2 | PASS | 3 | 371 | 3309 | 4114 | 2794 | yes | yes | hidden | stop | - |
| H04-build-order | 2 | PASS | 2 | 166 | 1245 | 4114 | 714 | yes | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 2 | 162 | 1327 | 4114 | 548 | yes | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 3 | 242 | 1408 | 4114 | 540 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | PASS | 1 | 80 | 1089 | 4114 | 475 | yes | yes | hidden | stop | - |
| H08-glob | 2 | FAIL | 3 | 256 | 1493 | 4116 | 1004 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 2 | PASS | 2 | 177 | 1474 | 4114 | 925 | yes | yes | hidden | stop | - |
| H10-perf-report | 2 | FAIL | 3 | 216 | 1285 | 4114 | 367 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H01-semver-range | 3 | PASS | 3 | 293 | 2092 | 4114 | 1811 | yes | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 2 | 196 | 1711 | 4114 | 1274 | yes | yes | hidden | stop | - |
| H03-json-patch | 3 | PASS | 2 | 233 | 2151 | 4114 | 2516 | yes | yes | hidden | stop | - |
| H04-build-order | 3 | PASS | 2 | 165 | 1212 | 4114 | 633 | yes | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 2 | 155 | 1449 | 4114 | 517 | yes | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 81 | 909 | 4114 | 526 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | PASS | 1 | 80 | 1054 | 4114 | 475 | yes | yes | hidden | stop | - |
| H08-glob | 3 | FAIL | 3 | 254 | 1531 | 4114 | 713 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H09-ledger-root-cause | 3 | PASS | 1 | 88 | 1352 | 4114 | 910 | yes | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 80 | 1273 | 4114 | 376 | yes | yes | hidden | stop | - |

validated 24/30 (80.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 6}; failed attempts by class: {'MODEL_CAPABILITY': 35}

### b-flashnext-gsq-64k - THINKING_ON_BOUNDED_4096
model `b-flashnext-gsq-64k`, max_tokens 16384, reasoning_budget 4096, task-runs 30

| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | valid answer | validator (last) | termination (last) | failure class |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H01-semver-range | 1 | PASS | 1 | 286 | 5861 | 4114 | 1237 | yes | yes | hidden | stop | - |
| H02-cron-next | 1 | PASS | 1 | 279 | 2273 | 4114 | 1161 | yes | yes | hidden | stop | - |
| H03-json-patch | 1 | PASS | 2 | 659 | 4262 | 4114 | 2020 | yes | yes | hidden | stop | - |
| H04-build-order | 1 | PASS | 1 | 255 | 1999 | 4114 | 722 | yes | yes | hidden | stop | - |
| H05-retry | 1 | PASS | 1 | 248 | 2493 | 4114 | 564 | yes | yes | hidden | stop | - |
| H06-allocate | 1 | PASS | 1 | 241 | 2031 | 4114 | 464 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 1 | FAIL | 3 | 749 | 3086 | 4114 | 605 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 1 | PASS | 1 | 285 | 2383 | 4113 | 1263 | yes | yes | hidden | stop | - |
| H09-ledger-root-cause | 1 | PASS | 1 | 266 | 2642 | 4114 | 906 | yes | yes | hidden | stop | - |
| H10-perf-report | 1 | PASS | 1 | 251 | 2593 | 4114 | 599 | yes | yes | hidden | stop | - |
| H01-semver-range | 2 | PASS | 1 | 306 | 2280 | 4114 | 1672 | yes | yes | hidden | stop | - |
| H02-cron-next | 2 | PASS | 1 | 276 | 2289 | 4114 | 1113 | yes | yes | hidden | stop | - |
| H03-json-patch | 2 | PASS | 1 | 330 | 2313 | 4114 | 2128 | yes | yes | hidden | stop | - |
| H04-build-order | 2 | PASS | 1 | 251 | 1921 | 4114 | 650 | yes | yes | hidden | stop | - |
| H05-retry | 2 | PASS | 1 | 246 | 2481 | 4113 | 533 | yes | yes | hidden | stop | - |
| H06-allocate | 2 | PASS | 1 | 241 | 1983 | 4114 | 462 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 2 | FAIL | 3 | 756 | 3446 | 4114 | 631 | yes | yes | visible | stop | MODEL_CAPABILITY |
| H08-glob | 2 | PASS | 3 | 910 | 3605 | 4115 | 1725 | yes | yes | hidden | stop | - |
| H09-ledger-root-cause | 2 | PASS | 1 | 270 | 2651 | 4114 | 973 | yes | yes | hidden | stop | - |
| H10-perf-report | 2 | PASS | 1 | 252 | 2558 | 4114 | 620 | yes | yes | hidden | stop | - |
| H01-semver-range | 3 | PASS | 1 | 280 | 2325 | 4114 | 1192 | yes | yes | hidden | stop | - |
| H02-cron-next | 3 | PASS | 2 | 569 | 3346 | 4114 | 1225 | yes | yes | hidden | stop | - |
| H03-json-patch | 3 | PASS | 2 | 655 | 4108 | 4114 | 1987 | yes | yes | hidden | stop | - |
| H04-build-order | 3 | PASS | 1 | 252 | 1955 | 4114 | 672 | yes | yes | hidden | stop | - |
| H05-retry | 3 | PASS | 1 | 246 | 2447 | 4114 | 536 | yes | yes | hidden | stop | - |
| H06-allocate | 3 | PASS | 1 | 244 | 2004 | 4114 | 525 | yes | yes | hidden | stop | - |
| H07-sqlite-rebuild | 3 | FAIL | 3 | 735 | 2785 | 4114 | 605 | yes | yes | hidden | stop | MODEL_CAPABILITY |
| H08-glob | 3 | PASS | 2 | 607 | 3162 | 4115 | 1575 | yes | yes | hidden | stop | - |
| H09-ledger-root-cause | 3 | PASS | 1 | 273 | 2678 | 4114 | 1015 | yes | yes | hidden | stop | - |
| H10-perf-report | 3 | PASS | 1 | 239 | 2602 | 4114 | 367 | yes | yes | hidden | stop | - |

validated 27/30 (90.0%); failed task-runs by terminal class: {'MODEL_CAPABILITY': 3}; failed attempts by class: {'MODEL_CAPABILITY': 15}

## Condition comparison (never pooled)

| run | condition | validated | median wall s/task-run | attempts | budget hits | reasoning tok p50 / p90 / max | failed: MODEL_CAPABILITY / REASONING_BUDGET_EXHAUSTION / SERVING_CONFIGURATION_FAILURE |
|---|---|---|---|---|---|---|---|
| lead-q3coder30b-q4km-nothink | THINKING_OFF | 3/30 (10.0%) | 50 | 84 | 0 | n/r | 26 / 0 / 1 |
| deep-q35-27b-q4km-nothink | THINKING_OFF | 21/30 (70.0%) | 115 | 51 | 0 | n/r | 8 / 0 / 1 |
| c-q38-27b-q4km | THINKING_OFF | 22/30 (73.3%) | 90 | 56 | 0 | n/r | 8 / 0 / 0 |
| c-q36-35b-a3b-q4km | THINKING_OFF | 21/30 (70.0%) | 57 | 65 | 0 | n/r | 7 / 0 / 2 |
| c-flashnext-gsq-1gpu | THINKING_OFF_CTX32K | 24/30 (80.0%) | 66 | 52 | 0 | n/r | 6 / 0 / 0 |
| c-glm47flash-q4km-r2 | THINKING_OFF | 1/30 (3.3%) | 130 | 88 | 0 | n/r | 29 / 0 / 0 |
| t-q35-27b-q4km | THINKING_ON_UNBOUNDED | 16/30 (53.3%) | 1003 | 67 | 0 | n/r | 6 / 0 / 8 |
| b-q35-27b-q4km | THINKING_ON_BOUNDED_4096 | 21/30 (70.0%) | 358 | 61 | 25 | 2510 / 4114 / 4115 | 9 / 0 / 0 |
| b-q38-27b-q4km | THINKING_ON_BOUNDED_4096 | 26/30 (86.7%) | 353 | 44 | 44 | 4114 / 4114 / 4116 | 4 / 0 / 0 |
| b-q36-35b-a3b-q4km | THINKING_ON_BOUNDED_4096 | 24/30 (80.0%) | 173 | 59 | 56 | 4114 / 4114 / 4116 | 6 / 0 / 0 |
| b-flashnext-gsq-64k | THINKING_ON_BOUNDED_4096 | 27/30 (90.0%) | 275 | 42 | 42 | 4114 / 4114 / 4115 | 3 / 0 / 0 |
