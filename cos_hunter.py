#!/usr/bin/env python3
"""UK CoS Job Hunter v1.0.

Discovery is intentionally broad: no job-title or skill filter.
A result is accepted only when the vacancy itself advertises sponsorship
and the employer can be verified on the official GOV.UK sponsor register.
"""
from __future__ import annotations
import csv, hashlib, io, json, os, re, sys, time
from dataclasses import dataclass, asdict
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup

REGISTER_PAGE="https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
REGISTER_CSV_FALLBACK="https://www.gov.uk/csv-preview/6aacebbdce3f006bd4346c6b/SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-09-18.csv"
UA="UK-CoS-Job-Hunter/1.0 (+https://github.com/SirAyo-IAM/cos)"
TIMEOUT=int(os.getenv("COS_HTTP_TIMEOUT","15"))
STATE=Path(os.getenv("COS_STATE_DIR",".cos_state"))/"seen_jobs.json"
MAX_CANDIDATES=int(os.getenv("COS_MAX_CANDIDATES","160"))
BRAVE=os.getenv("BRAVE_SEARCH_API_KEY","").strip()

POSITIVE=[
 r"certificate of sponsorship", r"\bcos\b.{0,40}(?:available|provided|offered|sponsor)",
 r"skilled worker (?:visa )?sponsorship", r"visa sponsorship (?:is )?(?:available|provided|offered)",
 r"(?:can|able to|will) sponsor (?:a |the |this )?(?:successful )?(?:candidate|applicant)",
 r"sponsorship (?:is )?available", r"eligible for sponsorship"
]
NEGATIVE=[
 r"(?:no|not) (?:visa )?sponsorship", r"sponsorship (?:is )?not available",
 r"(?:cannot|can't|unable to|will not|won't) (?:provide |offer )?(?:visa )?sponsorship",
 r"(?:cannot|can't|unable to) sponsor", r"does not offer sponsorship",
 r"must (?:already )?have (?:the )?(?:right|permission) to work in (?:the )?uk",
 r"without (?:the need for )?sponsorship"
]
UK_HINTS=("united kingdom"," uk ","england","scotland","wales","northern ireland","london","manchester","birmingham","leeds","glasgow","edinburgh","cardiff","belfast","bristol","liverpool","newcastle","sheffield","nottingham","cambridge","oxford")

@dataclass
class Job:
    title:str; employer:str; location:str; url:str; sponsorship_evidence:str
    sponsor_name:str; sponsor_town:str; sponsor_route:str; sponsor_rating:str
    match_score:float; first_seen:str=""; notification_status:str="NEW"

