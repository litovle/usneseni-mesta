"""Reader-facing labels for model categories; no training metadata required."""

TOPIC_LABELS = {
    "administration": "Správa města",
    "culture": "Kultura",
    "education": "Školství",
    "environment": "Životní prostředí",
    "finance": "Finance",
    "infrastructure": "Technická infrastruktura",
    "planning": "Územní plánování",
    "property": "Majetek města",
    "security": "Bezpečnost",
    "social": "Sociální a zdravotní služby",
    "sport": "Sport",
    "strategy": "Strategický rozvoj",
    "transport": "Doprava",
    "waste": "Odpady",
}


def topic_category(resolution):
    classification = resolution.get("classification") or {}
    return classification.get("category")


def topic_label(category):
    return TOPIC_LABELS.get(category, category)


def topic_catalog(resolutions):
    labels = dict(TOPIC_LABELS)
    for resolution in resolutions:
        category = topic_category(resolution)
        if category:
            labels[category] = topic_label(category)
    return dict(sorted(labels.items()))
