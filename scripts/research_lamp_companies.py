#!/usr/bin/env python3
"""Research and verify public ATS coverage for the ranked MSIS LAMP employers.

Non-runtime workflow tool. It:

1. Reads the MSIS LAMP list Excel workbook and ranks employers by
   ``Student Interest #`` (top N, default 300 = the full list).
2. Normalizes employer names to the canonical names used in
   ``config/company_careers.yml`` and collapses duplicate aliases (the best
   rank wins; merged ranks are recorded on the surviving row).
3. Optionally fetches each employer's public careers page (one GET) and
   detects ATS endpoint candidates (``discovery.detect_ats_candidates``).
4. Verifies curated/discovered candidates with at most ONE low-volume list
   request per provider/company (limit=1 where the API supports it).
5. Writes an auditable coverage report (JSON + Markdown) comparing the ranked
   list against the runtime config.

Compliance: public endpoints only, project User-Agent, rate limited, no login
or CAPTCHA/anti-bot circumvention. Failures are recorded, never retried
aggressively.

Usage (from repo root, inside the project venv):

    python scripts/research_lamp_companies.py \
        --excel data/lamp_list_2025_26.xlsx --top 300 --live

Use ``--min-rank`` to restrict live probing to a rank window (e.g.
``--min-rank 51`` when ranks 1-50 are already verified). Without ``--live``
the script only reads the Excel and the config and reports coverage gaps (no
network access).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from hope_job_agent.sources.company_careers.config import (  # noqa: E402
    load_company_careers_config,
)
from hope_job_agent.sources.company_careers.discovery import (  # noqa: E402
    detect_ats_candidates,
)
from hope_job_agent.sources.company_careers.http import (  # noqa: E402
    HttpClient,
    HttpError,
)

# Excel name -> canonical name used in config/company_careers.yml.
COMPANY_ALIASES: dict[str, str] = {
    "ey (ernst & young)": "EY",
    "pwc (pricewaterhousecoopers)": "PwC",
    "kpmg": "KPMG US",
    "microsoft corporation": "Microsoft",
    "meta platforms, inc.": "Meta",
    "nvidia corporation": "NVIDIA",
    "intel corporation": "Intel",
    "oracle corporation": "Oracle",
    "tesla, inc.": "Tesla",
    "netflix, inc.": "Netflix",
    "jpmorgan chase & co.": "JPMorgan Chase",
    "wipro limited": "Wipro",
    "boston consulting group (bcg)": "Boston Consulting Group",
    "toyota material handling north america (tmhna)": (
        "Toyota Material Handling North America"
    ),
    "salesforce": "Salesforce",
    "eli lilly and company": "Eli Lilly and Company",
    # Ranks 51-150.
    "w.w. grainger, inc.": "W.W. Grainger",
    "united airlines holdings, inc.": "United Airlines",
    "hp inc.": "HP Inc.",
    "hewlett packard": "Hewlett Packard Enterprise",
    "wells fargo & company": "Wells Fargo",
    "workday, inc.": "Workday",
    "target corporation": "Target",
    "uber technologies, inc.": "Uber",
    "ford motor company": "Ford",
    "walmart inc.": "Walmart",
    "tata consultancy services (tcs)": "Tata Consultancy Services",
    "tcs": "Tata Consultancy Services",
    "visa inc.": "Visa",
    "pfizer inc.": "Pfizer",
    "nike, inc.": "Nike",
    "optum (unitedhealth group)": "Optum",
    "slalom consulting": "Slalom",
    "morningstar, inc.": "Morningstar",
    "square": "Block",
    "zoom video communications": "Zoom",
    "notion labs, inc.": "Notion",
    "mcdonald's corporation": "McDonald's",
    # Ranks 151-300.
    "hewlett packard enterprise (hpe)": "Hewlett Packard Enterprise",
    "amazon web services (aws)": "Amazon Web Services",
    "slack (salesforce)": "Slack",
    "tableau software (salesforce)": "Tableau",
    "strategy& (part of pwc)": "Strategy&",
    "rtx corporation (formerly raytheon technologies)": "RTX Corporation",
    "rei (recreational equipment, inc.)": "REI",
    "total quality logistics (tql)": "Total Quality Logistics",
    "national football league (nfl)": "National Football League",
    "merck & co., inc.": "Merck",
    "honda motor co., ltd.": "Honda",
    "moderna, inc.": "Moderna",
    "f5, inc.": "F5",
    "lowe's companies, inc.": "Lowe's",
    "t-mobile us, inc.": "T-Mobile",
    "paypal holdings, inc.": "PayPal",
    "snap inc.": "Snap",
    "under armour, inc.": "Under Armour",
    "gap inc.": "Gap",
    "northern trust corporation": "Northern Trust",
    "rolls-royce holdings plc": "Rolls-Royce",
    "ubs group ag": "UBS",
    "the coca-cola company": "Coca-Cola",
    "verizon communications": "Verizon",
    "nucor corporation": "Nucor",
    "whirlpool corporation": "Whirlpool",
    "liberty mutual insurance": "Liberty Mutual",
    "discover financial services": "Discover",
    "elanco animal health": "Elanco",
    "micron technology": "Micron",
}

# Public careers pages used for discovery (one GET per company when --live).
CAREERS_PAGES: dict[str, str] = {
    "Deloitte": "https://apply.deloitte.com/",
    "EY": "https://careers.ey.com/",
    "PwC": "https://www.pwc.com/us/en/careers.html",
    "Accenture": "https://www.accenture.com/us-en/careers/jobsearch",
    "Amazon": "https://www.amazon.jobs/en/",
    "Google": "https://careers.google.com/",
    "KPMG US": "https://www.kpmguscareers.com/",
    "Microsoft": "https://careers.microsoft.com/",
    "IBM": "https://www.ibm.com/careers/search",
    "Salesforce": "https://careers.salesforce.com/",
    "Boston Consulting Group": "https://careers.bcg.com/",
    "McKinsey & Company": "https://www.mckinsey.com/careers/search-jobs",
    "Oracle": "https://careers.oracle.com/en/sites/jobsearch",
    "Bain & Company": "https://www.bain.com/careers/find-a-role/",
    "Apple": "https://jobs.apple.com/",
    "Eli Lilly and Company": "https://careers.lilly.com/us/en/search-results",
    "SAP": "https://jobs.sap.com/",
    "JPMorgan Chase": "https://careers.jpmorgan.com/us/en/search-results",
    "Meta": "https://www.metacareers.com/jobs",
    "Cognizant": "https://careers.cognizant.com/global-en/jobs/",
    "Crowe": "https://www.crowe.com/careers",
    "Infosys": "https://www.infosys.com/careers/",
    "Cisco": "https://jobs.cisco.com/",
    "Capgemini": "https://www.capgemini.com/careers/join-capgemini/job-search/",
    "Adobe": "https://careers.adobe.com/us/en/search-results",
    "NVIDIA": "https://www.nvidia.com/en-us/about-nvidia/careers/",
    "Intel": "https://jobs.intel.com/",
    "Grant Thornton": "https://www.grantthornton.com/careers",
    "ServiceNow": "https://careers.servicenow.com/careers/",
    "Bank of America": "https://careers.bankofamerica.com/en-us/job-search",
    "Protiviti": "https://www.protiviti.com/us-en/careers",
    "ZS Associates": "https://jobs.zs.com/",
    "Goldman Sachs": "https://higher.gs.com/roles",
    "Procter & Gamble": "https://www.pgcareers.com/global/en/search-results",
    "Tesla": "https://www.tesla.com/careers/search/",
    "Morgan Stanley": "https://www.morganstanley.com/careers/career-opportunities-search",
    "Dell Technologies": "https://jobs.dell.com/en/search-jobs",
    "Elevance Health": "https://careers.elevancehealth.com/en/jobs/",
    "Intuit": "https://jobs.intuit.com/search-jobs",
    "Netflix": "https://explore.jobs.netflix.net/careers",
    "Spotify": "https://www.lifeatspotify.com/jobs",
    "American Express": "https://aexp.eightfold.ai/careers",
    "FTI Consulting": "https://fticonsulting.wd1.myworkdayjobs.com/FTI_Consulting_Careers",
    "Johnson & Johnson": "https://www.careers.jnj.com/en/jobs/",
    "Citigroup": "https://jobs.citi.com/search-jobs",
    "Toyota Material Handling North America": "https://www.tmhnc.com/careers",
    "Wipro": "https://careers.wipro.com/careers-home/",
    "Epic Systems": "https://careers.epic.com/",
    "Cummins": "https://www.cummins.com/careers",
    "RSM US LLP": "https://rsmus.wd1.myworkdayjobs.com/RSMCareers",
    # Ranks 51-150.
    "W.W. Grainger": "https://jobs.grainger.com/",
    "West Monroe": "https://www.westmonroe.com/careers",
    "United Airlines": "https://careers.united.com/us/en/search-results",
    "Booz Allen Hamilton": "https://careers.boozallen.com/jobs/search",
    "Capital One": "https://www.capitalonecareers.com/search-jobs",
    "General Motors": "https://search-careers.gm.com/en/jobs/",
    "HP Inc.": "https://jobs.hp.com/",
    "Kearney": "https://www.kearney.com/careers",
    "Oliver Wyman": "https://careers.marshmclennan.com/global/en/oliver-wyman-search",
    "Wells Fargo": "https://www.wellsfargojobs.com/en/jobs/",
    "Workday": "https://workday.wd5.myworkdayjobs.com/Workday",
    "Abbott": "https://www.jobs.abbott/us/en/search-results",
    "AT&T": "https://www.att.jobs/search-jobs",
    "General Electric": "https://jobs.gecareers.com/global/en/search-results",
    "L.E.K. Consulting": "https://careers.lek.com/",
    "PepsiCo": "https://www.pepsicojobs.com/main/jobs",
    "Target": "https://corporate.target.com/careers/search",
    "Uber": "https://www.uber.com/us/en/careers/list/",
    "Ford": "https://efds.fa.em5.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1",
    "Genpact": "https://www.genpact.com/careers/job-search",
    "Guidehouse": "https://guidehouse.wd1.myworkdayjobs.com/External",
    "Huron Consulting Group": "https://careers.huronconsultinggroup.com/",
    "Walmart": "https://careers.walmart.com/results",
    "Bectran": "https://www.bectran.com/company/careers",
    "Bloomberg": "https://careers.bloomberg.com/job/search",
    "LinkedIn": "https://careers.linkedin.com/",
    "Samsung": "https://www.samsung.com/us/careers/",
    "Tata Consultancy Services": "https://www.tcs.com/careers",
    "The Walt Disney Company": "https://www.disneycareers.com/en/search-jobs",
    "Baker Tilly": "https://careers.bakertilly.com/",
    "Boeing": "https://jobs.boeing.com/search-jobs",
    "CrowdStrike": "https://www.crowdstrike.com/careers/",
    "Nike": "https://careers.nike.com/",
    "Pfizer": "https://www.pfizer.com/about/careers",
    "AbbVie": "https://careers.abbvie.com/en/search-jobs",
    "American Airlines": "https://jobs.aa.com/search-jobs",
    "CGI": "https://www.cgi.com/en/careers",
    "CVS Health": "https://jobs.cvshealth.com/us/en/search-results",
    "Delta Air Lines": "https://careers.delta.com/careers",
    "HubSpot": "https://www.hubspot.com/careers/jobs",
    "Slalom": "https://www.slalom.com/us/en/careers/find-a-role",
    "Snowflake": "https://careers.snowflake.com/us/en/search-results",
    "Walgreens Boots Alliance": "https://jobs.walgreens.com/en/search-jobs",
    "Allstate": "https://www.allstate.jobs/search-jobs/",
    "BDO": "https://www.bdo.com/careers",
    "Caterpillar": "https://careers.caterpillar.com/en/jobs/",
    "Comcast": "https://jobs.comcast.com/search-jobs",
    "Gartner": "https://jobs.gartner.com/jobs/",
    "HSBC": "https://mycareer.hsbc.com/en_GB/external",
    "Optum": "https://careers.unitedhealthgroup.com/job-search-results/",
    "Philips Healthcare": "https://www.careers.philips.com/global/en/search-results",
    "Publicis Sapient": "https://careers.publicissapient.com/jobs",
    "Roland Berger": "https://rolandberger.jobs/",
    "Siemens": "https://jobs.siemens.com/careers",
    "Atlassian": "https://www.atlassian.com/company/careers/all-jobs",
    "Atos": "https://atos.net/en/join-us",
    "Boston Scientific": "https://careers.bostonscientific.com/",
    "DHL": "https://careers.dhl.com/global/en/search-results",
    "GE HealthCare": "https://careers.gehealthcare.com/global/en/search-results",
    "Honeywell": "https://careers.honeywell.com/us/en/search-results",
    "IU Health": "https://careers.iuhealth.org/",
    "LTIMindtree": "https://www.ltimindtree.com/careers/",
    "Medtronic": "https://jobs.medtronic.com/search-jobs",
    "Morningstar": "https://careers.morningstar.com/us/en",
    "Nestle": "https://www.nestlejobs.com/search-jobs",
    "Roche Diagnostics": "https://careers.roche.com/global/en/search-results",
    "Block": "https://block.xyz/careers/jobs",
    "Unilever": "https://careers.unilever.com/global/en/search-results",
    "UnitedHealth Group": "https://careers.unitedhealthgroup.com/job-search-results/",
    "Zoom": "https://careers.zoom.us/jobs/search",
    "ADM": "https://www.adm.com/en-us/culture-and-careers/",
    "AlixPartners": "https://www.alixpartners.com/careers/",
    "Alvarez & Marsal": "https://www.alvarezandmarsal.com/careers",
    "Avanade": "https://www.avanade.com/en-us/career/job-search",
    "Barclays": "https://search.jobs.barclays/",
    "Baxter": "https://jobs.baxter.com/search-jobs",
    "BMO Financial Group": "https://jobs.bmo.com/ca/en/search-results",
    "CDW": "https://www.cdwjobs.com/",
    "Costco": "https://www.costco.com/jobs.html",
    "EPAM Systems": "https://www.epam.com/careers/job-listings",
    "Fidelity Investments": "https://jobs.fidelity.com/",
    "FIS Global": "https://careers.fisglobal.com/us/en/search-results",
    "Genesys": "https://careers.genesys.com/",
    "Hewlett Packard Enterprise": "https://careers.hpe.com/us/en/search-results",
    "Humana": "https://careers.humana.com/",
    "IQVIA": "https://jobs.iqvia.com/en/search-jobs",
    "Lenovo": "https://jobs.lenovo.com/en_US/careers",
    "Lockheed Martin": "https://www.lockheedmartinjobs.com/search-jobs",
    "Lyft": "https://www.lyft.com/careers",
    "McDonald's": "https://careers.mcdonalds.com/",
    "Medline Industries": "https://www.medline.com/careers/",
    # Ranks 151-300.
    "NTT DATA": "https://careers.services.global.ntt/",
    "Palo Alto Networks": "https://jobs.paloaltonetworks.com/en/",
    "Sony": "https://www.sony.com/en/SonyInfo/Careers/",
    "Stryker": "https://careers.stryker.com/",
    "Thoughtworks": "https://www.thoughtworks.com/careers/jobs",
    "TikTok": "https://lifeattiktok.com/search",
    "Verizon": "https://mycareer.verizon.com/jobs/",
    "AlphaSights": "https://www.alphasights.com/careers/open-positions/",
    "AMD": "https://careers.amd.com/careers-home",
    "Amgen": "https://careers.amgen.com/en",
    "Anthropic": "https://www.anthropic.com/careers",
    "Aon": "https://jobs.aon.com/",
    "Asana": "https://asana.com/jobs/all",
    "BlackRock": "https://careers.blackrock.com/",
    "Cardinal Health": "https://jobs.cardinalhealth.com/search",
    "Charles Schwab": "https://www.schwabjobs.com/",
    "Cigna": "https://jobs.thecignagroup.com/us/en",
    "CohnReznick": "https://www.cohnreznick.com/careers",
    "Discover": "https://jobs.discover.com/",
    "Figma": "https://www.figma.com/careers/",
    "Fortinet": "https://www.fortinet.com/corporate/careers",
    "Forvis": "https://careers.forvismazars.us/",
    "Hitachi Vantara": "https://www.hitachivantara.com/en-us/company/careers",
    "Honda": "https://careers.honda.com/",
    "Korn Ferry": "https://www.kornferry.com/about-us/careers",
    "Kroger": "https://jobs.kroger.com/",
    "Leidos": "https://careers.leidos.com/search/jobs",
    "Liberty Mutual": "https://jobs.libertymutualgroup.com/search-jobs/",
    "Mayo Clinic": "https://jobs.mayoclinic.org/search-jobs",
    "Merck": "https://jobs.merck.com/us/en/search-results",
    "NBCUniversal": "https://www.nbcunicareers.com/find-a-job",
    "NielsenIQ": "https://nielseniq.com/global/en/careers/",
    "Northern Trust": "https://careers.northerntrust.com/",
    "Novartis": "https://www.novartis.com/careers",
    "OC&C Strategy Consultants": "https://www.occstrategy.com/en/careers/",
    "Persistent Systems": "https://www.persistent.com/careers/",
    "Pinterest": "https://www.pinterestcareers.com/jobs/",
    "Plante Moran": "https://www.plantemoran.com/explore-our-firm/careers",
    "Republic Airways": "https://www.rjet.com/careers",
    "Rolls-Royce": "https://careers.rolls-royce.com/usa",
    "Shopify": "https://www.shopify.com/careers",
    "Simon-Kucher": "https://www.simon-kucher.com/en/careers",
    "State Farm": "https://jobs.statefarm.com/main/",
    "T-Mobile": "https://careers.t-mobile.com/job-search/",
    "TD Bank Group": "https://jobs.td.com/en/",
    "Coca-Cola": "https://careers.coca-colacompany.com/",
    "The Home Depot": "https://careers.homedepot.com/",
    "UBS": "https://jobs.ubs.com/",
    "Uline": "https://www.uline.jobs/",
    "Vanguard": "https://www.vanguardjobs.com/",
    "3M": "https://www.3m.com/3M/en_US/careers-us/",
    "Airtable": "https://airtable.com/careers",
    "Alibaba": "https://talent.alibaba.com/",
    "Altria": "https://www.altria.com/careers",
    "Amazon Web Services": "https://aws.amazon.com/careers/",
    "AMEND Consulting": "https://amendllc.com/careers/",
    "ASML": "https://www.asml.com/en/careers",
    "Atrium Health": "https://careers.atriumhealth.org/",
    "Audi": "https://www.audiusa.com/us/web/en/about/careers.html",
    "Avant": "https://www.avant.com/careers/",
    "BearingPoint": "https://www.bearingpoint.com/en/careers/",
    "Biogen": "https://careers.biogen.com/",
    "Blue Cross Blue Shield": "https://www.bcbs.com/careers",
    "BNY Mellon": "https://www.bny.com/corporate/global/en/careers.html",
    "Boston Red Sox": "https://www.mlb.com/redsox/team/jobs",
    "Box": "https://www.box.com/careers",
    "Broadcom": "https://www.broadcom.com/company/careers",
    "Bunzl": "https://careers.bunzldistribution.com/",
    "Canva": "https://www.lifeatcanva.com/en/jobs/",
    "CBRE": "https://careers.cbre.com/en_US/careers",
    "Cerner": "https://www.oracle.com/health/careers/",
    "Chevrolet": "https://search-careers.gm.com/en/jobs/",
    "Cintas": "https://careers.cintas.com/",
    "Clarkston Consulting": "https://clarkstonconsulting.com/careers/",
    "Cleveland Clinic": "https://jobs.clevelandclinic.org/",
    "Cook Medical": "https://www.cookmedical.com/careers/",
    "Credera": "https://www.credera.com/careers",
    "DoorDash": "https://careersatdoordash.com/",
    "Duolingo": "https://careers.duolingo.com/",
    "DXC Technology": "https://careers.dxc.com/global/en",
    "eBay": "https://jobs.ebayinc.com/us/en",
    "Elanco": "https://careers.elanco.com/us/en",
    "EXL Service": "https://www.exlservice.com/careers",
    "ExxonMobil": "https://jobs.exxonmobil.com/",
    "F5": "https://www.f5.com/company/careers",
    "Fischer Homes": "https://www.fischerhomes.com/careers/",
    "Formstack": "https://www.formstack.com/careers",
    "Fractal Analytics": "https://fractal.ai/careers/",
    "Gap": "https://www.gapinc.com/en-us/careers",
    "Globant": "https://www.globant.com/careers",
    "Grubhub": "https://careers.grubhub.com/",
    "Health Catalyst": "https://www.healthcatalyst.com/careers",
    "HealthScape Advisors": "https://healthscape.com/careers/",
    "Hexaware Technologies": "https://hexaware.com/careers/",
    "Hitachi Consulting": "https://www.hitachivantara.com/en-us/company/careers",
    "Infor": "https://www.infor.com/about/careers",
    "Insight Global": "https://jobs.insightglobal.com/",
    "John Hancock": "https://careers.manulife.com/global/en/john-hancock",
    "Kroll": "https://careers.kroll.com/",
    "Logitech": "https://jobs.jobvite.com/logitech/",
    "Lowe's": "https://talent.lowes.com/us/en",
    "Lumen Technologies": "https://jobs.lumen.com/global/en",
    "Marsh McLennan": "https://careers.marshmclennan.com/global/en/search-results",
    "Micron": "https://careers.micron.com/careers",
    "Moderna": "https://www.modernatx.com/careers/",
    "National Football League": "https://www.nfl.com/careers/",
    "New Balance": "https://jobs.newbalance.com/",
    "Nucor": "https://careers.nucor.com/",
    "Nutanix": "https://careers.nutanix.com/en",
    "Okta": "https://www.okta.com/company/careers/",
    "PayPal": "https://careers.pypl.com/home/",
    "Perficient": "https://www.perficient.com/careers",
    "PNC Financial Services": "https://careers.pnc.com/global/en",
    "Premier Irrigation Adritec Pvt Ltd": "https://www.premierirrigation.com/",
    "Publicis Groupe": "https://www.publicisgroupe.com/en/careers",
    "RBW Consulting": "https://rbwconsulting.com/careers/",
    "Red Hat": "https://www.redhat.com/en/jobs",
    "REI": "https://rei.jobs/",
    "Resultant": "https://resultant.com/careers/",
    "Riot Games": "https://www.riotgames.com/en/work-with-us/jobs",
    "Rippling": "https://www.rippling.com/careers",
    "RTX Corporation": "https://careers.rtx.com/global/en/search-results",
    "Schneider Electric": "https://www.se.com/us/en/about-us/careers/overview.jsp",
    "Slack": "https://slack.com/careers",
    "Snap": "https://careers.snap.com/jobs",
    "Splunk": "https://www.splunk.com/en_us/careers/search-jobs.html",
    "Sprinklr": "https://www.sprinklr.com/careers/",
    "Strategy&": "https://www.strategyand.pwc.com/gx/en/careers.html",
    "Synergy Consulting": "https://synergyconsulting.ai/careers",
    "Synergy Works Group": "https://www.synergyworksgroup.com/",
    "Tableau": "https://careers.salesforce.com/en/jobs/",
    "Teladoc Health": "https://teladochealth.com/careers/",
    "The Hershey Company": "https://careers.thehersheycompany.com/",
    "The Kraft Heinz Company": "https://careers.kraftheinz.com/",
    "Total Quality Logistics": "https://www.tql.com/careers",
    "Toyota Motor Corporation": "https://www.toyota.com/usa/careers/",
    "U.S. Bank": "https://careers.usbank.com/global/en/search-results",
    "Ulta Beauty": "https://careers.ulta.com/careers/",
    "Under Armour": "https://careers.underarmour.com/",
    "Veeva Systems": "https://careers.veeva.com/",
    "Virtusa": "https://www.virtusa.com/careers",
    "VMware": "https://www.broadcom.com/company/careers",
    "Warner Bros. Discovery": "https://careers.wbd.com/global/en/search-results",
    "Whirlpool": "https://www.whirlpoolcareers.com/",
    "William Blair": "https://www.williamblair.com/Careers",
    "Zoho Corporation": "https://www.zoho.com/careers.html",
}

# Curated endpoint candidates to verify directly (skips brittle discovery).
# provider -> fields consumed by the matching verifier below.
CURATED_CANDIDATES: dict[str, list[dict[str, str]]] = {
    "ServiceNow": [{"provider": "smartrecruiters", "slug": "ServiceNow"}],
    "Mastercard": [
        {
            "provider": "workday",
            "host": "mastercard.wd1.myworkdayjobs.com",
            "tenant": "mastercard",
            "site": "CorporateCareers",
        }
    ],
    "Eli Lilly and Company": [
        {
            "provider": "workday",
            "host": "lilly.wd115.myworkdayjobs.com",
            "tenant": "lilly",
            "site": "LLY",
        }
    ],
    "Salesforce": [
        {
            "provider": "workday",
            "host": "salesforce.wd12.myworkdayjobs.com",
            "tenant": "salesforce",
            "site": "External_Career_Site",
        }
    ],
    "Adobe": [
        {
            "provider": "workday",
            "host": "adobe.wd5.myworkdayjobs.com",
            "tenant": "adobe",
            "site": "external_experienced",
        }
    ],
    "NVIDIA": [
        {
            "provider": "workday",
            "host": "nvidia.wd5.myworkdayjobs.com",
            "tenant": "nvidia",
            "site": "NVIDIAExternalCareerSite",
        }
    ],
    "Intel": [
        {
            "provider": "workday",
            "host": "intel.wd1.myworkdayjobs.com",
            "tenant": "intel",
            "site": "External",
        }
    ],
    "PwC": [
        {
            "provider": "workday",
            "host": "pwc.wd3.myworkdayjobs.com",
            "tenant": "pwc",
            "site": "Global_Experienced_Careers",
        }
    ],
    "Elevance Health": [
        {
            "provider": "workday",
            "host": "elevancehealth.wd1.myworkdayjobs.com",
            "tenant": "elevancehealth",
            "site": "ANT",
        }
    ],
    "Citigroup": [
        {
            "provider": "workday",
            "host": "citi.wd5.myworkdayjobs.com",
            "tenant": "citi",
            "site": "2",
        }
    ],
    "RSM US LLP": [
        {
            "provider": "workday",
            "host": "rsmus.wd1.myworkdayjobs.com",
            # Confirmed 2026-07-08: tenant is "rsm", not the host prefix.
            "tenant": "rsm",
            "site": "RSMCareers",
        }
    ],
    "Accenture": [
        {
            "provider": "workday",
            "host": "accenture.wd103.myworkdayjobs.com",
            "tenant": "accenture",
            "site": "AccentureCareers",
        }
    ],
    "Grant Thornton": [
        {
            "provider": "oraclecloud",
            "host": "ehzq.fa.us2.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "Procter & Gamble": [
        {
            "provider": "workday",
            "host": "pg.wd5.myworkdayjobs.com",
            "tenant": "pg",
            "site": "1000",
        }
    ],
    "Protiviti": [
        {
            "provider": "workday",
            "host": "roberthalf.wd1.myworkdayjobs.com",
            "tenant": "roberthalf",
            "site": "ProtivitiNA",
        }
    ],
    "Johnson & Johnson": [
        {
            "provider": "workday",
            "host": "jj.wd5.myworkdayjobs.com",
            "tenant": "jj",
            "site": "JJ",
        }
    ],
    "American Express": [
        {
            "provider": "oraclecloud",
            "host": "egug.fa.us2.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "FTI Consulting": [
        {
            "provider": "workday",
            "host": "fticonsulting.wd1.myworkdayjobs.com",
            "tenant": "fticonsulting",
            "site": "FTI_Consulting_Careers",
        }
    ],
    "Crowe": [
        {
            "provider": "workday",
            "host": "crowe.wd12.myworkdayjobs.com",
            "tenant": "crowe",
            "site": "External_Careers",
        }
    ],
    "Cognizant": [
        {
            # Confirmed host, but the cxs endpoint returns 401 for
            # unauthenticated requests; kept for future re-checks.
            "provider": "workday",
            "host": "cognizant.wd3.myworkdayjobs.com",
            "tenant": "cognizant",
            "site": "CognizantCareers",
        }
    ],
    "JPMorgan Chase": [
        {
            "provider": "oraclecloud",
            "host": "jpmc.fa.oraclecloud.com",
            "site": "CX_1001",
        }
    ],
    "Oracle": [
        {
            "provider": "oraclecloud",
            "host": "eeho.fa.us2.oraclecloud.com",
            "site": "CX_45001",
        },
        {
            "provider": "oraclecloud",
            "host": "eeho.fa.us2.oraclecloud.com",
            "site": "CX_1",
        },
    ],
    "Netflix": [{"provider": "lever", "slug": "netflix"}],
    "Spotify": [{"provider": "lever", "slug": "spotify"}],
    "Deloitte": [{"provider": "smartrecruiters", "slug": "DeloitteUS"}],
    # Ranks 51-150 candidates (verified with one list request each when --live).
    "Workday": [
        {
            "provider": "workday",
            "host": "workday.wd5.myworkdayjobs.com",
            "tenant": "workday",
            "site": "Workday",
        }
    ],
    "Capital One": [
        {
            "provider": "workday",
            "host": "capitalone.wd12.myworkdayjobs.com",
            "tenant": "capitalone",
            "site": "Capital_One",
        },
        {
            "provider": "workday",
            "host": "capitalone.wd1.myworkdayjobs.com",
            "tenant": "capitalone",
            "site": "Capital_One",
        },
    ],
    "General Motors": [
        {
            "provider": "workday",
            "host": "generalmotors.wd5.myworkdayjobs.com",
            "tenant": "generalmotors",
            "site": "Careers_GM",
        }
    ],
    "Wells Fargo": [
        {
            "provider": "workday",
            "host": "wd1.myworkdayjobs.com",
            "tenant": "wellsfargo",
            "site": "WellsFargoJobs",
        }
    ],
    "Abbott": [
        {
            "provider": "workday",
            "host": "abbott.wd5.myworkdayjobs.com",
            "tenant": "abbott",
            "site": "abbottcareers",
        }
    ],
    "Target": [
        {
            "provider": "workday",
            "host": "target.wd5.myworkdayjobs.com",
            "tenant": "target",
            "site": "targetcareers",
        }
    ],
    "Walmart": [
        {
            "provider": "workday",
            "host": "walmart.wd5.myworkdayjobs.com",
            "tenant": "walmart",
            "site": "WalmartExternal",
        }
    ],
    "CrowdStrike": [
        {
            "provider": "workday",
            "host": "crowdstrike.wd5.myworkdayjobs.com",
            "tenant": "crowdstrike",
            "site": "crowdstrikecareers",
        }
    ],
    "Allstate": [
        {
            "provider": "workday",
            "host": "allstate.wd5.myworkdayjobs.com",
            "tenant": "allstate",
            "site": "allstate_careers",
        }
    ],
    "Gartner": [
        {
            "provider": "workday",
            "host": "gartner.wd5.myworkdayjobs.com",
            "tenant": "gartner",
            "site": "EXT",
        }
    ],
    "Medtronic": [
        {
            "provider": "workday",
            "host": "medtronic.wd1.myworkdayjobs.com",
            "tenant": "medtronic",
            "site": "MedtronicCareers",
        }
    ],
    "Morningstar": [
        {
            "provider": "workday",
            "host": "morningstar.wd5.myworkdayjobs.com",
            "tenant": "morningstar",
            "site": "Americas",
        }
    ],
    "Zoom": [
        {
            "provider": "workday",
            "host": "zoom.wd5.myworkdayjobs.com",
            "tenant": "zoom",
            "site": "Zoom",
        }
    ],
    "FIS Global": [
        {
            "provider": "workday",
            "host": "fis.wd5.myworkdayjobs.com",
            "tenant": "fis",
            "site": "SearchJobs",
        }
    ],
    "Genesys": [
        {
            "provider": "workday",
            "host": "genesys.wd1.myworkdayjobs.com",
            "tenant": "genesys",
            "site": "Genesys",
        }
    ],
    "IQVIA": [
        {
            "provider": "workday",
            "host": "iqvia.wd1.myworkdayjobs.com",
            "tenant": "iqvia",
            "site": "IQVIA",
        }
    ],
    "United Airlines": [
        {
            "provider": "workday",
            "host": "united.wd1.myworkdayjobs.com",
            "tenant": "united",
            "site": "External",
        }
    ],
    "Booz Allen Hamilton": [
        {
            "provider": "workday",
            "host": "bah.wd1.myworkdayjobs.com",
            "tenant": "bah",
            "site": "BAH_Jobs",
        }
    ],
    "Oliver Wyman": [
        {
            "provider": "workday",
            "host": "mmc.wd1.myworkdayjobs.com",
            "tenant": "mmc",
            "site": "MMC",
        }
    ],
    "Guidehouse": [
        {
            "provider": "workday",
            "host": "guidehouse.wd1.myworkdayjobs.com",
            "tenant": "guidehouse",
            "site": "External",
        }
    ],
    "Huron Consulting Group": [
        {
            "provider": "workday",
            "host": "huron.wd1.myworkdayjobs.com",
            "tenant": "huron",
            "site": "External",
        }
    ],
    "Boeing": [
        {
            "provider": "workday",
            "host": "boeing.wd1.myworkdayjobs.com",
            "tenant": "boeing",
            "site": "EXTERNAL_CAREERS",
        }
    ],
    "Pfizer": [
        {
            "provider": "workday",
            "host": "pfizer.wd1.myworkdayjobs.com",
            "tenant": "pfizer",
            "site": "PfizerCareers",
        }
    ],
    "AbbVie": [
        {
            "provider": "workday",
            "host": "abbvie.wd5.myworkdayjobs.com",
            "tenant": "abbvie",
            "site": "External",
        }
    ],
    "CVS Health": [
        {
            "provider": "workday",
            "host": "cvshealth.wd1.myworkdayjobs.com",
            "tenant": "cvshealth",
            "site": "CVS_Health_Careers",
        }
    ],
    "Comcast": [
        {
            "provider": "workday",
            "host": "comcast.wd5.myworkdayjobs.com",
            "tenant": "comcast",
            "site": "Comcast_Careers",
        }
    ],
    "Philips Healthcare": [
        {
            "provider": "workday",
            "host": "philips.wd3.myworkdayjobs.com",
            "tenant": "philips",
            "site": "jobs-and-careers",
        }
    ],
    "Boston Scientific": [
        {
            "provider": "workday",
            "host": "bsci.wd5.myworkdayjobs.com",
            "tenant": "bsci",
            "site": "External",
        }
    ],
    "Avanade": [
        {
            "provider": "workday",
            "host": "avanade.wd3.myworkdayjobs.com",
            "tenant": "avanade",
            "site": "AvanadeCareers",
        }
    ],
    "Baxter": [
        {
            "provider": "workday",
            "host": "baxter.wd1.myworkdayjobs.com",
            "tenant": "baxter",
            "site": "External",
        }
    ],
    "BMO Financial Group": [
        {
            "provider": "workday",
            "host": "bmo.wd3.myworkdayjobs.com",
            "tenant": "bmo",
            "site": "External",
        }
    ],
    "CDW": [
        {
            "provider": "workday",
            "host": "cdw.wd1.myworkdayjobs.com",
            "tenant": "cdw",
            "site": "External",
        }
    ],
    "Humana": [
        {
            "provider": "workday",
            "host": "humana.wd5.myworkdayjobs.com",
            "tenant": "humana",
            "site": "Humana_External_Career_Site",
        }
    ],
    "Medline Industries": [
        {
            "provider": "workday",
            "host": "medline.wd1.myworkdayjobs.com",
            "tenant": "medline",
            "site": "Medline",
        }
    ],
    "HP Inc.": [
        {
            "provider": "workday",
            "host": "hp.wd5.myworkdayjobs.com",
            "tenant": "hp",
            "site": "ExternalCareerSite",
        }
    ],
    "Hewlett Packard Enterprise": [
        {
            "provider": "workday",
            "host": "hpe.wd5.myworkdayjobs.com",
            "tenant": "hpe",
            "site": "Jobsathpe",
        }
    ],
    "Nike": [
        {
            "provider": "workday",
            "host": "nike.wd1.myworkdayjobs.com",
            "tenant": "nike",
            "site": "nikecareers",
        }
    ],
    "W.W. Grainger": [
        {
            "provider": "workday",
            "host": "grainger.wd1.myworkdayjobs.com",
            "tenant": "grainger",
            "site": "External",
        }
    ],
    "Walgreens Boots Alliance": [
        {
            "provider": "workday",
            "host": "wba.wd3.myworkdayjobs.com",
            "tenant": "wba",
            "site": "External",
        }
    ],
    "Ford": [
        {
            "provider": "oraclecloud",
            "host": "efds.fa.em5.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "Lyft": [{"provider": "greenhouse", "slug": "lyft"}],
    "Atlassian": [{"provider": "greenhouse", "slug": "atlassian"}],
    "HubSpot": [{"provider": "greenhouse", "slug": "hubspot"}],
    "Block": [
        {"provider": "greenhouse", "slug": "block"},
        {"provider": "greenhouse", "slug": "square"},
    ],
    "West Monroe": [
        {"provider": "greenhouse", "slug": "westmonroe"},
        {"provider": "greenhouse", "slug": "westmonroepartners"},
    ],
    "Snowflake": [{"provider": "ashby", "slug": "snowflake"}],
    # Oracle CE hosts discovered from careers pages; CX_1 confirmed 2026-07-08.
    "Uber": [
        {
            "provider": "oraclecloud",
            "host": "iaziqy.fa.ocs.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "BDO": [
        {
            "provider": "oraclecloud",
            "host": "ebqb.fa.us2.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "Honeywell": [
        {
            "provider": "oraclecloud",
            "host": "ibqbjb.fa.ocs.oraclecloud.com",
            "site": "CX_1",
        }
    ],
    "Bectran": [
        {"provider": "greenhouse", "slug": "bectran"},
        {"provider": "lever", "slug": "bectran"},
    ],
    # Ranks 151-300 candidates.
    "Anthropic": [{"provider": "greenhouse", "slug": "anthropic"}],
    "Pinterest": [{"provider": "greenhouse", "slug": "pinterest"}],
    "Figma": [{"provider": "greenhouse", "slug": "figma"}],
    "Asana": [{"provider": "greenhouse", "slug": "asana"}],
    "Duolingo": [{"provider": "greenhouse", "slug": "duolingo"}],
    "Okta": [{"provider": "greenhouse", "slug": "okta"}],
    "Rippling": [{"provider": "greenhouse", "slug": "rippling"}],
    "Airtable": [{"provider": "greenhouse", "slug": "airtable"}],
    "Riot Games": [{"provider": "greenhouse", "slug": "riotgames"}],
    "Avant": [{"provider": "greenhouse", "slug": "avant"}],
    "AlphaSights": [{"provider": "greenhouse", "slug": "alphasights"}],
    "Moderna": [{"provider": "greenhouse", "slug": "modernatx"}],
    "DoorDash": [
        {"provider": "greenhouse", "slug": "doordashusa"},
        {"provider": "greenhouse", "slug": "doordash"},
    ],
    "Box": [{"provider": "greenhouse", "slug": "boxinc"}],
    "Grubhub": [{"provider": "greenhouse", "slug": "grubhubholdings"}],
    "Health Catalyst": [{"provider": "greenhouse", "slug": "healthcatalyst"}],
    "Thoughtworks": [{"provider": "greenhouse", "slug": "thoughtworks"}],
    "Teladoc Health": [{"provider": "greenhouse", "slug": "teladochealth"}],
    "Shopify": [{"provider": "greenhouse", "slug": "shopify"}],
    "Veeva Systems": [{"provider": "lever", "slug": "veeva"}],
    "Canva": [{"provider": "lever", "slug": "canva"}],
    "Palo Alto Networks": [
        {"provider": "smartrecruiters", "slug": "PaloAltoNetworks2"}
    ],
    "AMD": [
        {
            "provider": "workday",
            "host": "amd.wd1.myworkdayjobs.com",
            "tenant": "amd",
            "site": "External",
        }
    ],
    "Micron": [
        {
            "provider": "workday",
            "host": "micron.wd1.myworkdayjobs.com",
            "tenant": "micron",
            "site": "External",
        }
    ],
    "Fortinet": [
        {
            "provider": "workday",
            "host": "fortinet.wd1.myworkdayjobs.com",
            "tenant": "fortinet",
            "site": "FortinetCareers",
        }
    ],
    "Leidos": [
        {
            "provider": "workday",
            "host": "leidos.wd5.myworkdayjobs.com",
            "tenant": "leidos",
            "site": "External",
        }
    ],
    "T-Mobile": [
        {
            "provider": "workday",
            "host": "tmobileusa.wd1.myworkdayjobs.com",
            "tenant": "tmobileusa",
            "site": "External",
        }
    ],
    "PayPal": [
        {
            "provider": "workday",
            "host": "paypal.wd1.myworkdayjobs.com",
            "tenant": "paypal",
            "site": "jobs",
        }
    ],
    "eBay": [
        {
            "provider": "workday",
            "host": "ebayinc.wd5.myworkdayjobs.com",
            "tenant": "ebayinc",
            "site": "apply",
        }
    ],
    "Broadcom": [
        {
            "provider": "workday",
            "host": "broadcom.wd1.myworkdayjobs.com",
            "tenant": "broadcom",
            "site": "External_Career",
        }
    ],
    "Red Hat": [
        {
            "provider": "workday",
            "host": "redhat.wd5.myworkdayjobs.com",
            "tenant": "redhat",
            "site": "jobs",
        }
    ],
    "Stryker": [
        {
            "provider": "workday",
            "host": "stryker.wd1.myworkdayjobs.com",
            "tenant": "stryker",
            "site": "StrykerCareers",
        }
    ],
    "Cardinal Health": [
        {
            "provider": "workday",
            "host": "cardinalhealth.wd1.myworkdayjobs.com",
            "tenant": "cardinalhealth",
            "site": "EXT",
        }
    ],
    "Cigna": [
        {
            "provider": "workday",
            "host": "cigna.wd5.myworkdayjobs.com",
            "tenant": "cigna",
            "site": "cignacareers",
        }
    ],
    "Merck": [
        {
            "provider": "workday",
            "host": "merck.wd5.myworkdayjobs.com",
            "tenant": "merck",
            "site": "SearchJobs",
        }
    ],
    "BlackRock": [
        {
            "provider": "workday",
            "host": "blackrock.wd1.myworkdayjobs.com",
            "tenant": "blackrock",
            "site": "BlackRock_Professional",
        }
    ],
    "PNC Financial Services": [
        {
            "provider": "workday",
            "host": "pnc.wd5.myworkdayjobs.com",
            "tenant": "pnc",
            "site": "External",
        }
    ],
    "U.S. Bank": [
        {
            "provider": "workday",
            "host": "usbank.wd1.myworkdayjobs.com",
            "tenant": "usbank",
            "site": "US_Bank_Careers",
        }
    ],
    "Vanguard": [
        {
            "provider": "workday",
            "host": "vanguard.wd5.myworkdayjobs.com",
            "tenant": "vanguard",
            "site": "vanguard_external",
        }
    ],
    "TD Bank Group": [
        {
            "provider": "workday",
            "host": "td.wd3.myworkdayjobs.com",
            "tenant": "td",
            "site": "TD_Bank_Careers",
        }
    ],
    "Marsh McLennan": [
        {
            "provider": "workday",
            "host": "mmc.wd1.myworkdayjobs.com",
            "tenant": "mmc",
            "site": "MMC",
        }
    ],
    "Aon": [
        {
            "provider": "workday",
            "host": "aon.wd1.myworkdayjobs.com",
            "tenant": "aon",
            "site": "External",
        }
    ],
    "CBRE": [
        {
            "provider": "workday",
            "host": "cbre.wd1.myworkdayjobs.com",
            "tenant": "cbre",
            "site": "External",
        }
    ],
    "3M": [
        {
            "provider": "workday",
            "host": "3m.wd1.myworkdayjobs.com",
            "tenant": "3m",
            "site": "Search",
        }
    ],
    "Elanco": [
        {
            "provider": "workday",
            "host": "elanco.wd5.myworkdayjobs.com",
            "tenant": "elanco",
            "site": "ELAExternalCareerSite",
        }
    ],
    "Warner Bros. Discovery": [
        {
            "provider": "workday",
            "host": "warnerbros.wd5.myworkdayjobs.com",
            "tenant": "warnerbros",
            "site": "global",
        }
    ],
    "F5": [
        {
            "provider": "workday",
            "host": "f5.wd1.myworkdayjobs.com",
            "tenant": "f5",
            "site": "f5jobs",
        }
    ],
    "Northern Trust": [
        {
            "provider": "workday",
            "host": "ntrs.wd1.myworkdayjobs.com",
            "tenant": "ntrs",
            "site": "careers",
        }
    ],
    "Amgen": [
        {
            "provider": "workday",
            "host": "amgen.wd1.myworkdayjobs.com",
            "tenant": "amgen",
            "site": "careers",
        }
    ],
    "Dell Technologies": [
        {
            "provider": "workday",
            "host": "dell.wd1.myworkdayjobs.com",
            "tenant": "dell",
            "site": "External",
        }
    ],
}


@dataclass
class VerificationOutcome:
    provider: str
    endpoint: str
    status: str  # verified | failed | blocked | empty
    http_status: int | None = None
    jobs_total: int | None = None
    detail: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)


@dataclass
class CompanyCoverage:
    rank: int
    company: str
    excel_name: str
    industry: str | None
    student_interest: int
    merged_ranks: list[int] = field(default_factory=list)
    merged_names: list[str] = field(default_factory=list)
    in_config: bool = False
    config_enabled: bool = False
    config_provider: str | None = None
    config_verification_status: str | None = None
    discovered: list[dict[str, Any]] = field(default_factory=list)
    unsupported_markers: list[str] = field(default_factory=list)
    verifications: list[VerificationOutcome] = field(default_factory=list)

    @property
    def best_verified(self) -> VerificationOutcome | None:
        for outcome in self.verifications:
            if outcome.status == "verified":
                return outcome
        return None


def read_top_companies(excel_path: Path, top: int) -> list[dict[str, Any]]:
    import openpyxl

    workbook = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows = []
    for index, row in enumerate(sheet.iter_rows(values_only=True)):
        if index == 0 or row[1] is None:
            continue
        interest = row[3] if isinstance(row[3], (int, float)) else 0
        rows.append(
            {
                "excel_name": str(row[1]).strip(),
                "industry": str(row[2]).strip() if row[2] else None,
                "interest": int(interest or 0),
            }
        )
    rows.sort(key=lambda r: (-r["interest"], r["excel_name"].casefold()))
    deduped: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for rank, row in enumerate(rows[:top], start=1):
        row["rank"] = rank
        row["company"] = COMPANY_ALIASES.get(
            row["excel_name"].casefold(), row["excel_name"]
        )
        canonical = row["company"].casefold()
        if canonical in seen:
            # Duplicate alias (e.g. "Slalom Consulting" after "Slalom"): the
            # best-ranked row wins; record the merged rank for the report.
            seen[canonical].setdefault("merged_ranks", []).append(rank)
            seen[canonical].setdefault("merged_names", []).append(row["excel_name"])
            continue
        seen[canonical] = row
        deduped.append(row)
    return deduped


def _verify_greenhouse(client: HttpClient, c: dict[str, str]) -> VerificationOutcome:
    url = f"https://boards-api.greenhouse.io/v1/boards/{c['slug']}/jobs"
    return _probe_json(client, "greenhouse", url, c, jobs_key="jobs")


def _verify_lever(client: HttpClient, c: dict[str, str]) -> VerificationOutcome:
    url = f"https://api.lever.co/v0/postings/{c['slug']}?mode=json&limit=1"
    outcome = _probe_json(client, "lever", url, c)
    if outcome.status == "verified" and isinstance(outcome.jobs_total, int):
        return outcome
    return outcome


def _verify_ashby(client: HttpClient, c: dict[str, str]) -> VerificationOutcome:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{c['slug']}"
    return _probe_json(client, "ashby", url, c, jobs_key="jobs")


def _verify_smartrecruiters(
    client: HttpClient, c: dict[str, str]
) -> VerificationOutcome:
    url = (
        "https://api.smartrecruiters.com/v1/companies/"
        f"{c['slug']}/postings?limit=1"
    )
    return _probe_json(client, "smartrecruiters", url, c, total_key="totalFound")


def _verify_workday(client: HttpClient, c: dict[str, str]) -> VerificationOutcome:
    host, site = c["host"], c["site"]
    tenant = c.get("tenant") or host.split(".")[0]
    c = {**c, "tenant": tenant}
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}
    try:
        response = client.post_json(url, body)
    except HttpError as exc:
        return VerificationOutcome(
            provider="workday",
            endpoint=url,
            status="blocked" if exc.blocked else "failed",
            http_status=exc.status_code,
            detail=str(exc),
            identifiers=c,
        )
    if response.status_code != 200:
        return VerificationOutcome(
            provider="workday",
            endpoint=url,
            status="failed",
            http_status=response.status_code,
            detail=f"HTTP {response.status_code}",
            identifiers=c,
        )
    try:
        payload = response.json()
    except ValueError:
        return VerificationOutcome(
            provider="workday",
            endpoint=url,
            status="failed",
            http_status=200,
            detail="non-JSON response",
            identifiers=c,
        )
    total = payload.get("total") if isinstance(payload, dict) else None
    status = "verified" if isinstance(total, int) and total > 0 else "empty"
    return VerificationOutcome(
        provider="workday",
        endpoint=url,
        status=status,
        http_status=200,
        jobs_total=total if isinstance(total, int) else None,
        identifiers=c,
    )


def _verify_oraclecloud(client: HttpClient, c: dict[str, str]) -> VerificationOutcome:
    host, site = c["host"], c["site"]
    url = (
        f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        f"?onlyData=true&finder=findReqs;siteNumber={site},limit=1,offset=0,"
        "sortBy=POSTING_DATES_DESC"
    )
    outcome = _probe_json(client, "oraclecloud", url, c)
    if outcome.status in {"verified", "empty"} and outcome.http_status == 200:
        # jobs_total is filled from items[0].TotalJobsCount in _probe_json.
        pass
    return outcome


def _probe_json(
    client: HttpClient,
    provider: str,
    url: str,
    identifiers: dict[str, str],
    *,
    jobs_key: str | None = None,
    total_key: str | None = None,
) -> VerificationOutcome:
    try:
        response = client.get(url)
    except HttpError as exc:
        return VerificationOutcome(
            provider=provider,
            endpoint=url,
            status="blocked" if exc.blocked else "failed",
            http_status=exc.status_code,
            detail=str(exc),
            identifiers=identifiers,
        )
    if response.status_code != 200:
        return VerificationOutcome(
            provider=provider,
            endpoint=url,
            status="failed",
            http_status=response.status_code,
            detail=f"HTTP {response.status_code}",
            identifiers=identifiers,
        )
    try:
        payload = response.json()
    except ValueError:
        return VerificationOutcome(
            provider=provider,
            endpoint=url,
            status="failed",
            http_status=200,
            detail="non-JSON response",
            identifiers=identifiers,
        )

    jobs_total: int | None = None
    if isinstance(payload, list):
        jobs_total = len(payload)
    elif isinstance(payload, dict):
        if total_key and isinstance(payload.get(total_key), int):
            jobs_total = payload[total_key]
        elif jobs_key and isinstance(payload.get(jobs_key), list):
            meta_total = payload.get("meta", {})
            if isinstance(meta_total, dict) and isinstance(
                meta_total.get("total"), int
            ):
                jobs_total = meta_total["total"]
            else:
                jobs_total = len(payload[jobs_key])
        elif isinstance(payload.get("items"), list) and payload["items"]:
            first = payload["items"][0]
            if isinstance(first, dict) and isinstance(
                first.get("TotalJobsCount"), int
            ):
                jobs_total = first["TotalJobsCount"]

    status = "verified" if jobs_total is None or jobs_total > 0 else "empty"
    if jobs_total is None:
        # 200 + JSON but shape unknown: verified only if payload is non-empty.
        status = "verified" if payload else "empty"
    return VerificationOutcome(
        provider=provider,
        endpoint=url,
        status=status,
        http_status=200,
        jobs_total=jobs_total,
        identifiers=identifiers,
    )


_VERIFIERS = {
    "greenhouse": _verify_greenhouse,
    "lever": _verify_lever,
    "ashby": _verify_ashby,
    "smartrecruiters": _verify_smartrecruiters,
    "workday": _verify_workday,
    "oraclecloud": _verify_oraclecloud,
}


def _candidate_key(candidate: dict[str, str]) -> tuple[str, ...]:
    return tuple(
        str(candidate.get(k) or "")
        for k in ("provider", "slug", "host", "tenant", "site")
    )


def run(args: argparse.Namespace) -> int:
    excel_path = Path(args.excel)
    top_rows = read_top_companies(excel_path, args.top)
    config = load_company_careers_config(args.config)
    config_by_name = {c.company_name.casefold(): c for c in config.companies}

    client = HttpClient(min_interval_seconds=args.min_interval)
    coverages: list[CompanyCoverage] = []

    for row in top_rows:
        company = row["company"]
        coverage = CompanyCoverage(
            rank=row["rank"],
            company=company,
            excel_name=row["excel_name"],
            industry=row["industry"],
            student_interest=row["interest"],
            merged_ranks=row.get("merged_ranks", []),
            merged_names=row.get("merged_names", []),
        )
        target = config_by_name.get(company.casefold())
        if target is not None:
            coverage.in_config = True
            coverage.config_enabled = target.enabled
            coverage.config_provider = target.ats_provider
            coverage.config_verification_status = target.verification_status

        if (
            args.live
            and coverage.rank >= args.min_rank
            and (args.only is None or args.only.casefold() in company.casefold())
        ):
            _research_company(client, company, coverage, args)
        coverages.append(coverage)

    report = _build_report(coverages, args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "company_coverage_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_dir / "company_coverage_report.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(f"Wrote {json_path} and {md_path}")
    summary = report["summary"]
    print(json.dumps(summary, indent=2))
    return 0


def _research_company(
    client: HttpClient,
    company: str,
    coverage: CompanyCoverage,
    args: argparse.Namespace,
) -> None:
    candidates: list[dict[str, str]] = list(CURATED_CANDIDATES.get(company, []))

    careers_url = CAREERS_PAGES.get(company)
    if careers_url and not args.skip_discovery:
        try:
            response = client.get(careers_url, accept="text/html")
            if response.status_code == 200:
                discovery = detect_ats_candidates(response.text)
                coverage.unsupported_markers = discovery.unsupported_markers
                for detected in discovery.supported:
                    entry = {
                        k: v
                        for k, v in asdict(detected).items()
                        if k in {"provider", "slug", "host", "tenant", "site"} and v
                    }
                    coverage.discovered.append(
                        {**entry, "evidence": detected.evidence}
                    )
                    if detected.provider == "workday" and not (
                        entry.get("host") and entry.get("site")
                    ):
                        continue  # incomplete workday identifiers; skip probe
                    if detected.provider == "oraclecloud" and not entry.get("site"):
                        continue
                    candidates.append(entry)
        except HttpError as exc:
            coverage.discovered.append({"error": f"discovery failed: {exc}"})

    seen: set[tuple[str, ...]] = set()
    for candidate in candidates:
        provider = candidate.get("provider", "")
        verifier = _VERIFIERS.get(provider)
        if verifier is None:
            continue
        key = _candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        coverage.verifications.append(verifier(client, candidate))


def _build_report(
    coverages: list[CompanyCoverage], args: argparse.Namespace
) -> dict[str, Any]:
    entries = []
    for coverage in coverages:
        entry = asdict(coverage)
        best = coverage.best_verified
        entry["best_verified"] = asdict(best) if best else None
        entries.append(entry)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "top_n": len(coverages),
        "live": bool(args.live),
        "in_config": sum(1 for c in coverages if c.in_config),
        "enabled_in_config": sum(1 for c in coverages if c.config_enabled),
        "verified_live": sum(1 for c in coverages if c.best_verified),
        "unsupported_markers_found": sum(
            1 for c in coverages if c.unsupported_markers
        ),
        "missing_from_config": [c.company for c in coverages if not c.in_config],
    }
    return {"summary": summary, "companies": entries}


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# MSIS LAMP Employers ATS Coverage Report",
        "",
        f"Generated: {report['summary']['generated_at']}",
        "",
        "| # | Company | Interest | In config | Enabled | Verified endpoint |",
        "|---|---------|----------|-----------|---------|-------------------|",
    ]
    for entry in report["companies"]:
        best = entry.get("best_verified")
        verified = (
            f"{best['provider']} ({best.get('jobs_total', '?')} jobs)" if best else "-"
        )
        lines.append(
            f"| {entry['rank']} | {entry['company']} | {entry['student_interest']} "
            f"| {'yes' if entry['in_config'] else 'NO'} "
            f"| {'yes' if entry['config_enabled'] else 'no'} | {verified} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", default="data/lamp_list_2025_26.xlsx")
    parser.add_argument("--config", default="config/company_careers.yml")
    parser.add_argument("--top", type=int, default=300)
    parser.add_argument("--out", default="outputs")
    parser.add_argument("--live", action="store_true", help="Perform network probes")
    parser.add_argument(
        "--min-rank",
        type=int,
        default=1,
        help="Restrict live probes to companies at or below this rank",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip careers-page HTML discovery; only probe curated candidates",
    )
    parser.add_argument("--only", default=None, help="Restrict live probes to one company")
    parser.add_argument("--min-interval", type=float, default=1.0)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