def get(url, **kw):
    h={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml,application/json,text/csv;q=0.9,*/*;q=0.8"}
    h.update(kw.pop("headers",{}))
    return requests.get(url,headers=h,timeout=TIMEOUT,allow_redirects=True,**kw)

def register_csv_url():
    try:
        r=get(REGISTER_PAGE); r.raise_for_status()
        soup=BeautifulSoup(r.text,"lxml")
        for a in soup.select("a[href]"):
            href=a.get("href","")
            if href.lower().endswith(".csv") and "assets.publishing.service.gov.uk" in href:
                return href
    except Exception as e: print("Register page lookup warning:",e)
    return REGISTER_CSV_FALLBACK

def load_register():
    url=register_csv_url(); r=get(url); r.raise_for_status()
    text=r.content.decode("utf-8-sig",errors="replace")
    rows=list(csv.DictReader(io.StringIO(text)))
    if not rows or "Organisation Name" not in rows[0]:
        raise RuntimeError("Sponsor register schema not recognised")
    print(f"Sponsor register: {len(rows):,} rows from {url}")
    return rows,url

def norm_company(s):
    s=(s or "").lower().replace("&"," and ")
    s=re.sub(r"\b(t/a|trading as|limited|ltd|plc|llp|uk|u\.k\.)\b"," ",s)
    return re.sub(r"[^a-z0-9]+"," ",s).strip()

def sponsor_match(company, rows):
    n=norm_company(company)
    if len(n)<3:return None
    exact=[x for x in rows if norm_company(x["Organisation Name"])==n]
    if exact:return exact[0],1.0
    # Conservative fuzzy matching; avoid short/generic names.
    if len(n)<7:return None
    best=None; score=0.0
    for x in rows:
        m=norm_company(x["Organisation Name"])
        if not m:continue
        s=SequenceMatcher(None,n,m).ratio()
        if s>score: best,score=x,s
    return (best,score) if best and score>=0.90 else None

def clean_url(u):
    p=urlparse(u)
    if not p.scheme.startswith("http"):return ""
    q=parse_qs(p.query)
    keep={k:v for k,v in q.items() if k.lower() not in {"utm_source","utm_medium","utm_campaign","utm_content","utm_term","gclid","fbclid"}}
    from urllib.parse import urlencode
    return urlunparse((p.scheme,p.netloc.lower(),p.path.rstrip("/"),"",urlencode(keep,doseq=True),""))

def brave_search(query):
    if not BRAVE:return []
    r=requests.get("https://api.search.brave.com/res/v1/web/search",
        headers={"Accept":"application/json","X-Subscription-Token":BRAVE,"User-Agent":UA},
        params={"q":query,"count":20,"country":"GB","search_lang":"en","freshness":"pw"},timeout=TIMEOUT)
    r.raise_for_status()
    return [x.get("url","") for x in r.json().get("web",{}).get("results",[])]

def bing_rss(query):
    url="https://www.bing.com/search?format=rss&q="+quote_plus(query)
    try:
        r=get(url); r.raise_for_status(); soup=BeautifulSoup(r.text,"xml")
        return [i.link.get_text(strip=True) for i in soup.find_all("item") if i.link]
    except Exception:return []

def discover():
    phrases=[
      '"certificate of sponsorship" job UK','"certificate of sponsorship" vacancy UK',
      '"Skilled Worker sponsorship" jobs UK','"Skilled Worker visa sponsorship" careers UK',
      '"visa sponsorship available" jobs UK','"sponsorship available" vacancy UK',
      '"certificate of sponsorship" jobs England','"certificate of sponsorship" jobs Scotland',
      '"certificate of sponsorship" jobs Wales','"certificate of sponsorship" jobs "Northern Ireland"',
      '"visa sponsorship" site:jobs.nhs.uk','"certificate of sponsorship" site:jobs.ac.uk',
      '"skilled worker sponsorship" site:myworkdayjobs.com UK','"visa sponsorship" site:greenhouse.io UK',
    ]
    urls=[]; seen=set()
    for q in phrases:
        found=[]
        try: found=brave_search(q) if BRAVE else bing_rss(q)
        except Exception as e: print("Search warning:",q,e)
        for u in found:
            u=clean_url(u)
            if u and u not in seen:
                seen.add(u); urls.append(u)
                if len(urls)>=MAX_CANDIDATES:return urls
    print(f"Discovery: {len(urls)} unique candidates; Brave={'enabled' if BRAVE else 'disabled'}")
    return urls

def page_text(url):
    r=get(url); r.raise_for_status()
    if "text" not in r.headers.get("content-type","text/html"):return "","","",""
    soup=BeautifulSoup(r.text,"lxml")
    for x in soup(["script","style","nav","footer"]):x.decompose()
    text=" ".join(soup.stripped_strings)
    title=(soup.title.get_text(" ",strip=True) if soup.title else "")
    h1=soup.find("h1")
    jobtitle=h1.get_text(" ",strip=True) if h1 else title.split("|")[0].strip()
    # Employer from JSON-LD is preferable.
    employer=""; location=""
    raw=BeautifulSoup(r.text,"lxml")
    for sc in raw.find_all("script",type="application/ld+json"):
        try:
            data=json.loads(sc.string or "{}"); items=data if isinstance(data,list) else [data]
            for d in items:
                if isinstance(d,dict) and d.get("@type")=="JobPosting":
                    jobtitle=d.get("title") or jobtitle
                    org=d.get("hiringOrganization") or {}
                    if isinstance(org,dict): employer=org.get("name","")
                    loc=d.get("jobLocation")
                    if isinstance(loc,list):loc=loc[0] if loc else {}
                    if isinstance(loc,dict):
                        a=loc.get("address") or {}
                        if isinstance(a,dict):location=", ".join(str(a.get(k,"")) for k in ("addressLocality","addressRegion","addressCountry") if a.get(k))
        except Exception: pass
    return jobtitle,employer,location,text[:250000]

def sponsorship_evidence(text):
    low=text.lower()
    neg=[m.group(0) for p in NEGATIVE for m in [re.search(p,low,re.I)] if m]
    if neg:return None,"NEGATIVE: "+neg[0]
    for p in POSITIVE:
        m=re.search(p,text,re.I)
        if m:
            a=max(0,m.start()-100); b=min(len(text),m.end()+140)
            return " ".join(text[a:b].split()),"POSITIVE"
    return None,"NONE"

def looks_uk(location,text):
    hay=(" "+location+" "+text[:12000]+" ").lower()
    return any(x in hay for x in UK_HINTS)

def infer_employer(title,text,url):
    # Last-resort hints for pages without JobPosting structured data.
    for pat in [r"(?:Company|Employer|Organisation)\s*[:\-]\s*([^|•\n]{2,80})",r"jobs? at ([A-Z][A-Za-z0-9 &'\.\-]{2,70})"]:
        m=re.search(pat,text)
        if m:return m.group(1).strip()
    host=urlparse(url).netloc.lower().replace("www.","")
    return host.split(".")[0].replace("-"," ").title()

def load_state():
    try:return json.loads(STATE.read_text())
    except Exception:return {"jobs":{}}

def save_state(s):
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(s,indent=2,sort_keys=True))

def key(j):
    return hashlib.sha256((norm_company(j.employer)+"|"+re.sub(r"\W+"," ",j.title.lower()).strip()+"|"+clean_url(j.url)).encode()).hexdigest()

def write_csv(path,jobs):
    fields=list(Job.__dataclass_fields__)
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for j in jobs:w.writerow(asdict(j))

def self_test():
    assert norm_company("Example UK Limited")=="example"
    assert sponsorship_evidence("Skilled Worker visa sponsorship is available")[0]
    assert sponsorship_evidence("We cannot provide visa sponsorship")[0] is None
    assert clean_url("https://x.test/job/1?utm_source=a")=="https://x.test/job/1"
    rows=[{"Organisation Name":"Example Healthcare Limited","Town/City":"Leeds","County":"","Type & Rating":"Worker (A rating)","Route":"Skilled Worker"}]
    assert sponsor_match("Example Healthcare Ltd",rows)[1]==1.0
    print("Self-tests: PASS")

def main():
    if "--self-test" in sys.argv:self_test();return
    sponsors,regurl=load_register(); state=load_state(); now=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())
    accepted=[]; audit=[]
    for i,url in enumerate(discover(),1):
        status=""; detail=""
        try:
            title,employer,location,text=page_text(url)
            ev,evstat=sponsorship_evidence(text)
            if not ev: status="REJECT"; detail=evstat
            elif not looks_uk(location,text): status="REJECT"; detail="NOT_UK"
            else:
                employer=employer or infer_employer(title,text,url)
                sm=sponsor_match(employer,sponsors)
                if not sm: status="REJECT"; detail="SPONSOR_NOT_VERIFIED"
                else:
                    row,score=sm
                    j=Job(title or "Untitled vacancy",employer,location,url,ev,row["Organisation Name"],row.get("Town/City",""),row.get("Route",""),row.get("Type & Rating",""),round(score,3))
                    k=key(j); old=state["jobs"].get(k)
                    j.notification_status="SEEN" if old else "NEW"
                    j.first_seen=(old or {}).get("first_seen",now)
                    state["jobs"][k]={"first_seen":j.first_seen,"last_seen":now,"url":j.url,"title":j.title,"employer":j.employer}
                    accepted.append(j); status="ACCEPT"; detail=f"{j.sponsor_name} ({score:.2f})"
        except Exception as e: status="ERROR"; detail=str(e)[:180]
        audit.append({"url":url,"status":status,"detail":detail})
        print(f"[{i}] {status}: {url}")
    save_state(state)
    new=[j for j in accepted if j.notification_status=="NEW"]
    write_csv("cos_results.csv",accepted); write_csv("cos_new_results.csv",new)
    with open("cos_source_audit.csv","w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["url","status","detail"]);w.writeheader();w.writerows(audit)
    print(f"Verified current jobs: {len(accepted)} | NEW: {len(new)} | register: {regurl}")

if __name__=="__main__":main()
