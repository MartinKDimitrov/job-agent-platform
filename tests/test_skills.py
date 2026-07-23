"""Canonical skills dictionary (Phase 3): bilateral normalization, synonym fallback."""
from app.domain.skills import canon_skill, extract_skills, is_known
from app.domain.scoring import requirement_hit, score


# ---- dictionary units ----
def test_canon_collapses_aliases():
    assert canon_skill("React.js") == "react"
    assert canon_skill("reactjs") == "react"
    assert canon_skill("GCP") == "google cloud platform"
    assert canon_skill("k8s") == "kubernetes"
    assert canon_skill("golang") == "go"
    assert canon_skill("Postgres") == "postgresql"
    assert canon_skill("KMP") == "kotlin multiplatform"
    assert canon_skill("unknown-thing") == "unknown-thing"     # unknowns pass through
    assert is_known("js") and not is_known("frobnicator")


def test_extract_skills_from_free_text():
    got = extract_skills("Android Developer · Kotlin, Java, React.js, GCP, Node js")
    assert {"android", "kotlin", "java", "react", "google cloud platform", "node.js"} <= got
    # longest alias wins: 'react native' must not double-count as 'react'
    assert extract_skills("React Native developer") == {"react native"}
    # word boundaries: 'r' does not fire inside 'docker'; 'go' not inside 'django'
    assert "r" not in extract_skills("docker and django")
    assert "go" not in extract_skills("django only")
    # BG aliases
    assert "android" in extract_skills("търсим андроид разработчик")


# ---- bilateral canonization in coverage ----
def test_annotated_requirement_matches_profile_alias():
    # THE case that started it: annotation says 'react', the user typed 'React.js'
    r = {"text": "Experience with React", "kind": "must", "skills": ["react"], "weight": 4}
    assert requirement_hit(r, "Frontend · React.js, CSS") is True
    # and the reverse spelling on the annotation side
    r2 = {"text": "Experience with React", "kind": "must", "skills": ["reactjs"], "weight": 4}
    assert requirement_hit(r2, "Frontend · React, CSS") is True


def test_gcp_covers_google_cloud_both_directions():
    r = {"text": "Cloud experience", "kind": "must",
         "skills": ["google cloud platform"], "weight": 3}
    assert requirement_hit(r, "DevOps · GCP, Terraform") is True
    r2 = {"text": "Cloud experience", "kind": "must", "skills": ["gcp"], "weight": 3}
    assert requirement_hit(r2, "DevOps · Google Cloud Platform, Terraform") is True


def test_unannotated_requirement_uses_synonym_layer():
    # no 'skills' key (annotator hasn't reached it) — the dictionary still bridges GCP
    r = {"text": "Hands-on experience with GCP services", "kind": "must"}
    assert requirement_hit(r, "Platform Engineer · Google Cloud Platform, Kubernetes") is True
    r2 = {"text": "Deep knowledge of Kubernetes", "kind": "must"}
    assert requirement_hit(r2, "SRE · k8s, Terraform") is True


def test_unknown_annotation_skill_falls_back_to_raw_search():
    r = {"text": "Experience with FooBarLang", "kind": "must",
         "skills": ["foobarlang"], "weight": 3}
    assert requirement_hit(r, "Polyglot · FooBarLang, C") is True
    assert requirement_hit(r, "Java only") is False


def test_score_end_to_end_with_aliases():
    reqs = [{"text": "React experience", "kind": "must", "skills": ["react"], "weight": 4},
            {"text": "Node.js services", "kind": "must", "skills": ["node.js"], "weight": 4}]
    sc, cov, mis = score("Frontend · React.js, Node", "role", reqs)
    assert len(cov) == 2 and not mis
    assert sc == 100
