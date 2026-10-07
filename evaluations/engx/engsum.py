import json,glob,os,sys
out=sys.argv[1] if len(sys.argv)>1 else os.environ.get("ENGX_OUT", os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
rows=[]
for f in sorted(glob.glob(os.path.join(out, "eng-*.json"))):
    d=json.load(open(f)); s=d["summary"]; rows.append((d["label"],s,d.get("meta",{}).get("corpus_digest","legacy")))
print(f"{'model':18s} {'validated':>10s} {'1st-try':>8s} {'median s':>9s} {'s/task':>7s} {'tok/task':>9s}  per-rep  always-fail | flaky")
digests={g for _,_,g in rows}
if len(digests)>1: print("WARNING: mixed corpus versions", digests)
for l,s,_ in rows:
    print(f"{l:18s} {s['validated_rate']:>9.1f}% {s['first_attempt_rate']:>7.1f}% {s['median_secs_to_validated']!s:>9s} {s['mean_secs_per_task']:>7.1f} {s['mean_tokens_per_task']:>9d}  {s['validated_per_rep']}  {[x.split('-')[0] for x in s['always_fail']]} | {[x.split('-')[0] for x in s['flaky']]}")
print()
tasks=sorted({k for _,s,_ in rows for k in s["per_task_pass"]})
print(f"{'task':22s}"+"".join(f"{l[:14]:>16s}" for l,_,_ in rows))
for t in tasks: print(f"{t:22s}"+"".join(f"{s['per_task_pass'].get(t,'-'):>16s}" for _,s,_ in rows))
