import argparse
import csv
import json
import os
import re
import time
from typing import Dict, List, Optional
from urllib.parse import urlparse

from linkedin_api import Linkedin


BASE_DIR = os.path.dirname(__file__)
SESSION_FILE = os.path.join(BASE_DIR, ".li_session.json")
COOKIES_DIR = os.path.join(BASE_DIR, ".li_cookies")

DEFAULT_KEYWORDS = [
    "looking for app developer",
    "need website developer",
    "seeking software development company",
    "hire mobile app development team",
]

INTENT_PATTERNS = [
    r"\blooking for\b",
    r"\bneed\b",
    r"\bseeking\b",
    r"\bhiring\b",
    r"\bwant to build\b",
    r"\bbuild(ing)? an app\b",
    r"\bapp development\b",
    r"\bsoftware development\b",
    r"\bdevelopment agency\b",
]

BUYER_PATTERNS = [
    r"\bfounder\b",
    r"\bco[- ]founder\b",
    r"\bceo\b",
    r"\bcto\b",
    r"\bproduct manager\b",
    r"\bowner\b",
    r"\bdirector\b",
    r"\bentrepreneur\b",
    r"\bstartup\b",
    r"\bhead of\b",
]

NON_BUYER_PATTERNS = [
    r"\bsoftware engineer\b",
    r"\bdeveloper\b",
    r"\bfull[- ]stack\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bmobile developer\b",
    r"\bflutter\b",
    r"\breact\b",
    r"\bnode\.?js\b",
    r"\bdevops\b",
    r"\bagency owner\b",
    r"\bmarketing agency\b",
    r"\bfreelancer\b",
]

INDIA_LOCATION_HINTS = [
    "india",
    "mumbai",
    "delhi",
    "new delhi",
    "bengaluru",
    "bangalore",
    "hyderabad",
    "pune",
    "chennai",
    "kolkata",
    "ahmedabad",
    "gurgaon",
    "noida",
    "kochi",
    "jaipur",
    "bhubaneswar",
    "surat",
    "indore",
    "lucknow",
    "nagpur",
    "chandigarh",
    "coimbatore",
    "vadodara",
    "thiruvananthapuram",
    "vijayawada",
    "visakhapatnam",
    "patna",
    "rajkot",
    "ludhiana",
    "agra",
    "nashik",
    "faridabad",
    "ghaziabad",
    "amritsar",
    "kanpur",
    "bhopal",
]


def load_session() -> Dict:
    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(f"Session not found: {SESSION_FILE}")
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def build_api_from_session(session_data: Dict) -> Linkedin:
    if session_data.get("method") == "password":
        return Linkedin(
            session_data["email"],
            session_data["password"],
            cookies_dir=COOKIES_DIR,
        )

    api = Linkedin("", "", authenticate=False)
    jsessionid = session_data["jsessionid"].replace('"', "")
    api.client.session.cookies.set("li_at", session_data["li_at"], domain=".linkedin.com")
    api.client.session.cookies.set("JSESSIONID", jsessionid, domain=".linkedin.com")
    api.client.session.headers["csrf-token"] = jsessionid
    return api


def extract_public_id(profile_url: str) -> str:
    if not profile_url:
        return ""
    path = urlparse(profile_url).path.strip("/")
    if not path.startswith("in/"):
        return ""
    parts = path.split("/")
    return parts[1] if len(parts) > 1 else ""


