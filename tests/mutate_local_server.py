#!/usr/bin/env python3
"""Mutation-test the desktop app's start-up (0.1.44 H1) in mcp/local_server.py,
graded by tests/regression/test_local_server.py: bind first; on an occupied
port say what holds it -- another CRM app, by its own version, or another
program -- and never print the banner or open the browser.

Not mutated: Server.allow_reuse_address (off on Windows). It only changes
behaviour on Windows, and the suite runs on macOS, where the mutant would be
equivalent; it is a platform guard, named in the report.

Scoring, baseline and anchor guards live in tests/lib/mutate_lib.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from mutate_lib import mutate

SRC = "plugins/unrivaled-solutions/skills/crm"
TEST = "./tests/regression/test_local_server.py"

M = [
 ("the browser opens before the bind again",
  "    try:\n        httpd = Server((\"127.0.0.1\", args.port), Handler)\n",
  "    if not args.no_browser:\n        webbrowser.open(url)\n"
  "    try:\n        httpd = Server((\"127.0.0.1\", args.port), Handler)\n"),
 ("the banner prints before the bind again",
  "    try:\n        httpd = Server((\"127.0.0.1\", args.port), Handler)\n",
  "    print(f\"[local-server] CRM v{server.SERVER_VERSION} store={STORE_DIR}\", file=sys.stderr)\n"
  "    try:\n        httpd = Server((\"127.0.0.1\", args.port), Handler)\n"),
 ("what holds the port is not probed",
  "        kind, version = probe_holder(args.port)\n", "        kind, version = \"other\", None\n"),
 ("the running app's version is not read",
  "    return \"crm\", (str(v) if v else None)\n", "    return \"crm\", None\n"),
 ("any page counts as the CRM app",
  "    if \"<title>Unrivaled CRM</title>\" not in page:\n", "    if False:\n"),
 # re-anchored after the review: the probe reads through _fetch
 ("the older app's token is not used, so its version is never read",
  "                                 {\"X-Bridge-Token\": m.group(1)}).decode(\"utf-8\", \"replace\"))\n",
  "                                 {}).decode(\"utf-8\", \"replace\"))\n"),
 ("the probe is not hard-bounded: trickled headers hang the new app (round 2)",
  "    t.join(budget + 0.5)\n    return (\"other\", None) if t.is_alive() else tuple(out)\n",
  "    t.join()\n    return tuple(out)\n"),
 ("the probe reads a big page to the end, and calls a CRM app another program (round 2)",
  "            if enough and enough(b\"\".join(chunks)):\n", "            if False:\n"),
 # RETIRED (round 2), the code it mutated removed: "the probe has no total
 # budget". Once probe_holder ran the probe in a thread joined for the budget,
 # the body loop's own deadline check had no observable effect -- a trickling
 # or silent holder is abandoned at the join either way, the same exit and
 # message -- so the mutant survived as equivalent and the redundant check was
 # removed. "the probe is not hard-bounded" grades the bound that remains.
 ("an occupied port exits zero",
  "        sys.exit(f\"Another CRM app{f' (v{version})' if version else ''} is already \"\n",
  "        print(f\"Another CRM app{f' (v{version})' if version else ''} is already \"\n"),
]

sys.exit(mutate(SRC, TEST, "mcp/local_server.py", M))
