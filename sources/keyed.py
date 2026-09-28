"""Big aggregators with official APIs that need a free API key (entered in Sources)."""
import geo
from net import fetch
from . import Source

ADZUNA_COUNTRIES = ("gb", "us", "at", "au", "be", "br", "ca", "ch", "de", "es", "fr", "in", "it", "mx", "nl", "nz", "pl", "sg", "za")


class Adzuna(Source):
    id, name, kind, homepage = "adzuna", "Adzuna", "keyed", "https://developer.adzuna.com"
    about = "Millions of jobs aggregated from thousands of sites, with salaries. Free API key (App ID + Key)."
    coverage = "19 countries: UK, US, DE, FR, ES, IT, NL, BE, AT, CH, PL, CA, AU, NZ, IN, SG, ZA, BR, MX"
    needs = ("adzuna_app_id", "adzuna_app_key")
    server_search = True

    def search(self, q, ctx):
        cc = q.country.lower()
        countries = [cc] if cc in ADZUNA_COUNTRIES else (["gb", "us", "de", "fr", "ca", "au", "in"] if not cc else [])
        if not countries:
            ctx.report("country not covered by Adzuna")
            return
        pages = max(1, min(10, q.max_per_source // 50 // len(countries)))
        n = 0
        for c in countries:
            for term in q.search_terms[:4]:
                for page in range(1, pages + 1):
                    if ctx.stopped:
                        return
                    p = {"app_id": ctx.settings["adzuna_app_id"], "app_key": ctx.settings["adzuna_app_key"],
                         "results_per_page": 50, "content-type": "application/json"}
                    if term:
                        p["what"] = term
                    where = q.city or q.region
                    if where:
                        p["where"] = where
                    if q.days:
                        p["max_days_old"] = q.days
                    data = fetch("https://api.adzuna.com/v1/api/jobs/%s/search/%d" % (c, page), params=p, stop=ctx.stop)
                    rows = data.get("results") or []
                    for j in rows:
                        n += 1
                        loc = j.get("location") or {}
                        area = loc.get("area") or []
                        yield {"title": j.get("title"), "company": (j.get("company") or {}).get("display_name") or "",
                               "location": loc.get("display_name") or ", ".join(reversed(area)), "country_hint": c.upper(),
                               "region": area[1] if len(area) > 1 else "", "description": j.get("description") or "",
                               "url": j.get("redirect_url"), "apply_url": j.get("redirect_url"), "posted_at": j.get("created"),
                               "salary_min": j.get("salary_min"), "salary_max": j.get("salary_max"),
                               "job_type": " ".join(x for x in (j.get("contract_time"), j.get("contract_type")) if x).replace("_", " "),
                               "tags": [(j.get("category") or {}).get("label")] if (j.get("category") or {}).get("label") else []}
                    ctx.report("%d jobs" % n)
                    if len(rows) < 50:
                        break


class Jooble(Source):
    id, name, kind, homepage = "jooble", "Jooble", "keyed", "https://jooble.org/api/about"
    about = "Worldwide job aggregator (70+ countries). Free API key on request."
    coverage = "Worldwide · 70+ countries"
    needs = ("jooble_key",)
    server_search = True

    def search(self, q, ctx):
        loc = ", ".join(x for x in (q.city, q.region, geo.country_name(q.country)) if x)
        pages = max(1, min(10, q.max_per_source // 20))
        n = 0
        for term in q.search_terms[:4]:
            for page in range(1, pages + 1):
                if ctx.stopped:
                    return
                body = {"keywords": term, "location": loc, "page": str(page)}
                data = fetch("https://jooble.org/api/%s" % ctx.settings["jooble_key"], method="POST", json_body=body, stop=ctx.stop)
                rows = data.get("jobs") or []
                for j in rows:
                    n += 1
                    yield {"title": j.get("title"), "company": j.get("company") or "", "location": j.get("location") or loc,
                           "country_hint": q.country, "description_html": j.get("snippet") or "", "url": j.get("link"),
                           "apply_url": j.get("link"), "posted_at": j.get("updated"), "salary_text": j.get("salary") or "",
                           "job_type": j.get("type") or "", "tags": [j.get("source")] if j.get("source") else []}
                ctx.report("%d jobs" % n)
                if len(rows) < 20:
                    break


class USAJobs(Source):
    id, name, kind, homepage = "usajobs", "USAJOBS", "keyed", "https://developer.usajobs.gov"
    about = "Official US federal government jobs. Free API key + your email."
    coverage = "United States (federal)"
    needs = ("usajobs_key", "usajobs_email")
    server_search = True

    def search(self, q, ctx):
        if q.country and q.country != "US":
            ctx.report("US only - skipped")
            return
        headers = {"Host": "data.usajobs.gov", "User-Agent": ctx.settings["usajobs_email"], "Authorization-Key": ctx.settings["usajobs_key"]}
        n = 0
        for term in q.search_terms[:4]:
            p = {"ResultsPerPage": min(500, q.max_per_source)}
            if term:
                p["Keyword"] = term
            where = q.city or q.region
            if where:
                p["LocationName"] = where
            if q.days:
                p["DatePosted"] = min(60, q.days)
            data = fetch("https://data.usajobs.gov/api/search", params=p, headers=headers, stop=ctx.stop)
            for it in ((data.get("SearchResult") or {}).get("SearchResultItems") or []):
                j = it.get("MatchedObjectDescriptor") or {}
                pay = (j.get("PositionRemuneration") or [{}])[0]
                details = ((j.get("UserArea") or {}).get("Details") or {})
                n += 1
                yield {"title": j.get("PositionTitle"), "company": j.get("OrganizationName") or j.get("DepartmentName") or "",
                       "location": j.get("PositionLocationDisplay") or "", "country_hint": "US",
                       "description": "\n\n".join(x for x in (details.get("JobSummary"), details.get("MajorDuties") and "\n".join(details["MajorDuties"])) if x),
                       "url": j.get("PositionURI"), "apply_url": (j.get("ApplyURI") or [j.get("PositionURI")])[0],
                       "posted_at": j.get("PublicationStartDate"), "salary_min": _f(pay.get("MinimumRange")),
                       "salary_max": _f(pay.get("MaximumRange")), "salary_currency": "USD",
                       "job_type": ", ".join(x.get("Name", "") for x in (j.get("PositionSchedule") or [])),
                       "emails": [details.get("AgencyContactEmail")] if details.get("AgencyContactEmail") else [],
                       "phones_raw": details.get("AgencyContactPhone") or ""}
            ctx.report("%d jobs" % n)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# Careerjet runs local job search engines in ~90 countries (careerjet.com, optioncarriere.tn / .ma / .dz, ...).
CAREERJET_LOCALES = {
    "US": "en_US", "GB": "en_GB", "CA": "en_CA", "AU": "en_AU", "NZ": "en_NZ", "IE": "en_IE", "IN": "en_IN", "ZA": "en_ZA",
    "SG": "en_SG", "MY": "en_MY", "PH": "en_PH", "PK": "en_PK", "BD": "en_BD", "AE": "en_AE", "SA": "en_SA", "QA": "en_QA",
    "KW": "en_KW", "OM": "en_OM", "HK": "en_HK", "CN": "zh_CN", "TW": "en_TW", "VN": "vi_VN", "JP": "ja_JP", "KR": "ko_KR",
    "FR": "fr_FR", "BE": "fr_BE", "CH": "de_CH", "LU": "fr_LU", "MA": "fr_MA", "TN": "fr_TN", "DZ": "fr_DZ",
    "DE": "de_DE", "AT": "de_AT", "NL": "nl_NL", "ES": "es_ES", "PT": "pt_PT", "IT": "it_IT", "PL": "pl_PL", "CZ": "cs_CZ",
    "SK": "sk_SK", "HU": "hu_HU", "SE": "sv_SE", "NO": "no_NO", "DK": "da_DK", "FI": "fi_FI", "TR": "tr_TR", "UA": "uk_UA",
    "RU": "ru_RU", "BR": "pt_BR", "MX": "es_MX", "AR": "es_AR", "CL": "es_CL", "CO": "es_CO", "PE": "es_PE", "EC": "es_EC",
    "UY": "es_UY", "VE": "es_VE", "CR": "es_CR", "PA": "es_PA", "DO": "es_DO", "GT": "es_GT", "PR": "es_PR",
}


class Careerjet(Source):
    id, name, kind, homepage = "careerjet", "Careerjet", "keyed", "https://www.careerjet.com/partners/"
    about = ("Job search engine with local sites in ~90 countries (e.g. optioncarriere.tn in Tunisia). "
             "Free partner/affiliate ID from careerjet.com/partners.")
    coverage = "~90 countries, local job sites"
    needs = ("careerjet_affid",)
    server_search = True

    def search(self, q, ctx):
        locale = CAREERJET_LOCALES.get(q.country, "en_GB")
        where = ", ".join(x for x in (q.city, q.region) if x) or (geo.country_name(q.country) if q.country not in CAREERJET_LOCALES else "")
        pages = max(1, min(20, q.max_per_source // 99 + 1))
        n = 0
        for term in q.search_terms[:4]:
            for page in range(1, pages + 1):
                if ctx.stopped:
                    return
                p = {"locale_code": locale, "keywords": term, "location": where, "affid": ctx.settings["careerjet_affid"],
                     "user_ip": "127.0.0.1", "user_agent": "JobRadar/1.0", "url": "http://127.0.0.1/", "pagesize": 99, "page": page,
                     "sort": "date"}
                data = fetch("http://public.api.careerjet.net/search", params=p, stop=ctx.stop)
                if data.get("type") == "ERROR":
                    raise RuntimeError(data.get("error") or "Careerjet error")
                rows = data.get("jobs") or []
                for j in rows:
                    n += 1
                    yield {"title": j.get("title"), "company": j.get("company") or "", "location": j.get("locations") or where,
                           "country_hint": q.country, "description_html": j.get("description") or "", "url": j.get("url"),
                           "apply_url": j.get("url"), "posted_at": j.get("date"), "salary_text": j.get("salary") or "",
                           "tags": [j.get("site")] if j.get("site") else []}
                ctx.report("%d jobs" % n)
                if page >= int(data.get("pages") or 1):
                    break


class ReliefWeb(Source):
    id, name, kind, homepage = "reliefweb", "ReliefWeb (UN & NGOs)", "keyed", "https://apidoc.reliefweb.int/parameters#appname"
    about = "Humanitarian and development jobs from the UN, NGOs and agencies in 150+ countries. Free approved app name."
    coverage = "150+ countries · strong in Africa, MENA, Asia"
    needs = ("reliefweb_appname",)
    server_search = True

    def search(self, q, ctx):
        n = 0
        for term in q.search_terms[:4]:
            offset = 0
            while offset < min(q.max_per_source, 1000):
                if ctx.stopped:
                    return
                body = {"limit": 200, "offset": offset, "sort": ["date.created:desc"], "profile": "full",
                        "fields": {"include": ["title", "body", "source.name", "country.name", "country.iso3", "city.name",
                                               "date.created", "url_alias", "url", "how_to_apply", "type.name"]}}
                conds = []
                if q.country:
                    conds.append({"field": "country.name", "value": geo.country_name(q.country)})
                if conds:
                    body["filter"] = {"operator": "AND", "conditions": conds}
                if term:
                    body["query"] = {"value": term, "fields": ["title^3", "body"], "operator": "AND"}
                data = fetch("https://api.reliefweb.int/v2/jobs", method="POST", params={"appname": ctx.settings["reliefweb_appname"]},
                             json_body=body, stop=ctx.stop)
                rows = data.get("data") or []
                for it in rows:
                    f = it.get("fields") or {}
                    countries = [c.get("name") for c in (f.get("country") or []) if c.get("name")]
                    cities = [c.get("name") for c in (f.get("city") or []) if c.get("name")]
                    n += 1
                    yield {"title": f.get("title"), "company": ", ".join(s.get("name", "") for s in (f.get("source") or [])[:2]),
                           "location": ", ".join(cities + countries), "country_list": countries,
                           "description": (f.get("body") or "") + "\n\nHow to apply:\n" + (f.get("how_to_apply") or ""),
                           "url": f.get("url_alias") or f.get("url"), "apply_url": f.get("url_alias") or f.get("url"),
                           "posted_at": (f.get("date") or {}).get("created"), "job_type": ", ".join(t.get("name", "") for t in (f.get("type") or []))}
                ctx.report("%d jobs" % n)
                if len(rows) < 200:
                    break
                offset += 200
