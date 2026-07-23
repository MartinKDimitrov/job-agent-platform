"""Canonical skills dictionary (Phase 3 of the matching plan) — the deterministic layer
AFTER the LLM and AROUND the user: whatever the annotator returns ('reactjs', 'react.js')
and whatever the user typed ('React.js', 'GCP') both collapse to one canonical string, so
the coverage intersection actually intersects. Applied at WRITE (annotation output) and at
READ (requirement_hit) — a new dictionary entry takes effect instantly, no re-annotation.

Also the synonym layer for the token-fallback on un-annotated requirements, and the future
backbone of the ontology (ESCO hierarchy in Phase 4 of the product roadmap).

Keep entries lowercase. Multi-word aliases are supported (matched with word boundaries).
Unknown skills are logged by the callers — reviewing that log is what keeps this alive.
"""
from __future__ import annotations

import re

# canonical -> aliases (the canonical name itself is implicitly an alias)
_ALIASES: dict[str, tuple[str, ...]] = {
    # languages
    "javascript": ("js", "джаваскрипт"),
    "typescript": ("ts",),
    "python": ("py", "питон"),
    "java": ("джава",),
    "kotlin": ("котлин",),
    "go": ("golang",),
    "c#": ("csharp", "c sharp"),
    "c++": ("cpp",),
    ".net": ("dotnet", "dot net", ".net core", "asp.net", "asp.net core"),
    "php": (),
    "ruby": ("ruby on rails", "rails"),
    "swift": (),
    "objective-c": ("objc", "objective c"),
    "scala": (), "rust": (), "r": (), "dart": (), "elixir": (),
    # frontend
    "react": ("reactjs", "react.js", "react js"),
    "react native": ("reactnative",),
    "angular": ("angularjs", "angular.js"),
    "vue": ("vuejs", "vue.js"),
    "next.js": ("nextjs",),
    "svelte": (),
    "html": ("html5",), "css": ("css3", "scss", "sass"),
    # backend / frameworks
    "node.js": ("node", "nodejs", "node js"),
    "spring": ("spring boot", "springboot", "spring framework"),
    "django": (), "flask": (), "fastapi": (), "laravel": (), "symfony": (),
    "hibernate": (), "express": ("express.js", "expressjs"),
    # mobile
    "android": ("android sdk", "андроид"),
    "ios": (),
    "jetpack compose": (),
    "kotlin multiplatform": ("kmp", "kotlin multiplatform mobile", "kmm"),
    "swiftui": (), "flutter": (), "xamarin": (),
    # data / ml
    "machine learning": ("ml",),
    "deep learning": (),
    "pytorch": (), "tensorflow": (),
    "scikit-learn": ("sklearn", "scikit learn"),
    "pandas": (), "numpy": (),
    "llm": ("large language models", "large language model", "llms"),
    "rag": ("retrieval augmented generation",),
    "nlp": ("natural language processing",),
    "computer vision": ("cv",),
    "data science": (), "data engineering": (), "mlops": (),
    "spark": ("apache spark", "pyspark"), "airflow": ("apache airflow",),
    "databricks": (), "snowflake": (),
    # databases
    "postgresql": ("postgres", "psql"),
    "mysql": (), "mariadb": (),
    "sql server": ("mssql", "ms sql", "microsoft sql server", "t-sql", "tsql"),
    "mongodb": ("mongo",),
    "redis": (), "elasticsearch": ("elastic search",), "cassandra": (),
    "oracle": ("pl/sql", "plsql"),
    "sqlite": (), "clickhouse": (), "dynamodb": (),
    # cloud / devops
    "aws": ("amazon web services",),
    "google cloud platform": ("gcp", "google cloud"),
    "azure": ("microsoft azure",),
    "kubernetes": ("k8s",),
    "docker": (), "docker compose": (),
    "terraform": (), "ansible": (), "helm": (),
    "jenkins": (), "gitlab ci": ("gitlab-ci",), "github actions": (),
    "ci/cd": ("cicd", "ci cd", "continuous integration", "continuous delivery"),
    "linux": (), "bash": ("shell scripting", "shell"), "powershell": (),
    "grafana": (), "prometheus": (), "nginx": (),
    # messaging / apis
    "kafka": ("apache kafka",),
    "rabbitmq": (),
    "graphql": (), "grpc": (),
    "rest api": ("rest", "restful", "restful api", "restful apis", "rest apis"),
    "microservices": ("microservice", "микросървиси", "микроуслуги"),
    "websockets": ("websocket",),
    # testing / tools
    "selenium": (), "appium": (), "cypress": (), "playwright": (),
    "junit": (), "pytest": (), "jest": (),
    "git": (), "jira": (), "gradle": (), "maven": (), "webpack": (),
    # methods / misc
    "agile": ("scrum", "аджайл", "скръм"),
    "sql": ("сикуел",),
    "oop": ("object oriented programming", "object-oriented programming", "ооп"),
    "design patterns": ("солид", "solid"),
    "unit testing": ("unit tests", "юнит тестове"),
    # skills-v1.1 (2026-07-24): top unknown-skill candidates from the in-session annotation
    # runs over the doubled index — roles/domains employers name as requirements
    "devops": ("dev ops", "девопс"),
    "sre": ("site reliability engineering", "site reliability engineer"),
    "finops": ("cloud cost management", "cloud cost optimization"),
    "distributed systems": ("distributed computing",),
    "data pipelines": ("data pipeline", "etl pipelines"),
    "ai agents": ("agentic ai", "ai agent", "llm agents"),
    "cybersecurity": ("cyber security", "information security", "infosec",
                      "security engineering"),
    "disaster recovery": ("business continuity",),
    "data structures": ("data structures and algorithms",),
    "algorithms": (),
    "splunk": (), "kibana": (), "datadog": (), "argocd": ("argo cd",), "helm": (),
    "openshift": (), "cloudformation": (), "logstash": (), "gitlab": (),
    "english": ("английски", "english language"),
}

# reverse index: alias -> canonical (canonical maps to itself)
_CANON: dict[str, str] = {}
for _c, _als in _ALIASES.items():
    _CANON[_c] = _c
    for _a in _als:
        _CANON[_a] = _c

DICTIONARY_VERSION = "skills-v1"     # provenance only — read-side canon needs no re-annotation

# one big word-boundary regex over all aliases (longest first, so 'react native' wins 'react')
_ALIAS_RE = re.compile(
    r"(?<![a-z0-9+#.])("
    + "|".join(re.escape(a) for a in sorted(_CANON, key=len, reverse=True))
    + r")(?![a-z0-9+#])", re.I)


def canon_skill(s: str) -> str:
    """Canonical form of one skill string ('React.js' -> 'react'); unknowns lowercase as-is."""
    low = (s or "").strip().lower()
    return _CANON.get(low, low)


def is_known(s: str) -> bool:
    return (s or "").strip().lower() in _CANON


def extract_skills(text: str) -> set[str]:
    """All canonical skills mentioned in free text (profile skills field, requirement text)."""
    return {_CANON[m.group(1).lower()] for m in _ALIAS_RE.finditer(text or "")}


# Skills too common to signal RELEVANCE on their own — the recall stop-list (a 'git' or
# 'sql' overlap must not flood the candidate set; they still count for COVERAGE).
RECALL_GENERIC_SKILLS = frozenset({
    "git", "sql", "rest api", "agile", "oop", "unit testing", "ci/cd", "linux", "bash",
    "jira", "html", "css", "docker", "design patterns", "microservices",
    # v1.1: near-universal in JDs — coverage yes, relevance no
    "english", "algorithms", "data structures", "distributed systems",
})
