"""The single Critical route shared by the installed and portable controllers."""


def routing():
    assignments = (("probe", "sol"), ("plan", "astra"), ("implement", "sol"), ("verify", "sol"))
    return [
        {"round": number, "role": role, "model": "gpt-6.2-" + model, "reasoning_effort": "max",
         "service_tier": "default" if model == "astra" else "priority"}
        for number, (role, model) in enumerate(assignments, 1)
    ]


def apply(result):
    rounds = routing()
    settings = dict(result.get("requested_settings", {}))
    for key, row in zip(("probe", "lead", "owner", "verifier"), rounds):
        settings[key] = {"model": row["model"], "effort": row["reasoning_effort"],
                         "tier": "Fast" if row["service_tier"] == "priority" else "Standard"}
    return {**result, "workflow": "critical-four-v1", "lane": "Critical", "owner": "sol", "lead": "astra",
            "final_review": "sol", "audits": ["combined"], "rounds": rounds, "requested_settings": settings,
            "entrypoint": "i2e.py critical"}
