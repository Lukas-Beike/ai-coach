"""Claude Code PreToolUse hook: new T3 threads follow the athlete's model/effort rule.

The rule lives in thread-model-rule.json next to this file: "allowed" maps a
model name fragment (case-insensitive, e.g. "opus") to the highest effort
allowed for it. Edit that file to change the rule; no code change is needed.
Effort above "high" is never allowed without the athlete's explicit approval,
whatever the file says. A launch that inherits the model or effort is checked
only on the parts it sets. Exit code 2 blocks the call and returns the message.
"""

import json
import sys
from pathlib import Path

RULE_FILE = Path(__file__).with_name("thread-model-rule.json")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CAP = "high"


def load_rule(path=RULE_FILE):
    rule = json.loads(path.read_text(encoding="utf-8"))["allowed"]
    if not rule or not all(
        isinstance(model, str) and model and effort in EFFORTS
        for model, effort in rule.items()
    ):
        raise ValueError("allowed must map model fragments to an effort level")
    return {model.lower(): effort for model, effort in rule.items()}


def _effort(options):
    if isinstance(options, dict):
        value = options.get("effort")
    elif isinstance(options, list):
        value = next(
            (
                item.get("value")
                for item in options
                if isinstance(item, dict) and item.get("id") == "effort"
            ),
            None,
        )
    else:
        value = None
    return str(value).lower() if value is not None else None


def requested(tool_name, tool_input):
    """Yield (model, effort) for each thread the call would start."""
    if tool_name.endswith("t3_thread_launch"):
        selection = tool_input.get("modelSelection") or {}
        yield selection.get("model"), _effort(selection.get("options"))
    elif tool_name.endswith("create_threads"):
        for thread in tool_input.get("threads") or []:
            target = (thread or {}).get("target") or {}
            yield target.get("model"), _effort(target.get("options"))


def violation(model, effort, rule):
    if effort is not None and (
        effort not in EFFORTS or EFFORTS.index(effort) > EFFORTS.index(CAP)
    ):
        return f"effort {effort} is above the {CAP} cap"
    if model is None:
        return None
    limit = next((rule[key] for key in rule if key in str(model).lower()), None)
    if limit is None:
        return f"model {model} is not allowed"
    if effort is not None and EFFORTS.index(effort) > EFFORTS.index(limit):
        return f"effort {effort} is above {limit} for {model}"
    return None


def main(rule_file=RULE_FILE):
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    try:
        rule = load_rule(rule_file)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(
            f"Blocked: thread model rule {rule_file.name} is missing or invalid ({error}).",
            file=sys.stderr,
        )
        return 2
    text = ", ".join(f"{model} up to effort {effort}" for model, effort in rule.items())
    for model, effort in requested(
        str(payload.get("tool_name") or ""), payload.get("tool_input") or {}
    ):
        problem = violation(model, effort, rule)
        if problem:
            print(
                f"Blocked: {problem}. New threads must use: {text} (scripts/hooks/{rule_file.name}).",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
