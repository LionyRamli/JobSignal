"""Every word the dashboard shows, in English and Traditional Chinese (繁體中文).

One home for UI copy, so a label and its tooltip never drift apart and tests can prove that
both languages say the same things (same keys, same {placeholders}). Codes stay codes in the
data and the API; they become business words only here, at the edge of the screen. Scraped
data (company tokens, job titles, cities) is never translated.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple


class Term(NamedTuple):
    label: str
    help: str


@dataclass(frozen=True)
class Copy:
    """All on-screen words in one language. Templates use str.format placeholders."""

    lang: str
    detector: Mapping[str, str]
    direction: Mapping[str, str]
    band: Mapping[str, str]
    level: Mapping[str, str]
    score_status: Mapping[str, str]
    snapshot_status: Mapping[str, str]
    health: Mapping[str, str]
    codes: Mapping[str, str]  # taxonomy codes (role family, seniority, location kind)
    alert_table: Mapping[str, Term]
    company_table: Mapping[str, Term]
    postings_table: Mapping[str, Term]
    runs_table: Mapping[str, Term]
    controls: Mapping[str, Term]  # by widget key
    kpis: Mapping[str, Term]
    chart: Mapping[str, str]
    chart_help: Mapping[str, str]
    text: Mapping[str, str]
    guide_title: str
    guide: str
    error_prefix: str  # before the client's technical message (English stays as is)
    date_format: str  # table date columns (moment.js tokens)
    datetime_format: str
    week_axis: str  # chart week labels (d3 time format)

    def pretty(self, code: str | None) -> str:
        """A taxonomy code as words; an unknown future code still reads as words."""
        if not code:
            return "—"
        return self.codes.get(code) or code.replace("_", " ").title()


LANGUAGE_LABEL = "Language / 語言"  # the same in both languages: findable by everyone
LANGUAGES = {"en": "English", "zh-Hant": "繁體中文"}

# ---------------------------------------------------------------------------------- English

_Z_HELP = (
    "How far this week is from the company's normal hiring. 0 = business as usual. "
    "3 or more (either way) = unusual, so we raise an alert; beyond 5 = extreme. "
    "Plus = more hiring than normal, minus = less."
)
_TREND = "Trend (Expansion vs. Hiring Freeze)"

EN = Copy(
    lang="en",
    detector={"volume": "Total Hiring Volume", "mix_shift": "Strategic Focus Shift / Role Share"},
    direction={"expansion": "▲ Expansion", "contraction": "▼ Contraction"},
    band={"red": "Extreme", "yellow": "Unusual", "none": "Below alert level"},
    level={
        "company": "Whole company",
        "company_family": "By role family",
        "company_country": "By country",
        "company_family_country": "By role family & country",
    },
    score_status={
        "scored": "scored",
        "insufficient_history": "not enough history",
        "below_min_count": "too few postings",
    },
    snapshot_status={"ok": "OK", "partial": "Incomplete", "failed": "Failed"},
    health={"ok": "OK", "schema_missing": "Database not set up"},
    codes={
        "software_engineering": "Software Engineering",
        "ml_research": "ML Research",
        "data": "Data",
        "solutions_engineering": "Solutions Engineering",
        "security": "Security",
        "product_management": "Product Management",
        "program_management": "Program Management",
        "design": "Design",
        "sales": "Sales",
        "customer_success": "Customer Success",
        "marketing": "Marketing",
        "operations": "Operations",
        "finance": "Finance",
        "legal": "Legal",
        "people": "People (HR)",
        "other": "Other",
        "intern": "Intern",
        "entry": "Entry",
        "mid": "Mid",
        "senior": "Senior",
        "staff_plus": "Staff+",
        "manager": "Manager",
        "director_plus": "Director+",
        "city": "City",
        "region": "Region",
        "country": "Country",
        "remote": "Remote",
    },
    alert_table={
        "id": Term("#", "Alert reference number. Pick it under 'Inspect an alert' below."),
        "band": Term(
            "Alert Level",
            "Extreme = Anomaly Score beyond ±5. Unusual = between ±3 and ±5. "
            "Below alert level = shown for context only.",
        ),
        "company": Term("Company", "The company whose job postings changed."),
        "cell": Term(
            "Where (Role · Country)",
            "Which part of the company's hiring this is about: a type of role, a country, "
            "both, or the whole company.",
        ),
        "detector": Term(
            "Signal Type",
            "Total Hiring Volume (Total Hiring Growth / Expansion): the company is posting far "
            "more, or far fewer, new jobs than usual. Strategic Focus Shift / Role Share: the "
            "mix of its jobs changed, e.g. a bigger share of sales roles, a hint at new "
            "priorities.",
        ),
        "direction": Term(
            _TREND,
            "▲ Expansion: hiring more than usual (growth, a new team, a new market). "
            "▼ Contraction: hiring less than usual, an early sign of a slowdown or hiring freeze.",
        ),
        "z": Term("Anomaly Score (Z)", _Z_HELP),
        "dz_prev_week": Term(
            "Score Change vs Last Week",
            "How much the Anomaly Score moved since last week. A growing number means the "
            "change is picking up speed.",
        ),
        "observed": Term(
            "This Week",
            "Total Hiring Volume: new job postings this week. Role Share: the share of the "
            "company's recent postings in this role or country.",
        ),
        "baseline": Term(
            "Normal Level",
            "What is typical: the average of earlier weeks (volume) or the earlier share "
            "(role share). The alert compares this week against it.",
        ),
        "d_baseline": Term(
            "vs Normal",
            "This week minus the normal level: extra (or missing) postings for volume, "
            "percentage points for role share.",
        ),
        "trend": Term(
            "8-Week Trend",
            "The weekly numbers for the last 8 weeks. Weeks without complete data are skipped.",
        ),
        "week": Term("Week Of", "The week (starting Monday) this alert is about."),
        "provisional": Term(
            "Provisional",
            "Ticked = an early lead based on job posting dates, which can be skewed. "
            "Check it before acting on it.",
        ),
        "also_at": Term(
            "Also Seen At",
            "Other slices of the same company where the same change shows up, e.g. the whole "
            "company as well as one country.",
        ),
    },
    company_table={
        "company": Term("Company", "A company whose job board we track."),
        "open_postings": Term("Open Roles Now", "Jobs currently advertised by the company."),
        "d_open_prev_week": Term(
            "Change vs Last Week", "Open roles now minus last week. Blank = not enough data yet."
        ),
        "open_trend": Term(
            "Open Roles (12 Weeks)",
            "How many jobs were open each week. Weeks without complete data are skipped.",
        ),
        "new_trend": Term(
            "New Roles Posted (12 Weeks)",
            "How many new jobs appeared each week: the pace of hiring.",
        ),
        "last_scrape": Term("Last Data Refresh", "When we last read the company's job board."),
        "status": Term(
            "Refresh Status",
            "OK = the last refresh read every job. Incomplete or Failed = it did not finish, "
            "so numbers may be behind.",
        ),
        "stale": Term(
            "Data Out of Date",
            "Ticked = no complete refresh in the last 36 hours, so numbers may be behind.",
        ),
    },
    postings_table={
        "title": Term("Job Title", "The job title exactly as the company wrote it."),
        "role_family": Term("Role Family", "The type of role, sorted into broad groups."),
        "seniority": Term("Seniority", "The career level, read from the job title."),
        "locations": Term("Locations", "Where the job is based (some jobs list several)."),
        "first_seen_at": Term("First Seen", "When this job first appeared on the board."),
        "url": Term("Job Link", "Opens the original job ad on the company's site."),
    },
    runs_table={
        "id": Term("Run #", "Each run checks the latest hiring data for unusual changes."),
        "as_of": Term("Data As Of", "The point in time the run analysed."),
        "computed_at": Term("Computed At", "When the run itself happened."),
        "signals_version": Term(
            "Detection Rules", "Version of the rules that decide what counts as unusual."
        ),
        "taxonomy_version": Term(
            "Job Classification Rules",
            "Version of the rules that sort jobs into roles and places.",
        ),
    },
    controls={
        "refresh": Term(
            "Refresh now",
            "Fetch the newest data now. Otherwise the dashboard refreshes every minute.",
        ),
        "run": Term(
            "Analysis run",
            "Which analysis to show. Each run checks the latest job postings for unusual "
            "changes; 'Latest run' is the most recent one.",
        ),
        "detector": Term(
            "Signal Type",
            "What kind of change to look for. Total Hiring Volume (Total Hiring Growth / "
            "Expansion): far more or fewer new jobs than usual. Strategic Focus Shift / Role "
            "Share: the mix of jobs changed.",
        ),
        "direction": Term(
            _TREND,
            "Expansion = hiring more than usual. Contraction = hiring less than usual, an early "
            "sign of a slowdown or hiring freeze.",
        ),
        "level": Term(
            "Breakdown",
            "How finely each company's hiring is sliced: the whole company, one type of role, "
            "one country, or one type of role in one country.",
        ),
        "company_filter": Term("Company", "Show alerts for one company only."),
        "min_abs_z": Term(
            "Minimum Anomaly Score (Z)",
            "Hide weaker signals. " + _Z_HELP + " The slider ignores the sign, so it works "
            "for expansions and contractions alike.",
        ),
        "include_all": Term(
            "Show all scores, not just alerts",
            "Off: alerts only. On: every score we computed, including normal weeks, for context.",
        ),
        "inspect": Term(
            "Alert", "Pick an alert to see its weekly history and the job postings behind it."
        ),
        "company_view": Term(
            "Company", "Pick a company to see what kinds of roles it is hiring for, and where."
        ),
        "role_family_filter": Term(
            "Role family", "Show only one type of role, e.g. Sales or Software Engineering."
        ),
        "seniority_filter": Term(
            "Seniority", "Show only one career level, e.g. Senior or Director+."
        ),
        "country_filter": Term(
            "Country",
            "Show only jobs in one country. Lists the countries this company hires in.",
        ),
        "load_more": Term("Load {count} more", "Show the next batch of job postings."),
    },
    kpis={
        "alerts": Term(
            "Active Alerts",
            "Unusual hiring changes found in this run. The small number below compares with "
            "last week's run.",
        ),
        "expansions": Term(
            "Expansion Signals",
            "Alerts where a company is hiring MORE than usual: often growth, a new team or a "
            "new market. Green = more than last week.",
        ),
        "contractions": Term(
            "Contraction Signals",
            "Alerts where a company is hiring LESS than usual: an early warning of a slowdown "
            "or hiring freeze. Red = more than last week.",
        ),
        "companies": Term(
            "Companies Flagged", "How many different companies have at least one alert."
        ),
        "open_roles": Term("Open Roles Now", "Jobs this company is advertising right now."),
        "api_status": Term(
            "API Status", "Whether the data service behind this dashboard is up (OK)."
        ),
        "taxonomy": Term(
            "Job Classification Rules",
            "Version of the rules that sort jobs into roles and places.",
        ),
        "signals": Term(
            "Detection Rules", "Version of the rules that decide what counts as unusual."
        ),
    },
    chart={
        "z_axis": "Anomaly Score (Z) · 0 = normal hiring",
        "value_share": "Share of new postings",
        "value_volume": "New postings per week",
        "in_slice": " in this slice",
        "normal_band": " · shaded band = normal range",
        "score_title": "Anomaly Score · dashed = alert levels",
        "normal_from": "Normal range from",
        "normal_to": "Normal range to",
        "open_roles": "Open roles",
        "composition_title": "Open roles by {dimension}",
        "unclassified": "Unclassified",
    },
    chart_help={
        "z_chart": (
            "How to read: one bar per alert. Right of centre = hiring more than usual, left = "
            "less. The longer the bar, the more unusual. Dashed lines mark the alert level "
            "(±3) and the extreme level (±5)."
        ),
        "trend_chart": (
            "How to read: the top chart is the actual weekly number; the shaded band is the "
            "normal range, so a point above or below it is unusual. The bottom chart shows "
            "the same weeks as an Anomaly Score; past a dashed line means an alert. Gaps = "
            "weeks without complete data."
        ),
        "composition": (
            "How to read: where this company's open jobs are today, by type of role, career "
            "level and country. The biggest bars show where it is investing in people."
        ),
    },
    text={
        "title": "JobSignal Terminal",
        "tagline": (
            "Spot expansion plans before they are announced: unusual changes in companies' "
            "job postings, updated daily."
        ),
        "sidebar_header": "Filters",
        "sidebar_hint": "Narrow down the alerts. Hover the ⓘ next to a filter for an explanation.",
        "theme_hint": (
            "Light or dark mode: open the ⋮ menu at the top right and pick Light, Dark or System."
        ),
        "language_help": "Show every word on the dashboard in English or Traditional Chinese.",
        "all": "All",
        "latest_run": "Latest run",
        "run_option": "#{id} · as of {asof} UTC",
        "run_caption": (
            "Run #{id} · data as of {asof} UTC · classification rules {taxonomy} · "
            "detection rules {signals}"
        ),
        "vs_last_week": "vs last week",
        "no_runs": "No signal runs yet. Run: {command}",
        "empty_run": "No alerts in this run with the current filters.",
        "alert_ranking": "Alert ranking",
        "all_alerts": "All alerts",
        "inspect_alert": "Inspect an alert",
        "top_scores": "Showing the {limit} strongest Anomaly Scores.",
        "trends_limited": "Trends shown for the top {limit} alerts.",
        "table_hint": "Hover a column heading for an explanation; click it to sort.",
        "no_signal": "no signal",
        "score": "Anomaly Score {z}",
        "score_na": "score n/a",
        "provisional": (
            "Provisional: an early lead, not proof. It is based on job posting dates, which "
            "can be skewed because roles that are filled quickly vanish from the board before "
            "we count them."
        ),
        "not_enough_history": "Not enough history yet",
        "postings_behind": "**Job postings behind this alert**",
        "technical_details": "Technical details: run parameters",
        "open_job_ad": "Open job ad ↗",
        "no_companies": "No companies tracked yet. Run: {command}",
        "company_overview": "Company overview",
        "company_overview_caption": (
            "One row per tracked company. Mini-charts show the last 12 weeks: green = rising, "
            "red = falling. Weeks without complete data are skipped."
        ),
        "company_deep_dive": "Company deep dive",
        "job_postings": "Job postings",
        "showing_postings": "Showing {count} postings · sorting applies to loaded rows{more}",
        "more_available": " · more available",
        "analysis_runs": "Analysis runs",
        "run_params": "Technical parameters of run #{id}",
        "stale": (
            "Data out of date: {companies}. Their job boards have not been fully read in the "
            "last 36 hours, so their numbers may be behind."
        ),
        "tab_alerts": "Alerts",
        "tab_companies": "Companies",
        "tab_runs": "Runs & health",
        "all_roles": "all roles",
        "all_countries": "all countries",
        "describe_volume": (
            "{prefix}: {observed} new postings in the week of {week}, vs a normal level of "
            "{mean} ± {std} a week (Anomaly Score Z = {z})"
        ),
        "describe_mix": (
            "{prefix}: {recent} of recent postings vs {baseline} before "
            "(Anomaly Score Z = {z}, provisional)"
        ),
        "describe_unscored": "{prefix}: not scored yet ({status})",
        "na": "n/a",
    },
    guide_title="New here? How to read this dashboard",
    guide="""\
