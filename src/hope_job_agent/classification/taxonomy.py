"""MSIS role and concentration taxonomy used for v0 job classification.

The concentration names below are the five official Kelley MSIS concentrations.
Legacy names from earlier sprints are preserved in
``LEGACY_CONCENTRATION_ALIASES`` so previously tagged source data and profiles
still classify into the current tracks without a data migration.
"""

MSIS_CONCENTRATIONS = [
    "Data Analytics and AI",
    "Cybersecurity and Risk Analytics",
    "Digital Enterprise Systems and AI",
    "Digital Platforms and Security",
    "IS Research",
]

# Short program codes for compact GCS-facing display. Full names remain the
# canonical tag values so outputs stay explainable without a lookup.
CONCENTRATION_CODES = {
    "Data Analytics and AI": "DA & AI",
    "Cybersecurity and Risk Analytics": "CRA",
    "Digital Enterprise Systems and AI": "DES & AI",
    "Digital Platforms and Security": "DPS",
    "IS Research": "ISR",
}

MSIS_TARGET_ROLES = [
    "IT Consultant / Tech Risk",
    "Data Analyst / BI Engineer",
    "Cybersecurity Analyst",
    "Product / Project Manager",
    "Software Engineer",
    "Other",
]

# Maps historical/alternate concentration names onto the current five tracks.
# Keys include prior sprint names, the older four-track canonical names, the
# short program codes, and common shorthand so older exports, fixtures,
# profiles, and source-provided tags keep classifying into the official names.
#
# These aliases are only ever applied to *explicit* concentration tags supplied
# by a source or profile (see ``normalize_concentration``). They are not used as
# free-text keyword rules, so intentionally broad shorthand such as "AI" or
# "Research" is safe here.
LEGACY_CONCENTRATION_ALIASES = {
    # --- Data Analytics and AI ---
    "Business Analytics": "Data Analytics and AI",
    "Business Intelligence and Analytics": "Data Analytics and AI",
    "Analytics": "Data Analytics and AI",
    "Data Analytics": "Data Analytics and AI",
    "AI": "Data Analytics and AI",
    "DAAI": "Data Analytics and AI",
    "DA & AI": "Data Analytics and AI",
    # --- Cybersecurity and Risk Analytics ---
    "Cybersecurity": "Cybersecurity and Risk Analytics",
    "Cyber Security": "Cybersecurity and Risk Analytics",
    "Security": "Cybersecurity and Risk Analytics",
    "Risk Analytics": "Cybersecurity and Risk Analytics",
    "CRA": "Cybersecurity and Risk Analytics",
    # --- Digital Enterprise Systems and AI ---
    "Digital Transformation with AI": "Digital Enterprise Systems and AI",
    "Digital Enterprise Systems": "Digital Enterprise Systems and AI",
    "Enterprise Systems": "Digital Enterprise Systems and AI",
    "IT Strategy / Consulting": "Digital Enterprise Systems and AI",
    "IT Strategy and Management": "Digital Enterprise Systems and AI",
    "DESAI": "Digital Enterprise Systems and AI",
    "DES & AI": "Digital Enterprise Systems and AI",
    "ERP": "Digital Enterprise Systems and AI",
    "SAP": "Digital Enterprise Systems and AI",
    "Enterprise AI": "Digital Enterprise Systems and AI",
    # --- Digital Platforms and Security ---
    "Digital Platforms": "Digital Platforms and Security",
    "Cloud Platforms": "Digital Platforms and Security",
    "Technology Architecture": "Digital Platforms and Security",
    "Platform Security": "Digital Platforms and Security",
    "Digital Innovation": "Digital Platforms and Security",
    "DPS": "Digital Platforms and Security",
    # --- IS Research ---
    "Information Systems Research in AI": "IS Research",
    "Information Systems Research": "IS Research",
    "IS Research in AI": "IS Research",
    "ISR": "IS Research",
    "Pre-PhD": "IS Research",
    "Research": "IS Research",
}

# Case-insensitive lookup that resolves official names, short codes, and legacy
# aliases onto the canonical official concentration name.
_CONCENTRATION_LOOKUP: dict[str, str] = {}
for _official in MSIS_CONCENTRATIONS:
    _CONCENTRATION_LOOKUP[_official.casefold()] = _official
for _code_name, _code in CONCENTRATION_CODES.items():
    _CONCENTRATION_LOOKUP[_code.casefold()] = _code_name
for _alias, _canonical in LEGACY_CONCENTRATION_ALIASES.items():
    _CONCENTRATION_LOOKUP.setdefault(_alias.casefold(), _canonical)


