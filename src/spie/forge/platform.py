"""Call the existing Studio verifier without importing/publishing any content."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

_BRIDGE = """
import { pathToFileURL } from 'node:url';
const { verifyBatch } = await import(pathToFileURL(process.argv[1]).href);
let input = '';
for await (const chunk of process.stdin) input += chunk;
const report = verifyBatch(JSON.parse(input), {batchId: 'corpus-preview', mode: 'strict'});
console.log(JSON.stringify({items: report.items, rejectHistogram: report.rejectHistogram}));
"""


def check_platform(result: dict, verifier: Path) -> dict:
    """Use an explicitly selected local source file. Fail closed if it cannot run.

The verifier checks editorial contracts; it does not establish truth. It runs
without the Studio's Firebase initialization and does not modify its registry.
"""
    verifier = verifier.resolve(strict=True)
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", _BRIDGE, str(verifier)],
        input=json.dumps(result["items"]), text=True, encoding="utf-8",
        capture_output=True, timeout=30, check=False,
    )
    if completed.returncode:
        raise ValueError("Studio verifier failed to run; no platform-checked output was saved")
    report = json.loads(completed.stdout)
    checks = report["items"]
    if len(checks) != len(result["items"]):
        raise ValueError("Studio verifier report length mismatch")
    kept = []
    for i, (item, check) in enumerate(zip(result["items"], checks, strict=True)):
        if check.get("index") != i or type(check.get("passed")) is not bool:
            raise ValueError("Studio verifier returned a malformed verdict")
        if check["passed"]:
            kept.append(item)
        else:
            result["rejected"].append({"item": item,
                                       "issues": check["rejects"] or check.get("warns", []),
                                       "stage": "platform-editorial"})
    result["items"] = kept
    result["checks"]["platform_verifier"] = {
        "path": str(verifier), "sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
        "scope": "schema and editorial rules, NOT answer correctness", "report": report,
    }
    return result
