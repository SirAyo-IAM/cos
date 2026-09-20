#!/usr/bin/env python3
import csv, html, os, sys, requests
FILE=os.getenv("COS_EMAIL_RESULTS_FILE","cos_new_results.csv")
if not os.path.exists(FILE): raise SystemExit(f"Missing {FILE}")
with open(FILE,encoding="utf-8-sig",newline="") as f: rows=list(csv.DictReader(f))
if not rows:
    print("No NEW verified sponsorship jobs; email suppressed."); raise SystemExit(0)
key=os.getenv("BREVO_API_KEY","").strip(); to=os.getenv("REPORT_EMAIL","").strip(); sender=os.getenv("BREVO_SENDER_EMAIL","").strip()
missing=[n for n,v in [("BREVO_API_KEY",key),("REPORT_EMAIL",to),("BREVO_SENDER_EMAIL",sender)] if not v]
if missing: raise SystemExit("Missing email secrets: "+", ".join(missing))
cards=[]
for r in rows:
    ev=html.escape(r.get("sponsorship_evidence",""))
    cards.append(f"""<div style="margin:0 0 18px;padding:16px;border:1px solid #ddd;border-radius:8px">
<b>{html.escape(r.get('title',''))}</b><br>{html.escape(r.get('employer',''))}<br>
📍 {html.escape(r.get('location',''))}<br>
🛂 <b>Sponsorship advertised + UKVI sponsor verified</b><br>
UKVI: {html.escape(r.get('sponsor_name',''))} — {html.escape(r.get('sponsor_route',''))}<br>
<small>Evidence: {ev}</small><br><br>
<a href="{html.escape(r.get('url',''),quote=True)}">Open vacancy</a></div>""")
body="<h2>UK CoS Job Hunter — "+str(len(rows))+" new verified jobs</h2><p>Each result contains sponsorship wording in the vacancy and an employer match on the UKVI sponsor register. This does not guarantee visa eligibility or that a CoS will be issued.</p>"+"".join(cards)
payload={"sender":{"email":sender,"name":"UK CoS Job Hunter"},"to":[{"email":to}],"subject":f"UK CoS Job Hunter: {len(rows)} new verified jobs","htmlContent":body}
r=requests.post("https://api.brevo.com/v3/smtp/email",headers={"api-key":key,"content-type":"application/json"},json=payload,timeout=30)
if r.status_code>=300: raise SystemExit(f"Brevo send failed HTTP {r.status_code}: {r.text[:300]}")
print(f"Email sent with {len(rows)} NEW jobs.")