**JobSignal watches companies' job postings and flags unusual changes: often the first \
public sign of an expansion, a new market or a slowdown.**

- **Anomaly Score (Z)**: how far this week's hiring is from the company's normal. \
0 = business as usual; **3 or more = alert**; **beyond 5 = extreme**. Plus = more hiring \
than normal, minus = less.
- **Trend**: **▲ Expansion** = hiring more than usual (growth, new teams, new offices). \
**▼ Contraction** = hiring less than usual (an early sign of a slowdown or hiring freeze).
- **Signal Type**: **Total Hiring Volume** (Total Hiring Growth / Expansion) counts new \
job postings: far more, or far fewer, than usual. **Strategic Focus Shift / Role Share** \
spots a change in the *mix* of jobs, e.g. a bigger share of sales roles.
- **Provisional**: an early lead based on posting dates, which can be skewed. Check it \
before acting on it.
- **Light or dark**: switch in the ⋮ menu at the top right.
- **Hover the ⓘ icons** next to any filter, number or column heading for an explanation.\
""",
    error_prefix="",
    date_format="MMM D, YYYY",
    datetime_format="MMM D, HH:mm",
    week_axis="%b %d",
)

# ------------------------------------------------------------------ 繁體中文 (Traditional)

_Z_HELP_ZH = (
    "本週招募偏離公司正常水準的程度。0＝一切如常。達 3 以上（正負皆同）＝異常，系統會發出"
    "警示；超過 5＝極端。正值＝招募多於平常，負值＝少於平常。"
)
_TREND_ZH = "趨勢（擴張 vs. 招募凍結）"

ZH = Copy(
    lang="zh-Hant",
    detector={"volume": "整體招募量", "mix_shift": "策略重心轉移／職務占比"},
    direction={"expansion": "▲ 擴張", "contraction": "▼ 收縮"},
    band={"red": "極端", "yellow": "異常", "none": "未達警示門檻"},
    level={
        "company": "全公司",
        "company_family": "依職務類別",
        "company_country": "依國家",
        "company_family_country": "依職務類別與國家",
    },
    score_status={
        "scored": "已評分",
        "insufficient_history": "歷史資料不足",
        "below_min_count": "職缺數過少",
    },
    snapshot_status={"ok": "正常", "partial": "不完整", "failed": "失敗"},
    health={"ok": "正常", "schema_missing": "資料庫尚未建立"},
    codes={
        "software_engineering": "軟體工程",
        "ml_research": "機器學習研究",
        "data": "資料",
        "solutions_engineering": "解決方案工程",
        "security": "資訊安全",
        "product_management": "產品管理",
        "program_management": "計畫管理",
        "design": "設計",
        "sales": "業務",
        "customer_success": "客戶成功",
        "marketing": "行銷",
        "operations": "營運",
        "finance": "財務",
        "legal": "法務",
        "people": "人力資源",
        "other": "其他",
        "intern": "實習",
        "entry": "初階",
        "mid": "中階",
        "senior": "資深",
        "staff_plus": "技術專家級以上",
        "manager": "經理",
        "director_plus": "總監級以上",
        "city": "城市",
        "region": "地區",
        "country": "國家",
        "remote": "遠端",
    },
    alert_table={
        "id": Term("編號", "警示參考編號。可在下方「檢視警示」中選取。"),
        "band": Term(
            "警示等級",
            "極端＝異常分數超過 ±5。異常＝介於 ±3 與 ±5 之間。未達警示門檻＝僅供參考。",
        ),
        "company": Term("公司", "職缺出現變化的公司。"),
        "cell": Term(
            "範圍（職務 · 國家）",
            "這項變化涉及公司招募的哪個部分：某類職務、某個國家、兩者兼具，或整間公司。",
        ),
        "detector": Term(
            "訊號類型",
            "整體招募量（整體招募成長／擴張）：公司刊登的新職缺遠多於或遠少於平常。"
            "策略重心轉移／職務占比：職缺組成改變，例如業務職缺占比提高，可能透露新的策略重點。",
        ),
        "direction": Term(
            _TREND_ZH,
            "▲ 擴張：招募多於平常（成長、新團隊或新市場）。"
            "▼ 收縮：招募少於平常，可能是業務放緩或招募凍結的早期徵兆。",
        ),
        "z": Term("異常分數 (Z)", _Z_HELP_ZH),
        "dz_prev_week": Term(
            "分數週變化", "異常分數相較上週的變動。數字持續擴大，代表變化正在加速。"
        ),
        "observed": Term(
            "本週數值",
            "整體招募量：本週新職缺數。職務占比：此職務或國家在公司近期職缺中的占比。",
        ),
        "baseline": Term(
            "正常水準",
            "平常的水準：過去數週的平均（招募量）或先前的占比（職務占比）。"
            "警示即以本週數值與此比較。",
        ),
        "d_baseline": Term(
            "與正常水準差異",
            "本週數值減去正常水準：招募量為多出（或減少）的職缺數，職務占比為百分點差。",
        ),
        "trend": Term("8 週趨勢", "最近 8 週的每週數值。資料不完整的週次會略過。"),
        "week": Term("週次", "此警示所屬的週（自週一起算）。"),
        "provisional": Term(
            "初步",
            "勾選＝依職缺刊登日期得出的早期線索，可能有偏差。採取行動前請先查證。",
        ),
        "also_at": Term(
            "亦出現於", "同一公司中也出現相同變化的其他範圍，例如整間公司以及某個國家。"
        ),
    },
    company_table={
        "company": Term("公司", "我們追蹤其職缺頁面的公司。"),
        "open_postings": Term("目前開放職缺", "公司目前刊登中的職缺數。"),
        "d_open_prev_week": Term("較上週變化", "目前開放職缺減去上週數值。空白＝資料尚不足。"),
        "open_trend": Term("開放職缺（12 週）", "每週的開放職缺數。資料不完整的週次會略過。"),
        "new_trend": Term("新增職缺（12 週）", "每週新出現的職缺數：反映招募步調。"),
        "last_scrape": Term("最近資料更新", "我們最近一次讀取該公司職缺頁面的時間。"),
        "status": Term(
            "更新狀態",
            "正常＝最近一次更新讀取了所有職缺。不完整或失敗＝更新未完成，數字可能落後。",
        ),
        "stale": Term("資料過期", "勾選＝過去 36 小時內沒有完整更新，數字可能落後。"),
    },
    postings_table={
        "title": Term("職稱", "公司原文刊登的職稱。"),
        "role_family": Term("職務類別", "職務的類型，依大類歸納。"),
        "seniority": Term("職級", "依職稱判斷的職涯層級。"),
        "locations": Term("工作地點", "職缺所在地（部分職缺列出多個地點）。"),
        "first_seen_at": Term("首次出現", "此職缺首次出現在職缺頁面的時間。"),
        "url": Term("職缺連結", "開啟公司網站上的原始職缺。"),
    },
    runs_table={
        "id": Term("批次編號", "每次分析都會檢查最新的招募資料是否出現異常變化。"),
        "as_of": Term("資料截至", "此次分析所依據的時間點。"),
        "computed_at": Term("計算時間", "此次分析實際執行的時間。"),
        "signals_version": Term("偵測規則", "判定何謂「異常」的規則版本。"),
        "taxonomy_version": Term("職缺分類規則", "將職缺歸入職務類別與地點的規則版本。"),
    },
    controls={
        "refresh": Term("立即更新", "立即取得最新資料；否則儀表板每分鐘自動更新。"),
        "run": Term(
            "分析批次",
            "要顯示哪一次分析。每次分析都會檢查最新職缺是否出現異常變化；「最新批次」為最近一次。",
        ),
        "detector": Term(
            "訊號類型",
            "要找哪一種變化。整體招募量（整體招募成長／擴張）：新職缺遠多於或遠少於平常。"
            "策略重心轉移／職務占比：職缺組成改變。",
        ),
        "direction": Term(
            _TREND_ZH,
            "擴張＝招募多於平常。收縮＝招募少於平常，可能是業務放緩或招募凍結的早期徵兆。",
        ),
        "level": Term(
            "細分層級",
            "公司招募資料的切分方式：整間公司、單一職務類別、單一國家，或某國家中的某類職務。",
        ),
        "company_filter": Term("公司", "只顯示單一公司的警示。"),
        "min_abs_z": Term(
            "最低異常分數 (Z)",
            "隱藏較弱的訊號。" + _Z_HELP_ZH + "此滑桿不分正負，擴張與收縮皆適用。",
        ),
        "include_all": Term(
            "顯示所有分數（不只警示）",
            "關閉：只顯示警示。開啟：顯示所有已計算的分數（含正常週次），以供參考。",
        ),
        "inspect": Term("警示", "選擇一則警示，查看每週走勢與背後的職缺。"),
        "company_view": Term("公司", "選擇一間公司，查看其正在招募的職務類型與地點。"),
        "role_family_filter": Term("職務類別", "只顯示某一類職務，例如業務或軟體工程。"),
        "seniority_filter": Term("職級", "只顯示某一職級，例如資深或總監級以上。"),
        "country_filter": Term("國家", "只顯示某一國家的職缺。清單列出此公司有招募的國家。"),
        "load_more": Term("再載入 {count} 筆", "顯示下一批職缺。"),
    },
    kpis={
        "alerts": Term("有效警示", "本次分析發現的異常招募變化。下方小字為與上週分析的比較。"),
        "expansions": Term(
            "擴張訊號",
            "公司招募「多於」平常的警示：常代表成長、新團隊或新市場。綠色＝比上週多。",
        ),
        "contractions": Term(
            "收縮訊號",
            "公司招募「少於」平常的警示：業務放緩或招募凍結的早期警訊。紅色＝比上週多。",
        ),
        "companies": Term("被標記公司", "至少有一則警示的公司數。"),
        "open_roles": Term("目前開放職缺", "此公司目前刊登中的職缺數。"),
        "api_status": Term("API 狀態", "儀表板背後的資料服務是否正常運作。"),
        "taxonomy": Term("職缺分類規則", "將職缺歸入職務類別與地點的規則版本。"),
        "signals": Term("偵測規則", "判定何謂「異常」的規則版本。"),
    },
    chart={
        "z_axis": "異常分數 (Z) · 0＝正常招募",
        "value_share": "新職缺占比",
        "value_volume": "每週新職缺數",
        "in_slice": "（此範圍）",
        "normal_band": " · 陰影帶＝正常範圍",
        "score_title": "異常分數 · 虛線＝警示門檻",
        "normal_from": "正常範圍下限",
        "normal_to": "正常範圍上限",
        "open_roles": "開放職缺",
        "composition_title": "依{dimension}統計的開放職缺",
        "unclassified": "未分類",
    },
    chart_help={
        "z_chart": (
            "閱讀方式：每則警示一條長條。中線右側＝招募多於平常，左側＝少於平常。"
            "長條越長越異常。虛線標示警示門檻（±3）與極端門檻（±5）。"
        ),
        "trend_chart": (
            "閱讀方式：上圖為每週實際數值，陰影帶為正常範圍，落在範圍外的點即為異常。"
            "下圖以異常分數呈現相同週次，超過虛線即觸發警示。空白＝該週資料不完整。"
        ),
        "composition": (
            "閱讀方式：此公司目前開放職缺的分布，依職務類別、職級與國家區分。"
            "最長的長條顯示其在人才上的投資重點。"
        ),
    },
    text={
        "title": "JobSignal 招募訊號終端",
        "tagline": "在企業正式宣布前搶先洞察擴張計畫：每日更新的企業職缺異常變化。",
        "sidebar_header": "篩選條件",
        "sidebar_hint": "縮小警示範圍。將滑鼠移到篩選條件旁的 ⓘ 可查看說明。",
        "theme_hint": (
            "淺色／深色模式：點選右上角 ⋮ 選單，選擇 Light（淺色）、Dark（深色）"
            "或 System（跟隨系統）。"
        ),
        "language_help": "將儀表板上的所有文字切換為英文或繁體中文。",
        "all": "全部",
        "latest_run": "最新批次",
        "run_option": "#{id} · 資料截至 {asof} UTC",
        "run_caption": (
            "批次 #{id} · 資料截至 {asof} UTC · 職缺分類規則 {taxonomy} · 偵測規則 {signals}"
        ),
        "vs_last_week": "較上週",
        "no_runs": "尚無分析批次。請執行：{command}",
        "empty_run": "在目前的篩選條件下，此批次沒有警示。",
        "alert_ranking": "警示排行",
        "all_alerts": "所有警示",
        "inspect_alert": "檢視警示",
        "top_scores": "顯示異常分數最強的 {limit} 筆。",
        "trends_limited": "僅顯示前 {limit} 則警示的趨勢。",
        "table_hint": "將滑鼠移到欄位標題可查看說明，點選可排序。",
        "no_signal": "無訊號",
        "score": "異常分數 {z}",
        "score_na": "無分數",
        "provisional": (
            "初步結果：僅為早期線索，並非定論。此結果依職缺刊登日期計算，可能有偏差，"
            "因為很快補齊的職缺會在我們統計前就從頁面消失。"
        ),
        "not_enough_history": "歷史資料尚不足",
        "postings_behind": "**此警示背後的職缺**",
        "technical_details": "技術細節：分析參數",
        "open_job_ad": "開啟職缺 ↗",
        "no_companies": "尚未追蹤任何公司。請執行：{command}",
        "company_overview": "公司總覽",
        "company_overview_caption": (
            "每列為一間追蹤中的公司。迷你圖顯示最近 12 週：綠色＝上升，紅色＝下降。"
            "資料不完整的週次會略過。"
        ),
        "company_deep_dive": "公司深入分析",
        "job_postings": "職缺",
        "showing_postings": "顯示 {count} 筆職缺 · 排序僅套用於已載入的資料{more}",
        "more_available": " · 尚有更多",
        "analysis_runs": "分析批次紀錄",
        "run_params": "批次 #{id} 的技術參數",
        "stale": ("資料過期：{companies}。過去 36 小時內未能完整讀取其職缺頁面，數字可能落後。"),
        "tab_alerts": "警示",
        "tab_companies": "公司",
        "tab_runs": "執行紀錄與系統狀態",
        "all_roles": "所有職務",
        "all_countries": "所有國家",
        "describe_volume": (
            "{prefix}：{week} 當週新增 {observed} 個職缺，正常水準為每週 {mean} ± {std} 個"
            "（異常分數 Z = {z}）"
        ),
        "describe_mix": (
            "{prefix}：近期職缺占比 {recent}，先前為 {baseline}（異常分數 Z = {z}，初步）"
        ),
        "describe_unscored": "{prefix}：尚未評分（{status}）",
        "na": "無資料",
    },
    guide_title="初次使用？儀表板閱讀指南",
    guide="""\
