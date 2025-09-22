from __future__ import annotations
import os, math, re, json
from typing import Any, Dict, List, Optional, TypedDict
from pathlib import Path
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


load_dotenv(dotenv_path=Path(__file__).with_name(".env"))
YELP_API_KEY = os.getenv("YELP_API_KEY")

mcp = FastMCP("WhatToEat")

STATE: Dict[str, Dict[str, Any]] = {}
def _profile(p: str) -> Dict[str, Any]:
    return STATE.setdefault(p, {"prefs": {}, "last_query": None, "last_results": []})

class Location(TypedDict, total=False):
    # (lat,lon) or address
    latitude: float
    longitude: float
    address: str

class Preferences(TypedDict, total=False):
    cuisines: List[str]
    dietary: List[str]
    budget: str          # "$", "$$", "$$$", "$$$$"
    vibe: List[str]
    distance_km: float
    min_rating: float    # max = 5.0
    open_now: bool
    group_size: int 
    avoid: List[str]

class FindQuery(TypedDict, total=False):
    location: Location
    cuisines: List[str]
    dietary: List[str]
    budget: str
    vibe: List[str]
    distance_km: float
    min_rating: float
    open_now: bool
    keywords: List[str]
    limit: int

class Restaurant(TypedDict):
    id: str
    name: str
    rating: float
    review_count: int
    price: Optional[str]
    categories: List[str]
    url: str
    address: str
    distance_km: float
    phone: Optional[str]
    snippet: Optional[str]

class SearchResult(TypedDict):
    query_used: Dict[str, Any]
    restaurants: List[Restaurant]
    tips: List[str]

def _require_yelp_key() -> str:
    if not YELP_API_KEY:
        raise RuntimeError("Cannot find YELP_API_KEY.")
    return YELP_API_KEY

def _km(meters: float) -> float:
    return round(meters / 1000.0, 2)

def _join_address(loc: Dict[str, Any]) -> str:
    parts = [p for p in [
        loc.get("address1"), loc.get("address2"), loc.get("address3"),
        loc.get("city"), loc.get("state"), loc.get("zip_code")
    ] if p]
    return ", ".join(parts)

def _category_names(cats: List[Dict[str, Any]]) -> List[str]:
    return [c.get("title") for c in cats or []]

def _score_business(b: Dict[str, Any], query: FindQuery) -> float:
    rating = float(b.get("rating", 0))
    reviews = float(b.get("review_count", 0))
    dist_km = _km(float(b.get("distance", 0)))
    max_km = float(query.get("distance_km", 3.0))

    # Distance penalty
    dist_pen = 0.0 if dist_km <= max_km else -0.5 * (dist_km - max_km)

    # Price
    price = b.get("price")
    align = 0.0
    if "budget" in query and price:
        wanted = query["budget"]
        diff = abs(len(price) - len(wanted))
        align = max(0.0, 1.5 - 0.75 * diff)

    # Keyword
    kw_bonus = 0.0
    kws = set([k.lower() for k in query.get("keywords", [])])
    hay = (b.get("name","") + " " + " ".join(_category_names(b.get("categories",[])))).lower()
    matches = sum(1 for k in kws if k in hay)
    kw_bonus = 0.5 * matches
    
    # Review count diminishing returns
    review_term = min(2.0, math.log10(1 + reviews) / math.log10(500 + 1) * 2.0)
    return rating + review_term + dist_pen + align + kw_bonus

