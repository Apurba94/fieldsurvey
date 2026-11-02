# FieldSurvey

Run a survey with no internet. Describe the form in a simple file, enter answers in the browser, and get tables and charts at once. It suits needs assessments and monitoring visits.

```
python -m fieldsurvey
```

Then open http://127.0.0.1:8032. A worked example is ready to use. It needs Python 3.10 or newer.

## A form definition

```json
{"title": "Household needs check", "questions": [
  {"name": "members", "label": "People in the household", "type": "integer", "required": true,
   "constraint": ". >= 1 and . <= 40", "constraint_message": "must be 1 to 40"},
  {"name": "children", "label": "Children under five", "type": "integer",
   "constraint": ". <= members", "constraint_message": "cannot exceed household size"},
  {"name": "water", "label": "Main water source", "type": "select_one",
   "choices": [["tap", "Tap stand"], ["other", "Other"]]},
  {"name": "water_other", "label": "Which other source?", "type": "text", "relevant": "water == 'other'"}
]}
```

Question types are `text`, `integer`, `decimal`, `date`, `select_one`, `select_multiple` and `note`.

## Skip logic and checks

`relevant` shows a question only when its condition holds, and `constraint` checks an answer, where `.` is the current value. Conditions can use earlier answers, `and`, `or`, `not`, arithmetic and the functions `selected()`, `count()`, `answered()` and `length()`. These ideas will feel familiar to users of XLSForm.

Skipped questions are not required, and any answer left behind on one is dropped. Results report how many people answered each question, so percentages use the right base.

## Safety

Conditions run in a small language written for this project, so a form definition cannot run code. Python's `eval` is not used anywhere, and tests try common attacks to confirm this.

## Results

Tables and charts for every question, mean and median for numbers, cross-tabulation in `core.py`, and CSV export for further analysis.

## How it is tested

The expression language is tested for logic, missing answers, type mix-ups and attack strings. Skip logic is tested through chains of dependent questions, and validation through each question type. App tests cover entry from start to export, and escaping of answers.

## Limits

It runs on one computer, so several enumerators means several files to combine. There is no phone app, GPS, photo capture or translation layer, and no weighting in the analysis. Personal data needs the same care as in any survey: the data file is not encrypted, so review it with your data protection lead.

## Tests

```
python -m unittest discover -s tests
```

MIT licence.
