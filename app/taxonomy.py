"""Curated occupation → skills seed for the light onboarding (Stage 1, IT-first per DECISIONS A1).

Each occupation carries a Bulgarian and English label plus its typical skills. The user picks an
occupation and gets these as editable chips — a ~30-second, mostly-click profile. Stage 2 swaps
this seed for the full ESCO taxonomy (with BG labels) covering every profession; the shape stays
the same, so callers don't change. Skills also feed normalized matching later (ARCHITECTURE §7).
"""

OCCUPATIONS = [
    {"id": "android-dev", "bg": "Android разработчик", "en": "Android Developer",
     "skills": ["Kotlin", "Java", "Jetpack Compose", "Coroutines", "MVVM", "Android SDK",
                "REST API", "Git", "Gradle"]},
    {"id": "ios-dev", "bg": "iOS разработчик", "en": "iOS Developer",
     "skills": ["Swift", "SwiftUI", "UIKit", "Objective-C", "Combine", "REST API", "Git", "Xcode"]},
    {"id": "frontend-dev", "bg": "Frontend разработчик", "en": "Frontend Developer",
     "skills": ["JavaScript", "TypeScript", "React", "HTML", "CSS", "Redux", "REST API", "Git"]},
    {"id": "backend-dev", "bg": "Backend разработчик", "en": "Backend Developer",
     "skills": ["Java", "Kotlin", "Spring", "SQL", "PostgreSQL", "REST API", "Docker", "Git",
                "Microservices"]},
    {"id": "fullstack-dev", "bg": "Fullstack разработчик", "en": "Fullstack Developer",
     "skills": ["JavaScript", "TypeScript", "React", "Node.js", "SQL", "REST API", "Docker", "Git"]},
    {"id": "python-dev", "bg": "Python разработчик", "en": "Python Developer",
     "skills": ["Python", "Django", "Flask", "FastAPI", "SQL", "PostgreSQL", "REST API", "Docker",
                "Git"]},
    {"id": "dotnet-dev", "bg": ".NET разработчик", "en": ".NET Developer",
     "skills": ["C#", ".NET", "ASP.NET", "SQL Server", "Entity Framework", "REST API", "Azure",
                "Git"]},
    {"id": "php-dev", "bg": "PHP разработчик", "en": "PHP Developer",
     "skills": ["PHP", "Laravel", "Symfony", "MySQL", "JavaScript", "REST API", "Git"]},
    {"id": "qa-manual", "bg": "QA инженер (ръчно тестване)", "en": "QA Engineer",
     "skills": ["Manual Testing", "Test Cases", "Jira", "SQL", "API Testing", "Bug Tracking",
                "Agile"]},
    {"id": "qa-automation", "bg": "QA Automation инженер", "en": "QA Automation Engineer",
     "skills": ["Selenium", "Java", "Python", "TestNG", "Cypress", "CI/CD", "API Testing", "Git"]},
    {"id": "devops", "bg": "DevOps инженер", "en": "DevOps Engineer",
     "skills": ["Docker", "Kubernetes", "CI/CD", "Linux", "AWS", "Terraform", "Bash", "Ansible",
                "Git"]},
    {"id": "cloud", "bg": "Cloud инженер", "en": "Cloud Engineer",
     "skills": ["AWS", "Azure", "GCP", "Kubernetes", "Terraform", "Docker", "Linux", "Networking"]},
    {"id": "data-engineer", "bg": "Data инженер", "en": "Data Engineer",
     "skills": ["Python", "SQL", "Spark", "Airflow", "ETL", "PostgreSQL", "Kafka", "AWS"]},
    {"id": "data-scientist", "bg": "Data Scientist", "en": "Data Scientist",
     "skills": ["Python", "Pandas", "NumPy", "Scikit-learn", "SQL", "Statistics",
                "Machine Learning", "Jupyter"]},
    {"id": "ml-engineer", "bg": "ML инженер", "en": "Machine Learning Engineer",
     "skills": ["Python", "PyTorch", "TensorFlow", "MLOps", "Docker", "SQL", "Machine Learning",
                "Scikit-learn"]},
    {"id": "sysadmin", "bg": "Системен администратор", "en": "System Administrator",
     "skills": ["Linux", "Windows Server", "Networking", "Bash", "Active Directory", "VMware",
                "Monitoring"]},
    {"id": "security", "bg": "Инженер по киберсигурност", "en": "Security Engineer",
     "skills": ["Network Security", "Penetration Testing", "SIEM", "Linux", "Python", "Firewalls",
                "OWASP"]},
    {"id": "dba", "bg": "Database администратор", "en": "Database Administrator",
     "skills": ["SQL", "PostgreSQL", "MySQL", "Oracle", "Performance Tuning", "Backup",
                "Replication"]},
    {"id": "ux-ui", "bg": "UX/UI дизайнер", "en": "UX/UI Designer",
     "skills": ["Figma", "Sketch", "Adobe XD", "Wireframing", "Prototyping", "User Research",
                "Design Systems"]},
    {"id": "product-manager", "bg": "Продуктов мениджър", "en": "Product Manager",
     "skills": ["Product Strategy", "Roadmapping", "Agile", "Jira", "Analytics",
                "Stakeholder Management", "User Research"]},
    {"id": "project-manager", "bg": "Проектен мениджър", "en": "Project Manager",
     "skills": ["Agile", "Scrum", "Jira", "Risk Management", "Stakeholder Management", "Budgeting",
                "Planning"]},
    {"id": "business-analyst", "bg": "Бизнес анализатор", "en": "Business Analyst",
     "skills": ["Requirements Analysis", "SQL", "Jira", "UML", "Stakeholder Management",
                "Documentation", "Agile"]},
    {"id": "scrum-master", "bg": "Scrum Master", "en": "Scrum Master",
     "skills": ["Scrum", "Agile", "Jira", "Facilitation", "Kanban", "Coaching",
                "Stakeholder Management"]},
]

_BY_ID = {o["id"]: o for o in OCCUPATIONS}


def by_id(occupation_id: str) -> dict | None:
    return _BY_ID.get(occupation_id)


def all_skills() -> list[str]:
    """De-duplicated, sorted union of every occupation's skills — for the autocomplete list."""
    seen = set()
    for o in OCCUPATIONS:
        seen.update(o["skills"])
    return sorted(seen, key=str.lower)