async def _yelp_search(query: FindQuery) -> List[Dict[str, Any]]:
    key = _require_yelp_key()
    headers = {"Authorization": f"Bearer {key}"}
    params: Dict[str, Any] = {
        "limit": min(int(query.get("limit", 12)), 50),
        "sort_by": "best_match",
    }
    # location
    loc = query.get("location", {})
    if "latitude" in loc and "longitude" in loc:
        params["latitude"] = loc["latitude"]
        params["longitude"] = loc["longitude"]
    elif "address" in loc and loc["address"]:
        params["location"] = loc["address"]
    else:
        raise ValueError("location required: either (latitude & longitude) or address")

    # radius
    radius_m = int( min( query.get("distance_km", 3.0) * 1000, 40000 ) )
    params["radius"] = max(100, radius_m)

    # categories
    cats: List[str] = []
    for c in query.get("cuisines", []) + query.get("dietary", []):
        cats.append(c)
    if cats:
        params["categories"] = ",".join(cats)

    if query.get("open_now", True):
        params["open_now"] = "true"

    # price mapping
    budget = query.get("budget")
    if budget and budget.count("$") in (1,2,3,4):
        params["price"] = str(budget.count("$"))

    # keyword & vibe search
    terms = []
    terms += query.get("keywords", [])
    terms += query.get("vibe", [])
    if terms:
        params["term"] = " ".join(terms)

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get("https://api.yelp.com/v3/businesses/search", headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
        return data.get("businesses", []) or []

async def _yelp_reviews(business_id: str) -> Optional[str]:
    key = _require_yelp_key()
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"https://api.yelp.com/v3/businesses/{business_id}/reviews", headers=headers)
            r.raise_for_status()
            js = r.json()
            reviews = js.get("reviews", [])
            if not reviews:
                return None
            text = reviews[0].get("text") or ""
            # trim to ~160 chars
            text = re.sub(r"\s+", " ", text).strip()
            return (text[:157] + "…") if len(text) > 160 else text
    except Exception:
        return None

def _filter_avoid(businesses: List[Dict[str, Any]], avoid: List[str]) -> List[Dict[str, Any]]:
    if not avoid:
        return businesses
    avoid_l = [a.lower() for a in avoid]
    out = []
    for b in businesses:
        hay = (b.get("name","") + " " + " ".join(_category_names(b.get("categories",[])))).lower()
        if any(a in hay for a in avoid_l):
            continue
        out.append(b)
    return out

def _to_restaurant(b: Dict[str, Any]) -> Restaurant:
    return {
        "id": b.get("id"),
        "name": b.get("name"),
        "rating": float(b.get("rating", 0)),
        "review_count": int(b.get("review_count", 0)),
        "price": b.get("price"),
        "categories": _category_names(b.get("categories", [])),
        "url": b.get("url"),
        "address": _join_address(b.get("location", {})),
        "distance_km": _km(float(b.get("distance", 0))),
        "phone": b.get("display_phone"),
        "snippet": None,
    }



@mcp.tool()
def set_dinner_prefs(preferences: Preferences, profile: str = "default") -> Dict[str, Any]:
    """
    Save/merge user dinner preferences for future queries and follow-ups.

    Example:
    {
      "preferences": {
         "cuisines": ["rice","curry"],
         "dietary": ["gluten-free"],
         "budget": "$$",
         "vibe": ["casual"],
         "distance_km": 2.0,
         "min_rating": 4.0,
         "open_now": true,
         "avoid": ["banana"]
      },
      "profile": "heathcl"
    }
    """
    st = _profile(profile)
    st["prefs"].update(preferences or {})
    return {"ok": True, "stored": st["prefs"]}

@mcp.tool()
async def find_dinner(query: FindQuery, profile: str = "default") -> SearchResult:
    """
    Find restaurants around a location that match constraints and preferences.

    Minimal:
      {"location": {"address": "Waterloo, ON"}}

    Optional fields:
      cuisines, dietary, budget ("$".."$$$$"), vibe, distance_km (float),
      min_rating (float), open_now (bool), keywords (list), limit (int)

    Returns a ranked list and stores context for follow-up queries.
    """
    st = _profile(profile)

    merged: FindQuery = {}
    merged.update(st.get("prefs", {}))
    merged.update({k:v for k,v in query.items() if v is not None})
    merged.setdefault("distance_km", 3.0)
    merged.setdefault("min_rating", 4.0)
    merged.setdefault("open_now", True)
    merged.setdefault("limit", 12)

    businesses = await _yelp_search(merged)
    businesses = _filter_avoid(businesses, merged.get("avoid", []))
    # Filter by min_rating
    min_rating = float(merged.get("min_rating", 0))
    businesses = [b for b in businesses if float(b.get("rating", 0)) >= min_rating]

    # Score & sort
    scored = sorted(businesses, key=lambda b: _score_business(b, merged), reverse=True)
    top = scored[: int(merged.get("limit", 12))]
    # Map to result & fetch review
    results: List[Restaurant] = [_to_restaurant(b) for b in top]
    for i in range(min(5, len(results))):
        results[i]["snippet"] = await _yelp_reviews(results[i]["id"])

    st["last_query"] = merged
    st["last_results"] = results

    tips: List[str] = []
    if not results:
        tips.append("Try widening distance_km, lowering min_rating, or removing avoid keywords.")
    else:
        tips.append("You can say things like: 'closer', 'cheaper', 'more spicy', 'kid-friendly', or 'not pizza'.")

    return {"query_used": merged, "restaurants": results, "tips": tips}