def normalize_concentration(value: str | None) -> str | None:
    """Return the official concentration name for a raw/legacy/coded value.

    Matching is case-insensitive and tolerant of surrounding whitespace. Returns
    ``None`` when the value cannot be mapped to one of the five official tracks,
    so callers can decide whether to drop or keep the unmapped tag.
    """

    if value is None:
        return None
    key = " ".join(str(value).split()).casefold()
    if not key:
        return None
    return _CONCENTRATION_LOOKUP.get(key)


def normalize_concentrations(values: list[str] | None) -> list[str]:
    """Normalize a list of concentration tags to official names, de-duplicated.

    Unmappable values are dropped. Output order follows the official taxonomy
    order so downstream exports stay stable and explainable.
    """

    if not values:
        return []
    resolved = {
        normalized
        for value in values
        if (normalized := normalize_concentration(value)) is not None
    }
    return [name for name in MSIS_CONCENTRATIONS if name in resolved]


ROLE_TO_CONCENTRATIONS = {
    "IT Consultant / Tech Risk": [
        "Digital Enterprise Systems and AI",
        "Cybersecurity and Risk Analytics",
    ],
    "Data Analyst / BI Engineer": [
        "Data Analytics and AI",
        "IS Research",
    ],
    "Cybersecurity Analyst": ["Cybersecurity and Risk Analytics"],
    "Product / Project Manager": ["Digital Enterprise Systems and AI"],
    "Software Engineer": ["Digital Enterprise Systems and AI"],
    "Other": [],
}

ROLE_KEYWORDS = {
    "IT Consultant / Tech Risk": [
        "it consultant",
        "technology consultant",
        "tech risk",
        "technology risk",
        "risk advisory",
        "it audit",
        "audit readiness",
        "compliance",
        "compliance assessments",
        "control gap",
        "process improvement",
        "business process",
        "erp consultant",
        "grc",
        "systems consultant",
        "vendor risk",
    ],
    "Data Analyst / BI Engineer": [
        "data analyst",
        "research analyst",
        "ai research analyst",
        "business analyst",
        "bi engineer",
        "business intelligence",
        "analytics engineer",
        "reporting analyst",
        "statistical modeling",
        "machine learning",
        "dashboard",
        "tableau",
        "power bi",
        "sql",
        "data visualization",
    ],
    "Cybersecurity Analyst": [
        "cybersecurity analyst",
        "security analyst",
        "cybersecurity",
        "information security",
        "infosec",
        "soc analyst",
        "siem",
        "splunk",
        "threat",
        "vulnerability",
        "nist",
        "grc",
    ],
    "Product / Project Manager": [
        "product manager",
        "product management",
        "product analysis",
        "project manager",
        "program manager",
        "product owner",
        "scrum master",
        "digital transformation",
        "workflow",
        "delivery",
        "agile",
        "business cases",
        "pmp",
        "roadmap",
        "rollout",
        "stakeholder management",
    ],
    "Software Engineer": [
        "software engineer",
        "software developer",
        "application developer",
        "engineering intern",
        "full stack",
        "frontend",
        "backend",
        "api",
        "java",
        "llm",
        "mcp server",
        "orchestration systems",
        "python developer",
        "cloud engineer",
        "devops",
        "software experience",
    ],
}

CONCENTRATION_KEYWORDS = {
    "Data Analytics and AI": [
        "data analytics",
        "analytics",
        "business intelligence",
        "machine learning",
        "ai",
        "sql",
        "python",
        "tableau",
        "power bi",
        "dashboard",
        "forecasting",
    ],
    "Cybersecurity and Risk Analytics": [
        "cybersecurity",
        "security",
        "risk management",
        "risk analytics",
        "operational risk",
        "fraud analytics",
        "threat",
        "vulnerability",
        "siem",
        "nist",
        "grc",
        "incident response",
    ],
    "Digital Enterprise Systems and AI": [
        "digital transformation",
        "ai transformation",
        "automation",
        "enterprise systems",
        "erp",
        "salesforce",
        "cloud",
        "customer experience",
        "customer success",
        "agile",
        "llm",
        "mcp",
        "product",
        "project",
        "consulting",
        "orchestration",
        "saas",
        "systems integration",
    ],
    "Digital Platforms and Security": [
        "platform engineering",
        "platform security",
        "digital platform",
        "identity and access",
        "identity management",
        "iam",
        "zero trust",
        "devsecops",
        "secure sdlc",
        "security engineering",
        "application security",
        "appsec",
        "api security",
        "cloud security",
        "container security",
        "kubernetes",
        "site reliability",
        "network security",
        "endpoint security",
        "iot",
        "secure architecture",
    ],
    "IS Research": [
        "research",
        "research analyst",
        "nlp",
        "natural language processing",
        "literature review",
        "experiment",
        "statistical modeling",
        "r",
        "machine learning",
        "ai",
    ],
}