def clean_profile_url(profile_url: str) -> str:
    if not profile_url:
        return ""
    parsed = urlparse(profile_url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def has_pattern(text: str, patterns: List[str]) -> bool:
    low = (text or "").lower()
    return any(re.search(p, low) for p in patterns)


def is_india_location(location: str) -> bool:
    low = (location or "").lower()
    return any(hint in low for hint in INDIA_LOCATION_HINTS)


def is_non_buyer_profile(text: str) -> bool:
    return has_pattern(text, NON_BUYER_PATTERNS)


def location_matches_any(location: str, keywords: List[str]) -> bool:
    if not keywords:
        return True
    low = (location or "").lower()
    return any(k.lower() in low for k in keywords)


def normalize_distance(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return raw.replace("DISTANCE_", "") + "nd" if raw.startswith("DISTANCE_2") else (
        raw.replace("DISTANCE_", "") + "rd" if raw.startswith("DISTANCE_3") else (
            raw.replace("DISTANCE_", "") + "st" if raw.startswith("DISTANCE_1") else raw
        )
    )


def contact_to_flat(contact: Dict) -> Dict:
    phones = contact.get("phone_numbers") or []
    websites = contact.get("websites") or []
    twitter = contact.get("twitter")
    return {
        "email": contact.get("email_address") or "",
        "phones": "; ".join(phones) if phones else "",
        "websites": "; ".join(websites) if websites else "",
        "twitter": twitter or "",
    }


def build_leads(
    api: Linkedin,
    keywords: List[str],
    per_keyword_limit: int,
    india_only: bool,
    non_india_only: bool,
    target_location_keywords: List[str],
    include_without_contact: bool,
    min_score: int,
    delay_sec: float,
) -> List[Dict]:
    leads: List[Dict] = []
    seen = set()

    for kw in keywords:
        print(f"[search] {kw}")
        try:
            rows = api.search({"keywords": kw}, limit=per_keyword_limit)
        except Exception as exc:
            print(f"[warn] search failed for '{kw}': {exc}")
            continue

        for item in rows:
            title = ((item.get("title") or {}).get("text") or "").strip()
            headline = ((item.get("primarySubtitle") or {}).get("text") or "").strip()
            location = ((item.get("secondarySubtitle") or {}).get("text") or "").strip()
            profile_url = clean_profile_url(item.get("navigationUrl") or "")
            public_id = extract_public_id(profile_url)
            if not public_id:
                continue
            if public_id in seen:
                continue

            combined = f"{title} {headline} {kw}"
            intent_hit = has_pattern(combined, INTENT_PATTERNS)
            buyer_hit = has_pattern(combined, BUYER_PATTERNS)
            non_buyer_hit = is_non_buyer_profile(combined)
            score = (2 if intent_hit else 0) + (1 if buyer_hit else 0)

            if india_only and not is_india_location(location):
                continue
            if non_india_only and is_india_location(location):
                continue
            if not location_matches_any(location, target_location_keywords):
                continue
            if non_buyer_hit:
                continue
            if score < min_score:
                continue

            contact = {}
            try:
                contact = api.get_profile_contact_info(public_id=public_id)
            except Exception:
                contact = {}

            flat = contact_to_flat(contact)
            has_contact = any([flat["email"], flat["phones"], flat["websites"], flat["twitter"]])
            if not include_without_contact and not has_contact:
                continue

            distance = ""
            tracking = item.get("entityCustomTrackingInfo") or {}
            if tracking:
                distance = normalize_distance(tracking.get("memberDistance", ""))

            lead = {
                "name": title,
                "headline": headline,
                "location": location,
                "profile_url": profile_url,
                "public_id": public_id,
                "distance": distance,
                "source_keyword": kw,
                "intent_match": intent_hit,
                "buyer_role_match": buyer_hit,
                "non_buyer_match": non_buyer_hit,
                "score": score,
                **flat,
            }
            leads.append(lead)
            seen.add(public_id)
            print(f"[lead] {title} | {location} | contact={has_contact}")
            time.sleep(delay_sec)

    return leads


def write_csv(path: str, rows: List[Dict]) -> None:
    cols = [
        "name",
        "headline",
        "location",
        "profile_url",
        "public_id",
        "distance",
        "source_keyword",
        "intent_match",
        "buyer_role_match",
        "non_buyer_match",
        "score",
        "email",
        "phones",
        "websites",
        "twitter",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in cols})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find LinkedIn leads likely seeking software/app development companies."
    )
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=DEFAULT_KEYWORDS,
        help="Search keywords. Example: --keywords \"looking for app development company india\"",
    )
    parser.add_argument("--per-keyword-limit", type=int, default=25)
    parser.add_argument("--india-only", action="store_true", default=False)
    parser.add_argument("--non-india-only", action="store_true", default=True)
    parser.add_argument(
        "--target-location-keywords",
        nargs="*",
        default=[],
        help="Only keep leads whose location contains one of these terms.",
    )
    parser.add_argument("--include-without-contact", action="store_true", default=False)
    parser.add_argument("--min-score", type=int, default=2)
    parser.add_argument("--delay-sec", type=float, default=0.3)
    parser.add_argument("--csv", default="india_leads.csv")
    parser.add_argument("--json", default="india_leads.json")
    args = parser.parse_args()

    session_data = load_session()
    api = build_api_from_session(session_data)

    leads = build_leads(
        api=api,
        keywords=args.keywords,
        per_keyword_limit=args.per_keyword_limit,
        india_only=args.india_only,
        non_india_only=args.non_india_only,
        target_location_keywords=args.target_location_keywords,
        include_without_contact=args.include_without_contact,
        min_score=args.min_score,
        delay_sec=args.delay_sec,
    )

    leads.sort(key=lambda x: x.get("score", 0), reverse=True)
    write_csv(args.csv, leads)
    with open(args.json, "w", encoding="utf-8") as f:
        json.dump(leads, f, indent=2, ensure_ascii=False)

    print(f"[done] leads: {len(leads)}")
    print(f"[done] csv: {os.path.abspath(args.csv)}")
    print(f"[done] json: {os.path.abspath(args.json)}")


if __name__ == "__main__":
    main()