@mcp.tool()
def refine_dinner(instruction: str, profile: str = "default") -> SearchResult:
    """
    Refine the last results based on a natural-language instruction.
    Examples:
      "closer", "cheaper", "not pizza", "open later", "date night", "more spicy"
    """
    st = _profile(profile)
    last_q: Optional[FindQuery] = st.get("last_query")
    last_r: List[Restaurant] = st.get("last_results", [])
    if not last_q or not last_r:
        return {"query_used": {}, "restaurants": [], "tips": ["No prior result to refine. Call find_dinner first."]}

    q = dict(last_q)
    instr = instruction.lower()

    if "closer" in instr or "nearer" in instr:
        q["distance_km"] = max(0.5, float(q.get("distance_km", 3.0)) * 0.6)
    if "farther" in instr or "more options" in instr:
        q["distance_km"] = min(30.0, float(q.get("distance_km", 3.0)) * 1.5)
    if "cheaper" in instr or "less expensive" in instr or "budget" in instr:
        budget = q.get("budget")
        if budget:
            q["budget"] = "$" * max(1, len(budget) - 1)
        else:
            q["budget"] = "$"
    if "fancier" in instr or "nicer" in instr or "date night" in instr:
        q["vibe"] = list(set(q.get("vibe", []) + ["romantic", "date night"]))
        q["min_rating"] = max(float(q.get("min_rating", 4.0)), 4.3)
    if "kid" in instr or "family" in instr:
        q["vibe"] = list(set(q.get("vibe", []) + ["family"]))
    if "open now" in instr:
        q["open_now"] = True
    if "open late" in instr or "open later" in instr:
        q["open_now"] = True

    m = re.findall(r"(no|not)\s+([a-zA-Z\- ]+)", instr)
    if m:
        avoid = q.get("avoid", [])
        for _, term in m:
            avoid.append(term.strip())
        q["avoid"] = list(set(avoid))

    add_cuis = re.findall(r"(?:want|craving|more|prefer)\s+([a-zA-Z\- ]+)", instr)
    if add_cuis:
        cuisines = q.get("cuisines", [])
        for term in add_cuis:
            cuisines.append(term.strip())
        q["cuisines"] = list(set(cuisines))

    st["last_query"] = q

    # Rerank
    filtered = [r for r in last_r if not any(a.lower() in (r["name"] + " " + " ".join(r["categories"])).lower()
                    for a in q.get("avoid", []))]

    def _score_rest(r: Restaurant) -> float:
        fake_biz = {
            "name": r["name"],
            "rating": r["rating"],
            "review_count": r["review_count"],
            "distance": r["distance_km"] * 1000.0,
            "price": r.get("price"),
            "categories": [{"title": c} for c in r.get("categories", [])],
        }
        return _score_business(fake_biz, q)

    ranked = sorted(filtered, key=_score_rest, reverse=True)
    tips = ["Say 'search again' to fetch fresh options from Yelp with your refined query."]

    return {"query_used": q, "restaurants": ranked, "tips": tips}

@mcp.tool()
async def search_again(profile: str = "default") -> SearchResult:
    """
    Hit Yelp again using the current refined query in memory.
    """
    st = _profile(profile)
    q = st.get("last_query")
    if not q:
        return {"query_used": {}, "restaurants": [], "tips": ["No query in memory. Use find_dinner first."]}
    businesses = await _yelp_search(q)
    businesses = _filter_avoid(businesses, q.get("avoid", []))
    min_rating = float(q.get("min_rating", 0))
    businesses = [b for b in businesses if float(b.get("rating", 0)) >= min_rating]
    top = sorted(businesses, key=lambda b: _score_business(b, q), reverse=True)[: int(q.get("limit", 12))]
    results = [_to_restaurant(b) for b in top]
    st["last_results"] = results
    return {"query_used": q, "restaurants": results, "tips": ["Refined search complete."]}

@mcp.resource("dinner-memory://{profile}")
def memory_resource(profile: str = "default") -> str:
    st = _profile(profile)
    return json.dumps({"prefs": st["prefs"], "last_query": st["last_query"], "last_count": len(st["last_results"])}, ensure_ascii=False, indent=2)
