"""Validation and descriptive evaluation for Phone Tracker rules.

The phone evaluates the same JSON expression shape independently while offline.
The PC evaluation is useful for rule previews and deterministic tests.
"""

from phone_tracker import PhoneTrackerError

OPERATORS = {"<", "<=", "==", ">=", ">"}
METRICS = {"app_usage_today", "app_launches_today", "category_usage_today",
           "category_launches_today", "time_of_day", "doomscroll_minutes"}
PROTECTED = {"com.android.settings", "com.android.dialer", "com.google.android.dialer",
             "com.android.systemui", "com.cleaningdashboard.phonetracker"}


def validate_expression(node, depth=0):
    if depth > 8 or not isinstance(node, dict):
        raise PhoneTrackerError("Rule expression is too deep or invalid")
    logical = [key for key in ("all", "any", "not") if key in node]
    if logical:
        if len(logical) != 1 or len(node) != 1:
            raise PhoneTrackerError("Rule expression needs one logical operator")
        key = logical[0]
        children = node[key]
        if key == "not":
            validate_expression(children, depth+1)
        elif not isinstance(children, list) or not 1 <= len(children) <= 20:
            raise PhoneTrackerError("all/any require 1 to 20 conditions")
        else:
            for child in children:
                validate_expression(child, depth+1)
        return
    metric = node.get("metric")
    if metric not in METRICS and not (isinstance(metric,str) and metric.startswith("external:")
                                       and 1 <= len(metric[9:]) <= 80):
        raise PhoneTrackerError("Unsupported rule metric")
    if node.get("operator") not in OPERATORS:
        raise PhoneTrackerError("Unsupported rule operator")
    if not isinstance(node.get("value"),(int,float,bool)):
        raise PhoneTrackerError("Rule value must be numeric or boolean")
    if metric in {"app_usage_today", "category_usage_today", "doomscroll_minutes"}:
        if node.get("unit") != "minutes":
            raise PhoneTrackerError("Usage values use minutes")
    elif node.get("unit") not in (None,"count","minutes"):
        raise PhoneTrackerError("Invalid rule unit")
    if metric in {"category_usage_today","category_launches_today"} and (
        not isinstance(node.get("category"),str) or not node["category"].strip()):
        raise PhoneTrackerError("Category rules need a category")


def validate_rule(rule):
    if not isinstance(rule,dict):
        raise PhoneTrackerError("Rule must be an object")
    target = rule.get("target")
    if not isinstance(target,str) or not 1 <= len(target) <= 256 or target in PROTECTED:
        raise PhoneTrackerError("Invalid or protected target package")
    if rule.get("action") != "block":
        raise PhoneTrackerError("Only block actions are supported")
    if not isinstance(rule.get("name"),str) or not 1 <= len(rule["name"].strip()) <= 100:
        raise PhoneTrackerError("Rule needs a name")
    validate_expression(rule.get("when"))
    return rule


def evaluate_expression(node, metrics):
    if "all" in node:
        return all(evaluate_expression(child,metrics) for child in node["all"])
    if "any" in node:
        return any(evaluate_expression(child,metrics) for child in node["any"])
    if "not" in node:
        return not evaluate_expression(node["not"],metrics)
    observed = metrics.get(node["metric"])
    if observed is None:
        return False
    expected = node["value"]
    operator = node["operator"]
    return {"<":lambda a,b:a<b,"<=":lambda a,b:a<=b,"==":lambda a,b:a==b,
            ">=":lambda a,b:a>=b,">":lambda a,b:a>b}[operator](observed,expected)
