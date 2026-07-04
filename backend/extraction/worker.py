"""Child-process entry point for the job manager.

Runs one extraction in an isolated process so a hang or hard crash
(segfault in a PDF library) can be killed without taking down the server.
Writes the ExtractionResult dict as JSON to `out_path`.

Test hooks (env vars, propagated to the spawned child):
  EXTRACT_TEST_SLEEP       — seconds to sleep before extracting (timeout tests)
  EXTRACT_TEST_CRASH_ONCE  — marker file path; crash if absent, create it and
                             exit(3) so the *retry* succeeds (crash-retry tests)
"""
import json
import os
import sys
import time


def run(pdf_path: str, out_path: str) -> None:
    delay = float(os.environ.get("EXTRACT_TEST_SLEEP", "0"))
    if delay:
        time.sleep(delay)

    crash_marker = os.environ.get("EXTRACT_TEST_CRASH_ONCE")
    if crash_marker and not os.path.exists(crash_marker):
        with open(crash_marker, "w") as f:
            f.write("crashed")
        sys.exit(3)

    from backend.extraction import extract

    result = extract(pdf_path)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f)


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