**JobSignal 持續追蹤企業的職缺刊登並標記異常變化：這往往是擴張、進軍新市場或業務放緩的\
第一個公開跡象。**

- **異常分數 (Z)**：本週招募偏離公司正常水準的程度。0＝一切如常；**3 以上＝警示**；\
**超過 5＝極端**。正值＝招募多於平常，負值＝少於平常。
- **趨勢**：**▲ 擴張**＝招募多於平常（成長、新團隊、新據點）。**▼ 收縮**＝招募少於平常\
（業務放緩或招募凍結的早期徵兆）。
- **訊號類型**：**整體招募量**（整體招募成長／擴張）計算新職缺數：遠多於或遠少於平常。\
**策略重心轉移／職務占比**偵測職缺「組成」的變化，例如業務職缺占比提高。
- **初步**：依刊登日期得出的早期線索，可能有偏差。採取行動前請先查證。
- **淺色／深色**：可在右上角 ⋮ 選單中切換。
- 將滑鼠移到任何篩選條件、數字或欄位標題旁的 **ⓘ** 圖示，即可查看說明。\
""",
    error_prefix="資料服務發生問題（技術細節如下）：",
    date_format="YYYY-MM-DD",
    datetime_format="YYYY-MM-DD HH:mm",
    week_axis="%m/%d",
)

COPIES = {"en": EN, "zh-Hant": ZH}


def copy_for(lang: str | None) -> Copy:
    """The words for a language code; anything unknown (or missing) reads as English."""
    return COPIES.get(lang or "", EN)
