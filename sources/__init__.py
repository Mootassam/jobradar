"""Job sources. Every source yields *raw* job dicts; engine.normalize() cleans them.

Raw job dict keys (all optional except title):
  title, company, company_url, location, country_hint, remote, description_html | description,
  url, apply_url, posted_at (ts or str), job_type, salary_min, salary_max, salary_currency, salary_text, tags
"""


import synonyms


class Query:
    def __init__(self, keywords="", country="", region="", city="", remote="any", days=0, job_type="",
                 max_per_source=500, match_description=False, include_worldwide=False, multilingual=True):
        self.keywords = (keywords or "").strip()
        self.country = (country or "").upper()
        self.region = (region or "").strip()
        self.city = (city or "").strip()
        self.remote = remote if remote in ("any", "remote", "onsite") else "any"
        self.days = int(days or 0)
        self.job_type = job_type or ""
        self.max_per_source = max(20, min(int(max_per_source or 500), 5000))
        self.match_description = bool(match_description)
        self.include_worldwide = bool(include_worldwide)
        self.multilingual = bool(multilingual)
        self._match_groups = None

    @property
    def match_groups(self):
        """Groups used to match jobs locally - expanded to every language when multilingual is on."""
        if self._match_groups is None:
            self._match_groups = synonyms.expand_groups(self.groups) if self.multilingual else self.groups
        return self._match_groups

    @property
    def groups(self):
        """'react developer, vue' -> [['react','developer'], ['vue']] (OR of ANDs)."""
        out = []
        for part in self.keywords.split(","):
            words = [w for w in part.lower().split() if w]
            if words:
                out.append(words)
        return out

    @property
    def search_terms(self):
        """Phrases to send to APIs that support server-side search (plus translations for the country's languages)."""
        if not self.groups:
            return [""]
        if self.multilingual:
            return synonyms.server_terms(self.groups, self.country, max_terms=max(4, len(self.groups)))
        return [" ".join(g) for g in self.groups]

    def to_dict(self):
        return dict(keywords=self.keywords, country=self.country, region=self.region, city=self.city, remote=self.remote,
                    days=self.days, job_type=self.job_type, max_per_source=self.max_per_source,
                    match_description=self.match_description, include_worldwide=self.include_worldwide,
                    multilingual=self.multilingual)


class Ctx:
    """Passed to sources: settings, stop flag and progress reporting."""

    def __init__(self, settings, stop, report, match=None):
        self.settings = settings
        self.stop = stop
        self.report = report      # report(message) -> None
        self.match = match        # match(raw_job) -> bool, lets big sources filter early
        self.checkpoint = set()   # ids already processed in an earlier (interrupted) part of this run
        self.board_done = None    # callback(board_id) to record progress for resume

    @property
    def stopped(self):
        return self.stop.is_set()


class Source:
    id = ""
    name = ""
    kind = "board"            # board | ats | keyed | crawler
    homepage = ""
    about = ""
    coverage = ""
    needs = ()                # settings keys required, e.g. ("adzuna_app_id", "adzuna_app_key")
    default_on = True
    server_search = False     # True = the API already filtered by keywords; don't re-filter on title

    def ready(self, settings):
        return all(settings.get(k) for k in self.needs)

    def search(self, query, ctx):
        raise NotImplementedError

    def info(self, settings):
        return {"id": self.id, "name": self.name, "kind": self.kind, "homepage": self.homepage, "about": self.about,
                "coverage": self.coverage, "needs": list(self.needs), "ready": self.ready(settings), "default_on": self.default_on}


def all_sources():
    from . import boards, ats, keyed, crawler, national
    return [national.NationalBoards(), ats.CompanyBoards(), boards.Remotive(), boards.RemoteOK(), boards.Jobicy(),
            boards.Himalayas(), boards.Arbeitnow(), boards.WorkingNomads(), boards.WeWorkRemotely(), keyed.Careerjet(),
            keyed.ReliefWeb(), keyed.Adzuna(), keyed.Jooble(), keyed.USAJobs(), crawler.CareerSites()]
