"""The offline web app. Skip logic also runs on the page, by asking the server."""
import json

from . import core
from .fieldkit import App, Fail, bar_chart, card, download, form, h, link, redirect, stats, table

SCHEMA = """
CREATE TABLE IF NOT EXISTS surveys (id INTEGER PRIMARY KEY, title TEXT NOT NULL, definition TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS responses (id INTEGER PRIMARY KEY, survey INTEGER NOT NULL REFERENCES surveys(id), answers TEXT NOT NULL);
"""


def field(q, raw, error):
    n = h(q["name"])
    label = h(q.get("label", q["name"])) + (" *" if q.get("required") else "")
    note = f'<span class="bad">{h(error)}</span>' if error else ""
    value = raw.get(q["name"], "")
    if q["type"] == "note":
        return f"<p>{label}</p>"
    if q["type"] == "select_one":
        opts = '<option value=""></option>' + "".join(f'<option value="{h(c[0])}"{" selected" if value == c[0] else ""}>{h(c[1])}</option>' for c in q["choices"])
        return f'<label>{label}<select name="{n}">{opts}</select>{note}</label>'
    if q["type"] == "select_multiple":
        chosen = value if isinstance(value, list) else str(value).split(",")
        boxes = "".join(f'<div><label style="font-weight:400"><input type="checkbox" name="{n}__{h(c[0])}" value="1"{" checked" if c[0] in chosen else ""}> {h(c[1])}</label></div>' for c in q["choices"])
        return f"<fieldset><legend>{label}</legend>{boxes}{note}</fieldset>"
    kind = {"integer": "number", "decimal": "number", "date": "date"}.get(q["type"], "text")
    step = ' step="any"' if q["type"] == "decimal" else ""
    return f'<label>{label}<input type="{kind}"{step} name="{n}" value="{h(str(value))}">{note}</label>'


def create_app(db="survey.db"):
    a = App("FieldSurvey", db, SCHEMA, [("Surveys", "/"), ("New survey", "/new")])

    def load(sid):
        r = a.row("SELECT * FROM surveys WHERE id = ?", sid)
        if r is None:
            raise Fail("No such survey", 404)
        return core.Survey(json.loads(r["definition"]))

    def collect(s, form_data):
        raw = {}
        for q in s.questions:
            if q["type"] == "select_multiple":
                raw[q["name"]] = [c[0] for c in q["choices"] if form_data.get(f"{q['name']}__{c[0]}")]
            elif q["name"] in form_data:
                raw[q["name"]] = form_data[q["name"]]
        return raw

    def answers(sid):
        return [json.loads(r["answers"]) for r in a.rows("SELECT answers FROM responses WHERE survey = ? ORDER BY id", sid)]

    @a.route("/")
    def home(req):
        rows = a.rows("SELECT s.id, s.title, COUNT(r.id) n FROM surveys s LEFT JOIN responses r ON r.survey = s.id GROUP BY s.id ORDER BY s.id DESC")
        return a.page("Surveys", card("Surveys", table(rows, [("Survey", lambda r: link(f"/s/{r['id']}", r["title"])), ("Responses", "n"), ("", lambda r: link(f"/s/{r['id']}/fill", "Enter a response"))], "Create a survey to begin.")))

    @a.route("/new", ("GET", "POST"))
    def new(req):
        if req.method == "POST":
            text = req.text("definition", limit=500000)
            try:
                s = core.Survey(json.loads(text))
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise Fail(f"That definition has a problem: {exc}") from None
            except core.FormError as exc:
                raise Fail(str(exc)) from None
            cur = a.run("INSERT INTO surveys (title, definition) VALUES (?, ?)", s.title, text)
            return redirect(f"/s/{cur.lastrowid}")
        return a.page("New survey", card("Definition as JSON", form(a, "/new", [("definition", "Definition", "textarea", core.EXAMPLE)], "Create")))

    @a.route("/s/<id>/fill", ("GET", "POST"))
    def fill(req, id):
        s = load(id)
        raw, errors = {}, {}
        if req.method == "POST":
            raw = collect(s, req.form)
            clean, errors = s.check(raw)
            if not errors and req.get("finish"):
                a.run("INSERT INTO responses (survey, answers) VALUES (?, ?)", id, json.dumps(clean, ensure_ascii=False))
                return redirect(f"/s/{id}/fill?saved=1")
            if not req.get("finish"):
                errors = {}
        shown = s.visible({q["name"]: s._peek(q["name"], raw.get(q["name"])) for q in s.questions})
        body = "".join(field(q, raw, errors.get(q["name"])) for q in shown)
        flash = "Response saved." if req.get("saved") else ""
        return a.page(s.title, f'<form class="card" method="post" action="/s/{id}/fill">{a.form_token()}{body}<p><button name="update" value="1">Update questions</button> <button name="finish" value="1">Save response</button></p></form>', flash)

    @a.route("/s/<id>")
    def results(req, id):
        s = load(id)
        rows = answers(id)
        body = stats([("Responses", len(rows))]) + f'<p><a class="button" href="/s/{id}/fill">Enter a response</a> <a href="/s/{id}/data.csv">Download CSV</a></p>'
        for item in s.tabulate(rows):
            detail = f"<p class='muted'>Answered {item['answered']}, skipped {item['skipped']}</p>"
            if "choices" in item:
                detail += bar_chart([(c[0], c[1]) for c in item["choices"]])
            elif "mean" in item:
                detail += f"<p>Mean {item['mean']:.2f}, median {item['median']:g}, range {item['low']:g} to {item['high']:g}</p>"
            body += card(item["label"], detail)
        return a.page(s.title, body)

    @a.route("/s/<id>/data.csv")
    def data(req, id):
        s = load(id)
        cols = [q["name"] for q in s.questions if q["type"] != "note"]
        rows = [[(";".join(r[c]) if isinstance(r.get(c), list) else r.get(c, "")) for c in cols] for r in answers(id)]
        return download(rows, cols, "survey.csv")

    return a
