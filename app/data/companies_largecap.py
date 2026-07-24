"""Large-cap employer seeds sourced from national stock-market indices (the authoritative,
stable list of the biggest employers per country — DAX/CAC/IBEX/... constituents).

Goal (owner, 2026-07-24): >=1000 postings from big companies in larger economies, >=500 in
smaller ones. These index members are read via the DUAL path — identity-verified ATS
detection first, generic schema.org/JobPosting careers-page adapter as the fallback (most
large firms expose one or the other for Google for Jobs). Real companies only; a firm with
neither machine-readable path records an honest miss.

Provenance is in the section comments so the list is auditable and refreshable when an index
rebalances. `country` is ISO-3166 alpha-2. Entries dedup against the existing registry at
import time via the detection tool.
"""

LARGECAP_COMPANIES: list[dict] = [
    # ===== Germany — DAX 40 (the 40 largest listed German companies) =====
    {"name": "Adidas", "country": "DE", "industry": "Retail", "website": "https://www.adidas-group.com"},
    {"name": "Airbus", "country": "DE", "industry": "Aerospace", "website": "https://www.airbus.com"},
    {"name": "Allianz", "country": "DE", "industry": "Insurance", "website": "https://www.allianz.com"},
    {"name": "BASF", "country": "DE", "industry": "Manufacturing", "website": "https://www.basf.com"},
    {"name": "Bayer", "country": "DE", "industry": "Pharma", "website": "https://www.bayer.com"},
    {"name": "Beiersdorf", "country": "DE", "industry": "FMCG", "website": "https://www.beiersdorf.com"},
    {"name": "BMW Group", "country": "DE", "industry": "Automotive", "website": "https://www.bmwgroup.com"},
    {"name": "Brenntag", "country": "DE", "industry": "Distribution", "website": "https://www.brenntag.com"},
    {"name": "Commerzbank", "country": "DE", "industry": "Banking", "website": "https://www.commerzbank.com"},
    {"name": "Continental", "country": "DE", "industry": "Automotive", "website": "https://www.continental.com"},
    {"name": "Daimler Truck", "country": "DE", "industry": "Automotive", "website": "https://www.daimlertruck.com"},
    {"name": "Deutsche Bank", "country": "DE", "industry": "Banking", "website": "https://www.db.com"},
    {"name": "Deutsche Börse", "country": "DE", "industry": "Finance", "website": "https://www.deutsche-boerse.com"},
    {"name": "Deutsche Telekom", "country": "DE", "industry": "Telecom", "website": "https://www.telekom.com"},
    {"name": "E.ON", "country": "DE", "industry": "Energy", "website": "https://www.eon.com"},
    {"name": "Fresenius", "country": "DE", "industry": "Health", "website": "https://www.fresenius.com"},
    {"name": "Fresenius Medical Care", "country": "DE", "industry": "Health", "website": "https://www.freseniusmedicalcare.com"},
    {"name": "Hannover Re", "country": "DE", "industry": "Insurance", "website": "https://www.hannover-re.com"},
    {"name": "Heidelberg Materials", "country": "DE", "industry": "Manufacturing", "website": "https://www.heidelbergmaterials.com"},
    {"name": "Henkel", "country": "DE", "industry": "FMCG", "website": "https://www.henkel.com"},
    {"name": "Infineon", "country": "DE", "industry": "Semiconductors", "website": "https://www.infineon.com"},
    {"name": "Mercedes-Benz Group", "country": "DE", "industry": "Automotive", "website": "https://group.mercedes-benz.com"},
    {"name": "Merck KGaA", "country": "DE", "industry": "Pharma", "website": "https://www.merckgroup.com"},
    {"name": "MTU Aero Engines", "country": "DE", "industry": "Aerospace", "website": "https://www.mtu.de"},
    {"name": "Munich Re", "country": "DE", "industry": "Insurance", "website": "https://www.munichre.com"},
    {"name": "Porsche AG", "country": "DE", "industry": "Automotive", "website": "https://www.porsche.com"},
    {"name": "Qiagen", "country": "DE", "industry": "Health", "website": "https://www.qiagen.com"},
    {"name": "Rheinmetall", "country": "DE", "industry": "Manufacturing", "website": "https://www.rheinmetall.com"},
    {"name": "RWE", "country": "DE", "industry": "Energy", "website": "https://www.rwe.com"},
    {"name": "SAP", "country": "DE", "industry": "IT", "website": "https://www.sap.com"},
    {"name": "Sartorius", "country": "DE", "industry": "Health", "website": "https://www.sartorius.com"},
    {"name": "Siemens", "country": "DE", "industry": "Manufacturing", "website": "https://www.siemens.com"},
    {"name": "Siemens Energy", "country": "DE", "industry": "Energy", "website": "https://www.siemens-energy.com"},
    {"name": "Siemens Healthineers", "country": "DE", "industry": "Health", "website": "https://www.siemens-healthineers.com"},
    {"name": "Symrise", "country": "DE", "industry": "Manufacturing", "website": "https://www.symrise.com"},
    {"name": "Volkswagen Group", "country": "DE", "industry": "Automotive", "website": "https://www.volkswagen-group.com"},
    {"name": "Vonovia", "country": "DE", "industry": "Real Estate", "website": "https://www.vonovia.de"},
    {"name": "Zalando", "country": "DE", "industry": "E-commerce", "website": "https://corporate.zalando.com"},
    # ===== France — CAC 40 (the 40 largest listed French companies) =====
    {"name": "Air Liquide", "country": "FR", "industry": "Manufacturing", "website": "https://www.airliquide.com"},
    {"name": "Airbus Group", "country": "FR", "industry": "Aerospace", "website": "https://www.airbus.com"},
    {"name": "ArcelorMittal", "country": "FR", "industry": "Manufacturing", "website": "https://corporate.arcelormittal.com"},
    {"name": "AXA", "country": "FR", "industry": "Insurance", "website": "https://www.axa.com"},
    {"name": "BNP Paribas", "country": "FR", "industry": "Banking", "website": "https://group.bnpparibas"},
    {"name": "Bouygues", "country": "FR", "industry": "Construction", "website": "https://www.bouygues.com"},
    {"name": "Capgemini", "country": "FR", "industry": "IT", "website": "https://www.capgemini.com"},
    {"name": "Carrefour", "country": "FR", "industry": "Retail", "website": "https://www.carrefour.com"},
    {"name": "Crédit Agricole", "country": "FR", "industry": "Banking", "website": "https://www.credit-agricole.com"},
    {"name": "Danone", "country": "FR", "industry": "Food", "website": "https://www.danone.com"},
    {"name": "Dassault Systèmes", "country": "FR", "industry": "IT", "website": "https://www.3ds.com"},
    {"name": "Engie", "country": "FR", "industry": "Energy", "website": "https://www.engie.com"},
    {"name": "EssilorLuxottica", "country": "FR", "industry": "Manufacturing", "website": "https://www.essilorluxottica.com"},
    {"name": "Hermès", "country": "FR", "industry": "Retail", "website": "https://www.hermes.com"},
    {"name": "Kering", "country": "FR", "industry": "Retail", "website": "https://www.kering.com"},
    {"name": "Legrand", "country": "FR", "industry": "Manufacturing", "website": "https://www.legrand.com"},
    {"name": "L'Oréal", "country": "FR", "industry": "FMCG", "website": "https://www.loreal.com"},
    {"name": "LVMH", "country": "FR", "industry": "Retail", "website": "https://www.lvmh.com"},
    {"name": "Michelin", "country": "FR", "industry": "Manufacturing", "website": "https://www.michelin.com"},
    {"name": "Orange", "country": "FR", "industry": "Telecom", "website": "https://www.orange.com"},
    {"name": "Pernod Ricard", "country": "FR", "industry": "Food", "website": "https://www.pernod-ricard.com"},
    {"name": "Publicis Groupe", "country": "FR", "industry": "Media", "website": "https://www.publicisgroupe.com"},
    {"name": "Renault Group", "country": "FR", "industry": "Automotive", "website": "https://www.renaultgroup.com"},
    {"name": "Safran", "country": "FR", "industry": "Aerospace", "website": "https://www.safran-group.com"},
    {"name": "Saint-Gobain", "country": "FR", "industry": "Manufacturing", "website": "https://www.saint-gobain.com"},
    {"name": "Sanofi", "country": "FR", "industry": "Pharma", "website": "https://www.sanofi.com"},
    {"name": "Schneider Electric", "country": "FR", "industry": "Manufacturing", "website": "https://www.se.com"},
    {"name": "Société Générale", "country": "FR", "industry": "Banking", "website": "https://www.societegenerale.com"},
    {"name": "Stellantis", "country": "FR", "industry": "Automotive", "website": "https://www.stellantis.com"},
    {"name": "STMicroelectronics", "country": "FR", "industry": "Semiconductors", "website": "https://www.st.com"},
    {"name": "TotalEnergies", "country": "FR", "industry": "Energy", "website": "https://www.totalenergies.com"},
    {"name": "Thales", "country": "FR", "industry": "Aerospace", "website": "https://www.thalesgroup.com"},
    {"name": "Veolia", "country": "FR", "industry": "Utilities", "website": "https://www.veolia.com"},
    {"name": "Vinci", "country": "FR", "industry": "Construction", "website": "https://www.vinci.com"},
    {"name": "Worldline", "country": "FR", "industry": "Fintech", "website": "https://worldline.com"},
]

LARGECAP_COUNTRY_CODES = sorted({c["country"] for c in LARGECAP_COMPANIES})
