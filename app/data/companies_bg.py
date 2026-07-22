"""Seed candidates for the company registry (ROADMAP 16б): notable tech employers in
Bulgaria. These are CANDIDATES for ATS detection, not claims of coverage — the detection
tool (`python -m app.tools.detect_companies`) probes each one and only companies with a
live supported ATS board become active in the registry. Real companies only (owner rule).

Names are the employers' common public names; the list skips job boards and agencies.
"""

BG_COMPANIES = [
    "Accedia", "Adastra Bulgaria", "Astea Solutions", "Bosch Digital", "Broadcom Bulgaria",
    "Bulpros", "Chaos", "CloudCart", "Coursedot", "Devexperts", "DevriX", "Dopamine",
    "Dreamix", "DXC Technology Bulgaria", "EGT Digital", "Endava", "EnhanceV", "Experian",
    "Fadata", "FFW", "Financial Times Sofia", "Gtmhub", "Haemimont", "HedgeServ",
    "Hyperscience", "Imperia Online", "Infragistics", "KBC Global Services", "Leanplum",
    "LimeChain", "Luxoft Bulgaria", "MammothDB", "Melon", "MentorMate", "Milestone Systems",
    "Musala Soft", "Nemetschek Bulgaria", "Netcompany Bulgaria", "OfficeRnD", "Ontotext",
    "Payhawk", "Paysafe", "Paysera", "Playtech Bulgaria", "Progress", "Proxiad SEE",
    "Quantive", "ReceiptBank", "Reward Gateway", "SAP Labs Bulgaria", "ScaleFocus",
    "Schwarz IT Bulgaria", "SiteGround", "Sirma", "Software Group", "Strypes", "SumUp",
    "Sutherland Bulgaria", "Telebid Pro", "Telerik Academy", "Tide", "TINQIN",
    "Tumba Solutions", "Uber Bulgaria", "VMware Bulgaria", "Visteon Bulgaria", "Yettel",
    "A1 Bulgaria", "Vivacom", "DSK Bank", "UniCredit Bulbank",
]
