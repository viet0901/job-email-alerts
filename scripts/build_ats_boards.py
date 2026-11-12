#!/usr/bin/env python3
"""Build ats_boards.yaml from LastRound ATS directory + curated Workday sites."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Large / mid-size employers we actually want (word match on company name or slug).
TOP_EMPLOYERS = [
    "stripe", "airbnb", "databricks", "snowflake", "cloudflare", "datadog",
    "figma", "robinhood", "coinbase", "dropbox", "asana", "airtable", "brex",
    "plaid", "affirm", "duolingo", "spotify", "palantir", "rivian", "doordash",
    "lyft", "instacart", "shopify", "twilio", "block", "square", "discord",
    "notion", "openai", "anthropic", "cohere", "perplexity", "scale ai",
    "huggingface", "hugging face", "cursor", "anysphere", "vercel", "linear",
    "ramp", "replit", "miro", "together ai", "anduril", "spacex", "tesla",
    "openai", "anthropic", "groq", "mistral", "xai", "adept",
    "elastic", "mongodb", "confluent", "hashicorp", "gitlab", "github",
    "atlassian", "okta", "crowdstrike", "palo alto", "zscaler", "fortinet",
    "servicenow", "salesforce", "workday", "intuit", "adp", "paychex",
    "visa", "mastercard", "paypal", "square", "stripe", "adyen", "klarna",
    "american express", "amex", "discover", "capital one",
    "netflix", "uber", "lyft", "airbnb",
    "snap", "pinterest", "reddit", "roblox", "unity", "ea", "electronic arts",
    "activision", "take-two", "zynga",
    "zoom", "slack", "box", "dropbox", "docusign", "hubspot", "zendesk",
    "twilio", "sendgrid", "cloudflare", "fastly", "akamai",
    "snowflake", "databricks", "palantir", "alteryx", "tableau",
    "nvidia", "amd", "intel", "qualcomm", "broadcom", "arm", "marvell",
    "applied materials", "lam research", "kla", "asml", "tsmc",
    "adobe", "autodesk", "synopsys", "cadence",
    "ibm", "oracle", "sap", "cisco", "dell", "hp", "hewlett packard",
    "vmware", "red hat", "splunk",
    "spotify", "soundhound", "roku",
    "wayfair", "etsy", "ebay", "shopify", "chewy",
    "coinbase", "kraken", "gemini", "ripple",
    "two sigma", "citadel", "jane street", "jump trading", "hrt",
    "hudson river", "de shaw", "point72", "millennium", "bridgewater",
    "blackrock", "blackstone", "kkr", "apollo", "carlyle", "ares",
    "goldman sachs", "morgan stanley", "jpmorgan", "jp morgan",
    "bank of america", "wells fargo", "citi", "citigroup",
    "barclays", "hsbc", "deutsche bank", "ubs", "credit suisse",
    "charles schwab", "fidelity", "vanguard", "state street",
    "truist", "pnc", "us bank", "ally financial", "sofi", "keybank",
    "regions", "bmo", "m&t", "bbva", "santander", "rbc", "scotiabank",
    "bloomberg", "reuters", "s&p global", "moodys", "fitch", "lseg",
    "invesco", "wellington", "t rowe", "pimco", "morningstar",
    "worldquant", "aqr", "man group", "optiver", "imc", "virtu",
    "akuna", "flow traders", "gsa capital", "winton", "pdt partners",
    "fiserv", "broadridge", "equifax", "transunion", "freddie mac",
    "fannie mae", "aig", "allstate", "prudential", "travelers",
    "ameriprise", "brookfield",
    "mckinsey", "bain", "boston consulting", "bcg", "deloitte",
    "pwc", "ey", "kpmg", "accenture", "capgemini", "cognizant",
    "infosys", "tcs", "wipro", "hcl",
    "abbvie", "abbott", "pfizer", "merck", "bristol", "lilly", "eli lilly",
    "amgen", "gilead", "biogen", "regeneron", "moderna", "biontech",
    "johnson & johnson", "j&j", "novartis", "roche", "sanofi", "gsk",
    "astrazeneca", "bayer", "takeda",
    "unitedhealth", "anthem", "elevance", "cigna", "humana", "cvshealth",
    "cvs health", "kaiser",
    "walmart", "target", "costco", "home depot", "lowes", "best buy",
    "macys", "nordstrom", "gap", "nike", "adidas", "lululemon",
    "starbucks", "mcdonalds", "chipotle", "yum",
    "disney", "comcast", "warner", "paramount", "sony", "nbcuniversal",
    "verizon", "at&t", "t-mobile",
    "exxon", "chevron", "shell", "bp", "conocophillips",
    "ge aerospace", "general electric", "honeywell", "3m", "caterpillar",
    "deere", "john deere", "boeing", "lockheed", "northrop", "raytheon",
    "rtx", "general dynamics", "l3harris",
    "ford", "general motors", "gm", "stellantis", "toyota", "honda",
    "tesla", "rivian", "lucid",
    "american airlines", "delta", "united airlines", "southwest",
    "ups", "fedex",
    " Pepsi", "pepsico", "coca-cola", "kraft heinz", "general mills",
    "procter", "unilever", "colgate", "kimberly-clark",
    "expedia", "booking", "airbnb",
    "zillow", "redfin", "opendoor",
    "grammarly", "canva", "miro", "figma",
    "databricks", "snowflake", "dbt", "fivetran",
    "datadog", "new relic", "dynatrace", "splunk",
    "okta", "auth0", "ping identity",
    "crowdstrike", "sentinelone", "rapid7",
    "hashicorp", "gitlab", "github", "atlassian", "jetbrains",
    "unity", "epic games",
    "bytedance", "tiktok", "shopify",
    "wise", "revolut", "chime", "nubank",
    "toast", "square", "block",
    "waymo", "cruise", "zoox", "aurora",
    "openai", "anthropic", "inflection", "character ai",
    "huggingface", "weights and biases", "wandb", "scale ai",
    "labelbox", "snorkel",
    "coreweave", "lambda", "crusoe",
    "stripe", "checkout.com", "marqeta",
    "nuro", "applied intuition",
    "sentry", "pagerduty", "opsgenie",
    "confluent", "redpanda", "databricks",
    "dbt labs", "census", "hightouch",
    "amplitude", "mixpanel", "segment", "twilio",
    "intercom", "freshworks",
    "rippling", "gusto", "deel", "remote.com",
    "carta", "angellist",
    "brex", "ramp", "mercury", "column",
    "chime", "affirm", "klarna", "afterpay",
    "sofi", "robinhood", "webull",
    "coinbase", "circle", "paxos",
    "openai", "midjourney", "stability",
    "runway", "elevenlabs", "suno",
    "notion", "coda", "airtable", "monday",
    "asana", "clickup", "linear", "height",
    "figma", "canva", "adobe",
    "webflow", "framer",
    "vercel", "netlify", "cloudflare", "fastly",
    "supabase", "planetscale", "neon",
    "snowflake", "bigquery",
    "palantir", "c3 ai", "dataiku", "alteryx",
    "sas", "spss",
    "moodys", "sp global", "factset", "refinitiv",
    "ice", "cme", "nasdaq",
    "visa", "mastercard", "amex",
    "experian", "equifax", "transunion",
    "nielsen", "comscore",
    "iqvia", "optum", "change healthcare",
    "epic systems", "cerner", "oracle health",
    "illumina", "10x genomics", "thermo fisher", "danaher", "agilent",
    "boston scientific", "medtronic", "stryker", "zimmer",
    "edwards lifesciences", "intuitive surgical",
    "walgreens", "rite aid",
    "kroger", "albertsons", "publix", "sysco",
    "marriott", "hilton", "hyatt", "airbnb",
    "booking holdings", "expedia",
    "live nation", "ticketmaster",
    "under armour", "columbia sportswear",
    "patagonia", "rei",
]

SKIP_SLUG = re.compile(
    r"(australia|india|canada|quebec|uae|internal|contractor|high-?volume|"
    r"social$|prep$|foundation|roofing)",
    re.I,
)
SKIP_NAME = re.compile(
    r"\b(staffing|recruit|agency|consulting pvt)\b",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _wanted(name: str, slug: str) -> bool:
    if SKIP_SLUG.search(slug) or SKIP_NAME.search(name):
        return False
    blob = f"{_norm(name)} {_norm(slug)}"
    for emp in TOP_EMPLOYERS:
        e = _norm(emp)
        if len(e) < 4:
            continue
        if re.search(rf"\b{re.escape(e)}\b", blob):
            return True
        compact = e.replace(" ", "")
        if compact and compact == _norm(slug).replace(" ", ""):
            return True
    return False


WORKDAY = [
    {"host": "mastercard.wd1.myworkdayjobs.com", "tenant": "mastercard", "site": "CorporateCareers", "name": "Mastercard"},
    {"host": "nvidia.wd5.myworkdayjobs.com", "tenant": "nvidia", "site": "NVIDIAExternalCareerSite", "name": "NVIDIA"},
    {"host": "adobe.wd5.myworkdayjobs.com", "tenant": "adobe", "site": "external_experienced", "name": "Adobe"},
    {"host": "salesforce.wd12.myworkdayjobs.com", "tenant": "salesforce", "site": "External_Career_Site", "name": "Salesforce"},
    {"host": "cisco.wd5.myworkdayjobs.com", "tenant": "cisco", "site": "Cisco_Careers", "name": "Cisco"},
    {"host": "paypal.wd1.myworkdayjobs.com", "tenant": "paypal", "site": "jobs", "name": "PayPal"},
    {"host": "target.wd5.myworkdayjobs.com", "tenant": "target", "site": "targetcareers", "name": "Target"},
    {"host": "intel.wd1.myworkdayjobs.com", "tenant": "intel", "site": "External", "name": "Intel"},
    {"host": "pnc.wd5.myworkdayjobs.com", "tenant": "pnc", "site": "External", "name": "PNC"},
    {"host": "gsk.wd5.myworkdayjobs.com", "tenant": "gsk", "site": "GSKCareers", "name": "GSK"},
    {"host": "td.wd3.myworkdayjobs.com", "tenant": "td", "site": "TD_Bank_Careers", "name": "TD Bank"},
    {"host": "capitalone.wd12.myworkdayjobs.com", "tenant": "capitalone", "site": "Capital_One", "name": "Capital One"},
    {"host": "wf.wd1.myworkdayjobs.com", "tenant": "wf", "site": "WellsFargoJobs", "name": "Wells Fargo"},
    {"host": "ghr.wd1.myworkdayjobs.com", "tenant": "ghr", "site": "Lateral-US", "name": "Bank of America"},
    {"host": "ms.wd5.myworkdayjobs.com", "tenant": "ms", "site": "External", "name": "Morgan Stanley"},
    {"host": "accenture.wd103.myworkdayjobs.com", "tenant": "accenture", "site": "AccentureCareers", "name": "Accenture"},
    {"host": "jj.wd5.myworkdayjobs.com", "tenant": "jj", "site": "JJ", "name": "Johnson & Johnson"},
    {"host": "jpmc.wd5.myworkdayjobs.com", "tenant": "jpmc", "site": "JPMC_US", "name": "JPMorgan Chase"},
    {"host": "gs.wd1.myworkdayjobs.com", "tenant": "gs", "site": "GoldmanSachs", "name": "Goldman Sachs"},
    {"host": "citi.wd3.myworkdayjobs.com", "tenant": "citi", "site": "2", "name": "Citi"},
    {"host": "discover.wd5.myworkdayjobs.com", "tenant": "discover", "site": "Discover", "name": "Discover"},
    {"host": "aexp.wd1.myworkdayjobs.com", "tenant": "aexp", "site": "American_Express", "name": "American Express"},
    {"host": "schwab.wd1.myworkdayjobs.com", "tenant": "schwab", "site": "External", "name": "Charles Schwab"},
    {"host": "blackrock.wd1.myworkdayjobs.com", "tenant": "blackrock", "site": "BlackRock_External_Career_Site", "name": "BlackRock"},
    {"host": "state.wd1.myworkdayjobs.com", "tenant": "state", "site": "StateStreet", "name": "State Street"},
    {"host": "truist.wd1.myworkdayjobs.com", "tenant": "truist", "site": "Truist", "name": "Truist"},
    {"host": "usbank.wd1.myworkdayjobs.com", "tenant": "usbank", "site": "USB", "name": "U.S. Bank"},
    {"host": "oracle.wd5.myworkdayjobs.com", "tenant": "oracle", "site": "External", "name": "Oracle"},
    {"host": "ibm.wd1.myworkdayjobs.com", "tenant": "ibm", "site": "IBM_Careers", "name": "IBM"},
    {"host": "dell.wd1.myworkdayjobs.com", "tenant": "dell", "site": "External_Careers", "name": "Dell"},
    {"host": "hp.wd5.myworkdayjobs.com", "tenant": "hp", "site": "ExternalCareerSite", "name": "HP"},
    {"host": "qualcomm.wd5.myworkdayjobs.com", "tenant": "qualcomm", "site": "External", "name": "Qualcomm"},
    {"host": "amd.wd1.myworkdayjobs.com", "tenant": "amd", "site": "AMD", "name": "AMD"},
    {"host": "broadcom.wd1.myworkdayjobs.com", "tenant": "broadcom", "site": "External_Career", "name": "Broadcom"},
    {"host": "appliedmaterials.wd1.myworkdayjobs.com", "tenant": "appliedmaterials", "site": "External", "name": "Applied Materials"},
    {"host": "lamresearch.wd1.myworkdayjobs.com", "tenant": "lamresearch", "site": "Lam_External", "name": "Lam Research"},
    {"host": "kla.wd1.myworkdayjobs.com", "tenant": "kla", "site": "Search", "name": "KLA"},
    {"host": "autodesk.wd1.myworkdayjobs.com", "tenant": "autodesk", "site": "Ext", "name": "Autodesk"},
    {"host": "intuit.wd1.myworkdayjobs.com", "tenant": "intuit", "site": "Intuit_Careers", "name": "Intuit"},
    {"host": "workday.wd5.myworkdayjobs.com", "tenant": "workday", "site": "Workday", "name": "Workday"},
    {"host": "servicenow.wd1.myworkdayjobs.com", "tenant": "servicenow", "site": "servicenowcareers", "name": "ServiceNow"},
    {"host": "splunk.wd5.myworkdayjobs.com", "tenant": "splunk", "site": "Jobs_at_Splunk", "name": "Splunk"},
    {"host": "okta.wd1.myworkdayjobs.com", "tenant": "okta", "site": "Okta_Careers", "name": "Okta"},
    {"host": "crowdstrike.wd1.myworkdayjobs.com", "tenant": "crowdstrike", "site": "crowdstrikecareers", "name": "CrowdStrike"},
    {"host": "paloaltonetworks.wd1.myworkdayjobs.com", "tenant": "paloaltonetworks", "site": "External", "name": "Palo Alto Networks"},
    {"host": "fortinet.wd1.myworkdayjobs.com", "tenant": "fortinet", "site": "Fortinet_Careers", "name": "Fortinet"},
    {"host": "vmware.wd1.myworkdayjobs.com", "tenant": "vmware", "site": "VMware_Careers", "name": "VMware"},
    {"host": "redhat.wd5.myworkdayjobs.com", "tenant": "redhat", "site": "jobs", "name": "Red Hat"},
    {"host": "atlassian.wd1.myworkdayjobs.com", "tenant": "atlassian", "site": "Atlassian", "name": "Atlassian"},
    {"host": "walmart.wd5.myworkdayjobs.com", "tenant": "walmart", "site": "WalmartExternal", "name": "Walmart"},
    {"host": "homedepot.wd5.myworkdayjobs.com", "tenant": "homedepot", "site": "HD_Career_Site", "name": "Home Depot"},
    {"host": "lowes.wd1.myworkdayjobs.com", "tenant": "lowes", "site": "Lowes", "name": "Lowe's"},
    {"host": "costco.wd1.myworkdayjobs.com", "tenant": "costco", "site": "Costco_Careers", "name": "Costco"},
    {"host": "bestbuy.wd5.myworkdayjobs.com", "tenant": "bestbuy", "site": "BBY_Jobs", "name": "Best Buy"},
    {"host": "nike.wd1.myworkdayjobs.com", "tenant": "nike", "site": "nke", "name": "Nike"},
    {"host": "starbucks.wd1.myworkdayjobs.com", "tenant": "starbucks", "site": "Starbucks", "name": "Starbucks"},
    {"host": "mcdonalds.wd5.myworkdayjobs.com", "tenant": "mcdonalds", "site": "McDonalds_Careers", "name": "McDonald's"},
    {"host": "disney.wd5.myworkdayjobs.com", "tenant": "disneycareers", "site": "Disney_Careers", "name": "Disney"},
    {"host": "comcast.wd5.myworkdayjobs.com", "tenant": "comcast", "site": "Comcast_Careers", "name": "Comcast"},
    {"host": "verizon.wd5.myworkdayjobs.com", "tenant": "verizon", "site": "Verizon_External", "name": "Verizon"},
    {"host": "att.wd1.myworkdayjobs.com", "tenant": "att", "site": "ATT_Careers", "name": "AT&T"},
    {"host": "tmobile.wd5.myworkdayjobs.com", "tenant": "tmobile", "site": "External", "name": "T-Mobile"},
    {"host": "geaerospace.wd5.myworkdayjobs.com", "tenant": "geaerospace", "site": "GE_Aerospace", "name": "GE Aerospace"},
    {"host": "honeywell.wd1.myworkdayjobs.com", "tenant": "honeywell", "site": "Honeywell", "name": "Honeywell"},
    {"host": "3m.wd1.myworkdayjobs.com", "tenant": "3m", "site": "Search", "name": "3M"},
    {"host": "caterpillar.wd5.myworkdayjobs.com", "tenant": "caterpillar", "site": "CAT", "name": "Caterpillar"},
    {"host": "deere.wd5.myworkdayjobs.com", "tenant": "deere", "site": "Search", "name": "John Deere"},
    {"host": "boeing.wd1.myworkdayjobs.com", "tenant": "boeing", "site": "BA_EXT", "name": "Boeing"},
    {"host": "lockheedmartin.wd5.myworkdayjobs.com", "tenant": "lockheedmartin", "site": "LockheedMartin", "name": "Lockheed Martin"},
    {"host": "northropgrumman.wd5.myworkdayjobs.com", "tenant": "northropgrumman", "site": "NGS", "name": "Northrop Grumman"},
    {"host": "rtx.wd5.myworkdayjobs.com", "tenant": "rtx", "site": "RTX", "name": "RTX"},
    {"host": "generaldynamics.wd5.myworkdayjobs.com", "tenant": "generaldynamics", "site": "GD", "name": "General Dynamics"},
    {"host": "ford.wd5.myworkdayjobs.com", "tenant": "ford", "site": "Ford", "name": "Ford"},
    {"host": "gm.wd5.myworkdayjobs.com", "tenant": "gm", "site": "GM_Careers", "name": "General Motors"},
    {"host": "toyota.wd1.myworkdayjobs.com", "tenant": "toyota", "site": "Toyota", "name": "Toyota"},
    {"host": "honda.wd5.myworkdayjobs.com", "tenant": "honda", "site": "Honda", "name": "Honda"},
    {"host": "ups.wd5.myworkdayjobs.com", "tenant": "ups", "site": "UPS", "name": "UPS"},
    {"host": "fedex.wd5.myworkdayjobs.com", "tenant": "fedex", "site": "FedEx", "name": "FedEx"},
    {"host": "aa.wd1.myworkdayjobs.com", "tenant": "aa", "site": "AA_External", "name": "American Airlines"},
    {"host": "delta.wd5.myworkdayjobs.com", "tenant": "delta", "site": "Delta", "name": "Delta"},
    {"host": "united.wd1.myworkdayjobs.com", "tenant": "united", "site": "UAL", "name": "United Airlines"},
    {"host": "exxonmobil.wd5.myworkdayjobs.com", "tenant": "exxonmobil", "site": "XOM", "name": "ExxonMobil"},
    {"host": "chevron.wd5.myworkdayjobs.com", "tenant": "chevron", "site": "Chevron", "name": "Chevron"},
    {"host": "shell.wd3.myworkdayjobs.com", "tenant": "shell", "site": "Shell_Careers", "name": "Shell"},
    {"host": "bp.wd3.myworkdayjobs.com", "tenant": "bp", "site": "BP_Careers", "name": "bp"},
    {"host": "pfizer.wd1.myworkdayjobs.com", "tenant": "pfizer", "site": "PfizerCareers", "name": "Pfizer"},
    {"host": "merck.wd5.myworkdayjobs.com", "tenant": "merck", "site": "Merck", "name": "Merck"},
    {"host": "bms.wd5.myworkdayjobs.com", "tenant": "bms", "site": "BMS", "name": "Bristol Myers Squibb"},
    {"host": "lilly.wd5.myworkdayjobs.com", "tenant": "lilly", "site": "LLY", "name": "Eli Lilly"},
    {"host": "amgen.wd1.myworkdayjobs.com", "tenant": "amgen", "site": "Amgen", "name": "Amgen"},
    {"host": "gilead.wd1.myworkdayjobs.com", "tenant": "gilead", "site": "gileadcareers", "name": "Gilead"},
    {"host": "biogen.wd1.myworkdayjobs.com", "tenant": "biogen", "site": "External_Careers", "name": "Biogen"},
    {"host": "regeneron.wd1.myworkdayjobs.com", "tenant": "regeneron", "site": "regeneroncareers", "name": "Regeneron"},
    {"host": "abbvie.wd5.myworkdayjobs.com", "tenant": "abbvie", "site": "abbvie_careers", "name": "AbbVie"},
    {"host": "abbott.wd5.myworkdayjobs.com", "tenant": "abbott", "site": "abbottcareers", "name": "Abbott"},
    {"host": "novartis.wd3.myworkdayjobs.com", "tenant": "novartis", "site": "Novartis_Careers", "name": "Novartis"},
    {"host": "roche.wd3.myworkdayjobs.com", "tenant": "roche", "site": "Roche_Careers", "name": "Roche"},
    {"host": "sanofi.wd3.myworkdayjobs.com", "tenant": "sanofi", "site": "SanofiCareers", "name": "Sanofi"},
    {"host": "astrazeneca.wd3.myworkdayjobs.com", "tenant": "astrazeneca", "site": "AstraZeneca_Careers", "name": "AstraZeneca"},
    {"host": "unitedhealthgroup.wd5.myworkdayjobs.com", "tenant": "unitedhealthgroup", "site": "UHG", "name": "UnitedHealth Group"},
    {"host": "cvshealth.wd1.myworkdayjobs.com", "tenant": "cvshealth", "site": "CVS_Health_Careers", "name": "CVS Health"},
    {"host": "cigna.wd5.myworkdayjobs.com", "tenant": "cigna", "site": "Cigna", "name": "Cigna"},
    {"host": "humana.wd5.myworkdayjobs.com", "tenant": "humana", "site": "Humana", "name": "Humana"},
    {"host": "pepsico.wd5.myworkdayjobs.com", "tenant": "pepsico", "site": "PepsiCo_Careers", "name": "PepsiCo"},
    {"host": "cocacola.wd1.myworkdayjobs.com", "tenant": "cocacola", "site": "TCCC", "name": "Coca-Cola"},
    {"host": "pg.wd5.myworkdayjobs.com", "tenant": "pg", "site": "Procter_and_Gamble", "name": "Procter & Gamble"},
    {"host": "unilever.wd3.myworkdayjobs.com", "tenant": "unilever", "site": "Unilever_Careers", "name": "Unilever"},
    {"host": "marriott.wd1.myworkdayjobs.com", "tenant": "marriott", "site": "Marriott_Careers", "name": "Marriott"},
    {"host": "hilton.wd5.myworkdayjobs.com", "tenant": "hilton", "site": "Hilton", "name": "Hilton"},
    {"host": "thermofisher.wd1.myworkdayjobs.com", "tenant": "thermofisher", "site": "Thermo_Fisher", "name": "Thermo Fisher"},
    {"host": "danaher.wd1.myworkdayjobs.com", "tenant": "danaher", "site": "Danaher", "name": "Danaher"},
    {"host": "medtronic.wd1.myworkdayjobs.com", "tenant": "medtronic", "site": "Medtronic", "name": "Medtronic"},
    {"host": "bsc.wd1.myworkdayjobs.com", "tenant": "bsc", "site": "Boston_Scientific", "name": "Boston Scientific"},
    {"host": "iqvia.wd1.myworkdayjobs.com", "tenant": "iqvia", "site": "IQVIA", "name": "IQVIA"},
    {"host": "deloitte.wd1.myworkdayjobs.com", "tenant": "deloitte", "site": "Deloitte", "name": "Deloitte"},
    {"host": "pwc.wd1.myworkdayjobs.com", "tenant": "pwc", "site": "PwC_Careers", "name": "PwC"},
    {"host": "ey.wd1.myworkdayjobs.com", "tenant": "ey", "site": "EY", "name": "EY"},
    {"host": "kpmg.wd1.myworkdayjobs.com", "tenant": "kpmg", "site": "KPMG_Careers", "name": "KPMG"},
    {"host": "mckinsey.wd1.myworkdayjobs.com", "tenant": "mckinsey", "site": "McKinsey", "name": "McKinsey"},
    {"host": "bcg.wd3.myworkdayjobs.com", "tenant": "bcg", "site": "BCG_Careers", "name": "BCG"},
    {"host": "bain.wd1.myworkdayjobs.com", "tenant": "bain", "site": "Bain", "name": "Bain"},
    {"host": "capgemini.wd3.myworkdayjobs.com", "tenant": "capgemini", "site": "Capgemini_Careers", "name": "Capgemini"},
    {"host": "cognizant.wd5.myworkdayjobs.com", "tenant": "cognizant", "site": "Cognizant", "name": "Cognizant"},
    {"host": "infosys.wd1.myworkdayjobs.com", "tenant": "infosys", "site": "Infosys_Careers", "name": "Infosys"},
    {"host": "expedia.wd5.myworkdayjobs.com", "tenant": "expedia", "site": "Expedia_Careers", "name": "Expedia"},
    {"host": "booking.wd3.myworkdayjobs.com", "tenant": "booking", "site": "Booking_Careers", "name": "Booking.com"},
    {"host": "ebay.wd5.myworkdayjobs.com", "tenant": "ebay", "site": "eBay_External", "name": "eBay"},
    {"host": "wayfair.wd1.myworkdayjobs.com", "tenant": "wayfair", "site": "Wayfair", "name": "Wayfair"},
    {"host": "zillow.wd1.myworkdayjobs.com", "tenant": "zillow", "site": "Zillow_Group", "name": "Zillow"},
    {"host": "ea.wd1.myworkdayjobs.com", "tenant": "ea", "site": "Electronic_Arts", "name": "Electronic Arts"},
    {"host": "activision.wd1.myworkdayjobs.com", "tenant": "activision", "site": "Activision", "name": "Activision"},
    {"host": "sony.wd1.myworkdayjobs.com", "tenant": "sony", "site": "Sony", "name": "Sony"},
    {"host": "paramount.wd5.myworkdayjobs.com", "tenant": "paramount", "site": "Paramount", "name": "Paramount"},
    {"host": "warnermedia.wd5.myworkdayjobs.com", "tenant": "warnermedia", "site": "Warner_Careers", "name": "Warner Bros. Discovery"},
    # Large banks / financial services (verified CXS)
    {"host": "barclays.wd3.myworkdayjobs.com", "tenant": "barclays", "site": "External_Career_Site_Barclays", "name": "Barclays"},
    {"host": "vanguard.wd5.myworkdayjobs.com", "tenant": "vanguard", "site": "Vanguard_External", "name": "Vanguard"},
    {"host": "wd1.myworkdaysite.com", "tenant": "fmr", "site": "FidelityCareers", "name": "Fidelity"},
    {"host": "spgi.wd5.myworkdayjobs.com", "tenant": "spgi", "site": "SPGI_Careers", "name": "S&P Global"},
    {"host": "fiserv.wd5.myworkdayjobs.com", "tenant": "fiserv", "site": "EXT", "name": "Fiserv"},
    {"host": "invesco.wd1.myworkdayjobs.com", "tenant": "invesco", "site": "IVZ", "name": "Invesco"},
    {"host": "blackstone.wd1.myworkdayjobs.com", "tenant": "blackstone", "site": "Blackstone_Careers", "name": "Blackstone"},
    {"host": "troweprice.wd5.myworkdayjobs.com", "tenant": "troweprice", "site": "TRowePrice", "name": "T. Rowe Price"},
    {"host": "carlyle.wd1.myworkdayjobs.com", "tenant": "carlyle", "site": "Carlyle", "name": "Carlyle"},
    {"host": "freddiemac.wd5.myworkdayjobs.com", "tenant": "freddiemac", "site": "External", "name": "Freddie Mac"},
    {"host": "keybank.wd5.myworkdayjobs.com", "tenant": "keybank", "site": "External_Career_Site", "name": "KeyBank"},
    {"host": "mtb.wd5.myworkdayjobs.com", "tenant": "mtb", "site": "MTB", "name": "M&T Bank"},
    {"host": "bmo.wd3.myworkdayjobs.com", "tenant": "bmo", "site": "External", "name": "BMO"},
    {"host": "ameriprise.wd5.myworkdayjobs.com", "tenant": "ameriprise", "site": "Ameriprise", "name": "Ameriprise"},
    {"host": "aig.wd1.myworkdayjobs.com", "tenant": "aig", "site": "AIG", "name": "AIG"},
    {"host": "prudential.wd3.myworkdayjobs.com", "tenant": "prudential", "site": "Prudential", "name": "Prudential"},
    {"host": "travelers.wd5.myworkdayjobs.com", "tenant": "travelers", "site": "External", "name": "Travelers"},
    {"host": "allstate.wd5.myworkdayjobs.com", "tenant": "allstate", "site": "Allstate_Careers", "name": "Allstate"},
    {"host": "regions.wd5.myworkdayjobs.com", "tenant": "regions", "site": "Regions_Careers", "name": "Regions"},
    {"host": "broadridge.wd5.myworkdayjobs.com", "tenant": "broadridge", "site": "Careers", "name": "Broadridge"},
    {"host": "equifax.wd5.myworkdayjobs.com", "tenant": "equifax", "site": "External", "name": "Equifax"},
    {"host": "transunion.wd5.myworkdayjobs.com", "tenant": "transunion", "site": "TransUnion", "name": "TransUnion"},
    {"host": "lseg.wd3.myworkdayjobs.com", "tenant": "lseg", "site": "Careers", "name": "LSEG"},
    {"host": "brookfield.wd5.myworkdayjobs.com", "tenant": "brookfield", "site": "Brookfield", "name": "Brookfield"},
    {"host": "wellington.wd5.myworkdayjobs.com", "tenant": "wellington", "site": "External", "name": "Wellington"},
    {"host": "aresmgmt.wd1.myworkdayjobs.com", "tenant": "aresmgmt", "site": "External", "name": "Ares"},
    {"host": "morningstar.wd5.myworkdayjobs.com", "tenant": "morningstar", "site": "Morningstar", "name": "Morningstar"},
    {"host": "bbva.wd3.myworkdayjobs.com", "tenant": "bbva", "site": "BBVA", "name": "BBVA"},
    {"host": "mastercard.wd1.myworkdayjobs.com", "tenant": "mastercard", "site": "Campus", "name": "Mastercard"},
]

SMARTRECRUITERS = [
    {"token": "Experian", "name": "Experian", "query": "Data Scientist", "limit": 40},
    {"token": "Experian", "name": "Experian", "query": "Data Analyst", "limit": 40},
    {"token": "Visa", "name": "Visa", "query": "Data Scientist", "limit": 40},
    {"token": "Visa", "name": "Visa", "query": "Data Analyst", "limit": 40},
    {"token": "ServiceNow", "name": "ServiceNow", "query": "Data Scientist", "limit": 40},
    {"token": "Wise", "name": "Wise", "query": "Data", "limit": 40},
    {"token": "Ikea", "name": "IKEA", "query": "Data Scientist", "limit": 30},
    {"token": "Siemens", "name": "Siemens", "query": "Data Scientist", "limit": 40},
    {"token": "Nvidia", "name": "NVIDIA", "query": "Data Scientist", "limit": 20},
]


def load_directory(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dump_yaml(path: Path, data: dict) -> None:
    lines = [
        "# Direct company career boards (Greenhouse / Lever / Ashby / Workday / SmartRecruiters).",
        "# Prefer official ATS APIs over LinkedIn/Indeed aggregators.",
        "# Regenerated by scripts/build_ats_boards.py",
        "",
    ]
    for key, boards in data.items():
        lines.append(f"{key}:")
        for b in boards:
            parts = ", ".join(f"{k}: {yaml_scalar(v)}" for k, v in b.items())
            lines.append(f"  - {{{parts}}}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def yaml_scalar(value) -> str:
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if re.search(r"[:#,\{\}\[\]]", text) or " " in text or any(c.isupper() for c in text):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/ats-directory.csv")
    rows = load_directory(csv_path)
    grouped: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        vendor = (row.get("ats_vendor") or "").strip().lower()
        name = (row.get("company_name") or "").strip()
        slug = (row.get("board_slug") or "").strip()
        if vendor not in {"greenhouse", "lever", "ashby"}:
            continue
        if not slug or (vendor, slug) in seen:
            continue
        if not _wanted(name, slug):
            continue
        seen.add((vendor, slug))
        grouped[vendor].append({"token": slug, "name": name or slug})

    for vendor in grouped:
        grouped[vendor].sort(key=lambda x: x["name"].lower())

    extra_gh = [
        {"token": "stripe", "name": "Stripe"},
        {"token": "airbnb", "name": "Airbnb"},
        {"token": "databricks", "name": "Databricks"},
        {"token": "cloudflare", "name": "Cloudflare"},
        {"token": "figma", "name": "Figma"},
        {"token": "robinhood", "name": "Robinhood"},
        {"token": "datadog", "name": "Datadog"},
        {"token": "lyft", "name": "Lyft"},
        {"token": "doordashusa", "name": "DoorDash"},
        {"token": "anthropic", "name": "Anthropic"},
        {"token": "spacex", "name": "SpaceX"},
        {"token": "andurilindustries", "name": "Anduril"},
        {"token": "bytedance", "name": "ByteDance"},
        {"token": "janestreet", "name": "Jane Street"},
        {"token": "jumptrading", "name": "Jump Trading"},
        {"token": "point72", "name": "Point72"},
        {"token": "imc", "name": "IMC"},
        {"token": "optiverus", "name": "Optiver"},
        {"token": "virtu", "name": "Virtu Financial"},
        {"token": "akunacapital", "name": "Akuna Capital"},
        {"token": "flowtraders", "name": "Flow Traders"},
        {"token": "aqr", "name": "AQR"},
        {"token": "mangroup", "name": "Man Group"},
        {"token": "worldquant", "name": "WorldQuant"},
        {"token": "pdtpartners", "name": "PDT Partners"},
        {"token": "gsacapital", "name": "GSA Capital"},
        {"token": "winton", "name": "Winton"},
        {"token": "sofi", "name": "SoFi"},
        {"token": "adyen", "name": "Adyen"},
        {"token": "chime", "name": "Chime"},
    ]
    extra_lever = [
        {"token": "spotify", "name": "Spotify"},
        {"token": "palantir", "name": "Palantir"},
        {"token": "zoox", "name": "Zoox"},
        {"token": "theathletic", "name": "The Athletic"},
    ]
    extra_ashby = [
        {"token": "openai", "name": "OpenAI"},
        {"token": "notion", "name": "Notion"},
        {"token": "ramp", "name": "Ramp"},
        {"token": "linear", "name": "Linear"},
        {"token": "cursor", "name": "Cursor"},
        {"token": "plaid", "name": "Plaid"},
        {"token": "replit", "name": "Replit"},
        {"token": "cohere", "name": "Cohere"},
        {"token": "perplexity", "name": "Perplexity"},
        {"token": "anthropic", "name": "Anthropic"},
        {"token": "vercel", "name": "Vercel"},
        {"token": "snowflake", "name": "Snowflake"},
    ]

    def merge(vendor: str, extra: list[dict]) -> list[dict]:
        have = {b["token"].lower() for b in grouped[vendor]}
        out = list(grouped[vendor])
        for b in extra:
            if b["token"].lower() not in have:
                out.append(b)
        out.sort(key=lambda x: x["name"].lower())
        return out

    data = {
        "greenhouse": merge("greenhouse", extra_gh),
        "lever": merge("lever", extra_lever),
        "ashby": merge("ashby", extra_ashby),
        "workday": WORKDAY,
        "smartrecruiters": SMARTRECRUITERS,
    }
    out = ROOT / "ats_boards.yaml"
    dump_yaml(out, data)
    print(
        f"Wrote {out} "
        f"gh={len(data['greenhouse'])} lever={len(data['lever'])} "
        f"ashby={len(data['ashby'])} workday={len(data['workday'])} "
        f"sr={len(data['smartrecruiters'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
