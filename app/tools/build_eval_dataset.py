"""Rebuild evals/matching_v1.json from staging postings (reproducible; needs the tunnel).

    python -m app.tools.build_eval_dataset

Picks are REAL postings, hand-graded per profile (0 irrelevant / 1 adjacent / 2 relevant);
`review: true` marks borderline judgments awaiting the owner's confirmation.
"""
import json

from ..data.db import SessionLocal
from ..data.models import Posting

# (posting_id, grade_android, grade_ml, grade_backend, review)
PICKS = [
    (38, 2, 0, 0, False), (33, 2, 0, 0, False), (655, 2, 0, 0, False),
    (36, 2, 0, 0, False), (35, 2, 0, 1, False), (838, 2, 0, 0, False),
    (751, 2, 0, 0, False),
    (933, 1, 0, 0, True), (1510, 1, 0, 0, True), (1054, 1, 0, 0, True),
    (850, 1, 0, 0, True), (663, 0, 0, 0, True),
    (1190, 0, 2, 1, False), (1513, 0, 2, 1, False), (1007, 0, 2, 0, False),
    (956, 0, 2, 0, False), (942, 0, 2, 0, False), (1058, 0, 2, 0, False),
    (954, 0, 2, 1, False), (1270, 0, 1, 0, True), (1030, 0, 1, 1, True),
    (1278, 0, 1, 2, False),
    (1520, 0, 0, 2, False), (1518, 0, 0, 2, False), (1176, 0, 1, 2, False),
    (1519, 0, 0, 2, False), (1247, 0, 0, 2, False), (1169, 0, 0, 1, False),
    (1192, 0, 1, 1, False), (1514, 0, 0, 1, False), (1315, 0, 0, 1, True),
    (1524, 0, 0, 0, False), (1505, 0, 0, 0, False), (1485, 0, 0, 0, False),
    (1516, 0, 0, 0, False), (1409, 0, 0, 0, False), (1350, 0, 0, 0, False),
]

PROFILES = {
    "p1_android": {"name": "Android Developer", "target_roles": "Android Developer",
                   "skills": "Kotlin, Java, Jetpack Compose, Coroutines, MVVM, Android SDK, "
                             "REST API, Git, Gradle",
                   "experience": "8 years native Android development, apps with millions of users"},
    "p2_ml": {"name": "Machine Learning Engineer",
              "target_roles": "Machine Learning Engineer, AI Engineer",
              "skills": "Python, PyTorch, scikit-learn, LLM, RAG, MLOps, SQL, Docker",
              "experience": "5 years building and deploying ML models and LLM applications"},
    "p3_backend": {"name": "Backend Developer",
                   "target_roles": "Backend Developer, Software Engineer",
                   "skills": "Python, Go, PostgreSQL, Kubernetes, AWS, REST API, microservices",
                   "experience": "6 years backend services and distributed systems"},
}

DESC_CHARS = 4000   # enough that extraction sees the real requirement sections


def main() -> None:
    with SessionLocal() as db:
        postings = {}
        for pid, *_ in PICKS:
            p = db.get(Posting, pid)
            assert p is not None, f"posting {pid} disappeared from staging"
            postings[pid] = {"id": pid, "title": p.title.strip(), "company": p.company,
                             "location": p.location,
                             "description": (p.description or "")[:DESC_CHARS]}
    dataset = {"version": "matching-eval-v1", "profiles": PROFILES,
               "postings": list(postings.values()),
               "labels": {k: {} for k in PROFILES}}
    for pid, g1, g2, g3, review in PICKS:
        for key, g in (("p1_android", g1), ("p2_ml", g2), ("p3_backend", g3)):
            dataset["labels"][key][str(pid)] = {"grade": g, "review": review}
    with open("evals/matching_v1.json", "w") as f:
        json.dump(dataset, f, ensure_ascii=False, indent=1)
    print(f"dataset: {len(postings)} postings × {len(PROFILES)} profiles "
          f"({sum(1 for p in PICKS if p[4])} flagged for review)")


if __name__ == "__main__":
    main()
