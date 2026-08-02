"""The 50 release-check profiles — deliberately spread across everything that has ever broken.

Each entry is (key, target_roles, skills, country, city, remote_pref, education, languages).
`education` is the NKPD 0-8 level the candidate states about themselves (None = not stated).

Coverage is the point, so the set spans:
- **professions**: all 16 ESCO verticals, not just IT — the concrete-finisher-vs-DevOps and
  accountant-vs-logistics bugs both came from non-tech profiles;
- **markets**: BG plus the countries our aggregators actually cover (DE/FR/ES/IT/NL/PL/RO/GR/IE),
  so postings whose TITLES are not in English get exercised;
- **employment type**: remote / hybrid / on-site, and seniority from apprentice to lead — the
  seniority and location soft factors only fire on some of these;
- **education**: from none stated to doctorate, since the qualification factor and the
  degree-coverage rule both key off it.
"""
from __future__ import annotations

# (key, target_roles, skills, country, city, remote_pref, education, languages)
PROFILES: list[tuple] = [
    # ---- IT (the families are fine-grained here, so several near-neighbours) ----
    ("backend_bg", "Backend Developer", "Python, Django, PostgreSQL, Docker, REST API",
     "Bulgaria", "Sofia", "remote", 6, "Bulgarian, English"),
    ("frontend_bg", "Frontend Developer", "JavaScript, TypeScript, React, CSS, Redux",
     "Bulgaria", "Plovdiv", "hybrid", 6, "Bulgarian, English"),
    ("android_bg", "Android Developer", "Kotlin, Jetpack Compose, Coroutines, MVVM, Android SDK",
     "Bulgaria", "Sofia", "remote", 6, "Bulgarian, English"),
    ("ios_de", "iOS Developer", "Swift, SwiftUI, UIKit, Combine, Xcode",
     "Germany", "Berlin", "hybrid", 6, "German, English"),
    ("devops_bg", "DevOps Engineer", "Kubernetes, Terraform, AWS, CI/CD, Docker, Prometheus",
     "Bulgaria", "Sofia", "remote", 6, "Bulgarian, English"),
    ("qa_bg", "QA Engineer", "test automation, Selenium, Playwright, pytest, API testing",
     "Bulgaria", "Varna", "hybrid", 5, "Bulgarian, English"),
    ("data_eng_pl", "Data Engineer", "SQL, Spark, dbt, Airflow, Python, Snowflake",
     "Poland", "Krakow", "remote", 6, "Polish, English"),
    ("ml_bg", "Machine Learning Engineer", "Python, PyTorch, scikit-learn, MLOps, LLM, Docker",
     "Bulgaria", "Sofia", "remote", 7, "Bulgarian, English"),
    ("security_nl", "Security Engineer", "penetration testing, SIEM, ISO 27001, incident response",
     "Netherlands", "Amsterdam", "hybrid", 6, "Dutch, English"),
    # ---- finance ----
    ("accountant_bg", "Accountant, bookkeeper", "accounting, IFRS, tax, payroll, Excel, ERP",
     "Bulgaria", "Sofia", "hybrid", 6, "Bulgarian, English"),
    ("junior_accountant_bg", "Junior Accountant", "bookkeeping, invoices, Excel, VAT",
     "Bulgaria", "Ruse", "onsite", 5, "Bulgarian"),
    ("auditor_ro", "Financial Auditor", "audit, IFRS, internal control, risk assessment",
     "Romania", "Bucharest", "hybrid", 7, "Romanian, English"),
    ("financial_analyst_de", "Financial Analyst", "financial modelling, Excel, SAP, forecasting",
     "Germany", "Frankfurt", "hybrid", 7, "German, English"),
    ("bank_teller_bg", "Bank Teller", "cash handling, customer service, banking products",
     "Bulgaria", "Sofia", "onsite", 3, "Bulgarian"),
    # ---- healthcare ----
    ("nurse_bg", "Nurse", "patient care, medication, vital signs, clinical documentation",
     "Bulgaria", "Sofia", "onsite", 6, "Bulgarian"),
    ("nurse_de", "Nurse", "patient care, geriatric care, medication, documentation",
     "Germany", "Munich", "onsite", 5, "German"),
    ("physiotherapist_bg", "Physiotherapist", "rehabilitation, manual therapy, exercise therapy",
     "Bulgaria", "Varna", "onsite", 6, "Bulgarian"),
    ("pharmacist_gr", "Pharmacist", "dispensing, pharmacology, prescriptions, stock control",
     "Greece", "Athens", "onsite", 7, "Greek, English"),
    ("care_assistant_ie", "Healthcare Assistant", "personal care, elderly care, hygiene, mobility",
     "Ireland", "Dublin", "onsite", 3, "English"),
    # ---- construction & trades ----
    ("concrete_bg", "Concrete Finisher, Construction Worker",
     "concrete, formwork, rebar, screed, site safety", "Bulgaria", "Sofia", "onsite", 3,
     "Bulgarian"),
    ("welder_bg", "Welder", "MIG MAG welding, TIG, metal fabrication, blueprint reading",
     "Bulgaria", "Plovdiv", "onsite", 3, "Bulgarian"),
    ("electrician_de", "Electrician", "electrical installation, wiring, fault finding, VDE",
     "Germany", "Hamburg", "onsite", 5, "German"),
    ("plumber_bg", "Plumber", "pipe fitting, heating systems, sanitary installation",
     "Bulgaria", "Burgas", "onsite", 3, "Bulgarian"),
    ("carpenter_ro", "Carpenter", "timber framing, formwork, finishing, power tools",
     "Romania", "Cluj", "onsite", 3, "Romanian"),
    ("cnc_operator_bg", "CNC Operator", "CNC milling, turning, technical drawings, calipers",
     "Bulgaria", "Stara Zagora", "onsite", 5, "Bulgarian"),
    ("mechanic_bg", "Car Mechanic", "engine repair, diagnostics, brakes, suspension",
     "Bulgaria", "Sofia", "onsite", 3, "Bulgarian"),
    # ---- transport & logistics ----
    ("truck_driver_bg", "Truck Driver", "category C+E, tachograph, ADR, long distance",
     "Bulgaria", "Sofia", "onsite", 3, "Bulgarian"),
    ("warehouse_bg", "Warehouse Worker", "forklift, picking, inventory, WMS",
     "Bulgaria", "Sofia", "onsite", 3, "Bulgarian"),
    ("logistics_pl", "Logistics Specialist", "freight forwarding, customs, planning, Excel",
     "Poland", "Warsaw", "hybrid", 6, "Polish, English"),
    ("courier_bg", "Delivery Driver", "category B, route planning, parcels, customer contact",
     "Bulgaria", "Varna", "onsite", 3, "Bulgarian"),
    # ---- sales, marketing, hospitality, services ----
    ("sales_rep_bg", "Sales Representative", "B2B sales, CRM, negotiation, lead generation",
     "Bulgaria", "Sofia", "hybrid", 6, "Bulgarian, English"),
    ("shop_assistant_bg", "Shop Assistant", "customer service, cash register, merchandising",
     "Bulgaria", "Pleven", "onsite", 3, "Bulgarian"),
    ("marketing_es", "Digital Marketing Specialist", "SEO, Google Ads, analytics, content",
     "Spain", "Barcelona", "remote", 6, "Spanish, English"),
    ("account_manager_it", "Account Manager", "key accounts, upselling, CRM, negotiation",
     "Italy", "Milan", "hybrid", 6, "Italian, English"),
    ("chef_bg", "Chef, Cook", "menu planning, food safety, HACCP, kitchen management",
     "Bulgaria", "Bansko", "onsite", 5, "Bulgarian"),
    ("waiter_gr", "Waiter", "table service, POS, upselling, customer care",
     "Greece", "Thessaloniki", "onsite", 3, "Greek, English"),
    ("hotel_reception_bg", "Hotel Receptionist", "check-in, PMS, reservations, guest relations",
     "Bulgaria", "Varna", "onsite", 5, "Bulgarian, English"),
    ("hairdresser_bg", "Hairdresser", "cutting, colouring, styling, client consultation",
     "Bulgaria", "Sofia", "onsite", 5, "Bulgarian"),
    ("cleaner_bg", "Cleaner", "cleaning, disinfection, equipment, schedules",
     "Bulgaria", "Sofia", "onsite", 1, "Bulgarian"),
    # ---- admin, legal, education, agriculture, engineering, management ----
    ("office_admin_bg", "Office Administrator", "MS Office, scheduling, correspondence, filing",
     "Bulgaria", "Sofia", "onsite", 5, "Bulgarian, English"),
    ("hr_specialist_bg", "HR Specialist", "recruitment, onboarding, labour law, payroll",
     "Bulgaria", "Sofia", "hybrid", 6, "Bulgarian, English"),
    ("lawyer_bg", "Lawyer", "commercial law, contracts, litigation, compliance",
     "Bulgaria", "Sofia", "hybrid", 7, "Bulgarian, English"),
    ("teacher_bg", "Teacher", "lesson planning, classroom management, assessment",
     "Bulgaria", "Sofia", "onsite", 7, "Bulgarian, English"),
    ("kindergarten_bg", "Kindergarten Teacher", "early years, child development, activities",
     "Bulgaria", "Plovdiv", "onsite", 6, "Bulgarian"),
    ("agronomist_bg", "Agronomist", "crop management, soil analysis, irrigation, pesticides",
     "Bulgaria", "Dobrich", "onsite", 6, "Bulgarian"),
    ("mech_engineer_de", "Mechanical Engineer", "CAD, SolidWorks, tolerances, manufacturing",
     "Germany", "Stuttgart", "hybrid", 7, "German, English"),
    ("civil_engineer_bg", "Civil Engineer", "structural design, AutoCAD, site supervision",
     "Bulgaria", "Sofia", "hybrid", 7, "Bulgarian, English"),
    ("project_manager_fr", "Project Manager", "Agile, Scrum, stakeholders, budgets, Jira",
     "France", "Paris", "hybrid", 7, "French, English"),
    ("designer_bg", "Graphic Designer", "Figma, Adobe, branding, typography, UI",
     "Bulgaria", "Sofia", "remote", 6, "Bulgarian, English"),
    ("student_bg", "Junior Software Developer", "Python, Git, SQL, algorithms",
     "Bulgaria", "Sofia", "hybrid", None, "Bulgarian, English"),
]

assert len(PROFILES) == 50, f"the release set is meant to be 50 profiles, found {len(PROFILES)}"
