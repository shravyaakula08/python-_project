"""Campus Catalyst - Streamlit GUI for the Simple Data Cleaning Assistant.

Run:  streamlit run app_gui.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from core import plots
from core.cleaner import FIX_OPTIONS, analyze, apply_fixes
from core.search import distinct_values, rows_with_issue_kind, search_records
from core.service import Workspace
from core.summary import compute_summary
from core.validation import validate_field
from core.importer import ImportFailure

st.set_page_config(page_title="Campus Catalyst - Data Cleaning Assistant", page_icon="🧹", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1300px;}
.cc-hero {padding: 18px 24px; border-radius: 16px; margin-bottom: 18px;
          background: linear-gradient(120deg, #4F46E5 0%, #7C3AED 55%, #06B6D4 100%); color: #fff;}
.cc-hero h1 {margin: 0; font-size: 1.7rem; color: #fff;}
.cc-hero p {margin: 4px 0 0 0; opacity: .92; color: #fff;}
.cc-card {border-radius: 14px; padding: 14px 18px; border: 1px solid rgba(99,102,241,.28);
          background: rgba(99,102,241,.07);}
.cc-card .label {font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; opacity: .7;}
.cc-card .value {font-size: 1.9rem; font-weight: 700; line-height: 1.2;}
.cc-card .sub {font-size: .8rem; opacity: .75;}
.cc-good {color: #10B981;} .cc-mid {color: #F59E0B;} .cc-bad {color: #EF4444;}
section[data-testid="stSidebar"] .stRadio label {font-size: 1rem;}
</style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------ helpers
def get_ws() -> Workspace:
    if "ws" not in st.session_state:
        st.session_state["ws"] = Workspace()
    return st.session_state["ws"]


def show_df(df: pd.DataFrame, **kw) -> None:
    """st.dataframe across Streamlit versions (width API changed over time)."""
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    except Exception:
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def rows_df(ws: Workspace, items=None) -> pd.DataFrame:
    items = items if items is not None else list(enumerate(ws.rows, 1))
    df = pd.DataFrame([{"#": n, **{c: r.get(c, "") for c in ws.columns}} for n, r in items],
                      columns=["#"] + ws.columns)
    return df.astype(str)


def card(label: str, value, sub: str = "", tone: str = "") -> str:
    return (f'<div class="cc-card"><div class="label">{label}</div>'
            f'<div class="value {tone}">{value}</div><div class="sub">{sub}</div></div>')


def tone_for(status: str) -> str:
    return {"Healthy": "cc-good", "Needs Attention": "cc-mid", "Critical": "cc-bad"}.get(status, "")


def show_alerts(ws: Workspace) -> None:
    for a in ws.alerts:
        {"CRITICAL": st.error, "WARNING": st.warning, "INFO": st.success}[a.level](a.message)


def show_figure(fig) -> None:
    st.pyplot(fig)
    plots.plt.close(fig)


# ------------------------------------------------------------------ pages
def page_dashboard(ws: Workspace) -> None:
    s = ws.summary
    c = st.columns(5)
    c[0].markdown(card("Records", s["rows"], f"{s['columns']} columns"), unsafe_allow_html=True)
    c[1].markdown(card("Quality score", s["quality_score"], s["status"], tone_for(s["status"])), unsafe_allow_html=True)
    c[2].markdown(card("Missing values", s["missing_cells"], f"completeness {s['completeness']}%"), unsafe_allow_html=True)
    c[3].markdown(card("Duplicate rows", s["duplicate_rows"], f"uniqueness {s['uniqueness']}%"), unsafe_allow_html=True)
    c[4].markdown(card("Inconsistent cells", s["inconsistent_cells"], f"validity {s['validity']}%"), unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([1, 1])
    with left:
        st.subheader("Threshold warnings")
        show_alerts(ws)
        if st.button("Run scan and log quality score"):
            ws.scan(log_history=True)
            st.toast("Scan complete - score logged to history")
            st.rerun()
    with right:
        st.subheader("Executive summary")
        st.markdown(f"**{s['clean_rows']} of {s['rows']}** rows are completely clean ({s['clean_rows_pct']}%). "
                    f"The scan found **{s['total_issues']}** issues: {s['by_kind'].get('missing', 0)} missing, "
                    f"{s['by_kind'].get('duplicate', 0)} duplicate-related and {s['by_kind'].get('inconsistent', 0)} inconsistent.")
        if s["numeric"]:
            df = pd.DataFrame(s["numeric"]).T.round(2)
            df.index.name = "column"
            show_df(df.reset_index())
    if plots.HAVE_MPL and ws.rows:
        a, b = st.columns(2)
        with a:
            show_figure(plots.fig_kind_breakdown(s))
        with b:
            show_figure(plots.fig_issue_types(s))
    for col, items in s["categories"].items():
        st.subheader(f"Distribution: {col}")
        st.bar_chart(pd.DataFrame(items, columns=[col, "records"]).set_index(col))
    t = s.get("trend") or {}
    if t.get("periods"):
        st.subheader(f"Trend: average {t['value_column']} by {t['date_column']} year")
        st.line_chart(pd.DataFrame({f"avg {t['value_column']}": t["averages"]}, index=t["periods"]))


def page_records(ws: Workspace) -> None:
    tab_browse, tab_add, tab_edit = st.tabs(["Browse & search", "Add record", "Edit / delete"])

    with tab_browse:
        c1, c2, c3 = st.columns([2, 1, 1])
        kw = c1.text_input("Keyword (any column)", key="kw")
        cat_cols = [c for c in ws.columns if ws.rules[c].get("type") == "category"]
        filters = {}
        if cat_cols:
            col = c2.selectbox("Category column", ["(none)"] + cat_cols, key="catcol")
            if col != "(none)":
                val = c3.selectbox(f"{col} equals", ["(any)"] + distinct_values(ws.rows, col), key="catval")
                if val != "(any)":
                    filters[col] = val
        d1, d2 = st.columns([1, 1])
        num_cols = [c for c in ws.columns if ws.rules[c].get("type") in ("int", "float")]
        ranges = {}
        if num_cols:
            ncol = d1.selectbox("Numeric range column", ["(none)"] + num_cols, key="numcol")
            if ncol != "(none)":
                lo_hi = d2.slider("Range", 0.0, 100.0, (0.0, 100.0), key="rng") if ws.rules[ncol].get("max") == 100 \
                    else (d2.number_input("Min", value=0.0, key="rmin"), d2.number_input("Max", value=200.0, key="rmax"))
                ranges[ncol] = (float(lo_hi[0]), float(lo_hi[1]))
        kind = st.radio("Only rows with", ["Any", "Missing values", "Duplicates", "Inconsistent entries"],
                        horizontal=True, key="kindsel")
        issue_rows = None
        if kind != "Any":
            issue_rows = rows_with_issue_kind(ws.issues, {"Missing values": "missing", "Duplicates": "duplicate",
                                                          "Inconsistent entries": "inconsistent"}[kind])
        found = search_records(ws.rows, ws.columns, kw, filters, ranges, issue_rows)
        st.caption(f"{len(found)} of {len(ws.rows)} records")
        show_df(rows_df(ws, found))

    with tab_add:
        st.write("Every field is validated before the record is saved.")
        with st.form("add_form", clear_on_submit=False):
            raw = {}
            cols = st.columns(2)
            for i, col in enumerate(ws.columns):
                rule = ws.rules[col]
                label = col.replace("_", " ").title() + (" *" if rule.get("required") else "")
                box = cols[i % 2]
                if rule.get("type") == "category" and rule.get("aliases"):
                    raw[col] = box.selectbox(label, [""] + sorted(rule["aliases"]), key=f"add_{col}")
                else:
                    ph = {"date": "YYYY-MM-DD", "id": "e.g. S041", "email": "name@campus.edu"}.get(rule.get("type"), "")
                    raw[col] = box.text_input(label, placeholder=ph, key=f"add_{col}")
            submitted = st.form_submit_button("Validate & save record")
        if submitted:
            clean, errors = {}, []
            for col in ws.columns:
                v, err = validate_field(col, ws.rules[col], raw[col], ws.rows)
                clean[col] = v
                if err:
                    errors.append(err)
            if errors:
                for e in errors:
                    st.error(e)
            else:
                n = ws.add_record(clean)
                st.success(f"Record saved as row {n}.")
                st.rerun()

    with tab_edit:
        if not ws.rows:
            st.info("No records yet.")
        else:
            n = st.number_input("Row number", min_value=1, max_value=len(ws.rows), value=1, step=1, key="edit_row")
            show_df(rows_df(ws, [(int(n), ws.rows[int(n) - 1])]))
            col = st.selectbox("Column", ws.columns, key="edit_col")
            cur = ws.rows[int(n) - 1].get(col, "")
            new = st.text_input("New value", value=cur, key=f"edit_val_{n}_{col}")
            b1, b2 = st.columns(2)
            if b1.button("Update value"):
                v, err = validate_field(col, ws.rules[col], new, ws.rows, current=cur)
                if err:
                    st.error(err)
                else:
                    ws.update_record(int(n), col, v)
                    st.success(f"Row {int(n)}: {col} updated to '{v}'.")
                    st.rerun()
            confirm = b2.checkbox("Confirm delete", key="del_ok")
            if b2.button("Delete this row") and confirm:
                ws.delete_record(int(n))
                st.rerun()
            with st.expander("Edit the whole table"):
                edited = st.data_editor(rows_df(ws).drop(columns="#"), num_rows="dynamic", key="grid")
                if st.button("Save table changes"):
                    ws.replace_rows(edited.fillna("").to_dict("records"))
                    st.success("Table saved.")
                    st.rerun()


def page_issues(ws: Workspace) -> None:
    st.subheader("Findings")
    if not ws.issues:
        st.success("No issues found - the dataset is clean.")
        return
    c1, c2, c3 = st.columns(3)
    kinds = c1.multiselect("Type", ["missing", "duplicate", "inconsistent"], default=["missing", "duplicate", "inconsistent"])
    sevs = c2.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
    cols = c3.multiselect("Column", ["(entire row)"] + ws.columns, default=[])
    sel = [i for i in ws.issues if i.kind in kinds and i.severity in sevs and (not cols or i.column in cols)]
    st.caption(f"{len(sel)} of {len(ws.issues)} issues")
    df = pd.DataFrame([{"Row": i.row, "Column": i.column, "Type": f"{i.kind}/{i.subtype}", "Severity": i.severity,
                        "Value": i.value, "Problem": i.message, "Suggested fix": i.suggestion} for i in sel])
    show_df(df)


def page_clean(ws: Workspace) -> None:
    st.subheader("Clean & fix")
    st.write("Pick the fixes to apply. Preview shows the effect without changing your data; Undo restores the previous state.")
    chosen = {k for k, label in FIX_OPTIONS.items() if st.checkbox(label, value=True, key=f"fix_{k}")}
    a, b, c = st.columns(3)
    if a.button("Preview"):
        new_rows, log = apply_fixes(ws.columns, ws.rows, ws.rules, chosen)
        issues = analyze(ws.columns, new_rows, ws.rules)
        s2 = compute_summary(ws.columns, new_rows, issues, ws.rules)
        st.info(f"Quality score would go from **{ws.summary['quality_score']}** to **{s2['quality_score']}** "
                f"({len(ws.issues)} -> {len(issues)} issues).")
        for line in log:
            st.write(f"- {line}")
    if b.button("Apply fixes"):
        log = ws.clean(chosen)
        st.session_state["last_clean"] = log
        st.rerun()
    if c.button("Undo last change"):
        st.toast("Undone" if ws.undo() else "Nothing to undo")
        st.rerun()
    if st.session_state.get("last_clean"):
        st.success("Cleaning applied:")
        for line in st.session_state["last_clean"]:
            st.write(f"- {line}")
        if ws.issues:
            st.warning(f"{len(ws.issues)} issue(s) remain that need a manual decision (see the Issues page).")


def page_charts(ws: Workspace) -> None:
    st.subheader("Charts")
    if not plots.HAVE_MPL:
        st.error("Matplotlib is not installed - run `pip install matplotlib`.")
        return
    figs = ws.charts()
    names = list(figs)
    for i in range(0, len(names), 2):
        cols = st.columns(2)
        for col, name in zip(cols, names[i:i + 2]):
            with col:
                show_figure(figs[name])
    if st.button("Save all charts as PNG"):
        paths = ws.save_charts()
        st.success(f"Saved {len(paths)} charts to {paths[0].parent}")


def page_import(ws: Workspace) -> None:
    st.subheader("Bulk import (legacy CSV)")
    up = st.file_uploader("Choose a CSV file", type=["csv"])
    strict = st.checkbox("Strict mode - reject rows that have field errors", value=False)
    if up is not None and st.button("Validate file"):
        tmp = Path(tempfile.gettempdir()) / up.name
        tmp.write_bytes(up.getvalue())
        try:
            st.session_state["import_res"] = ws.import_csv(tmp, strict=strict)
        except ImportFailure as exc:
            st.session_state.pop("import_res", None)
            st.error(f"Import failed: {exc}")
    res = st.session_state.get("import_res")
    if res:
        m = st.columns(4)
        m[0].metric("Rows read", res.total)
        m[1].metric("Accepted", res.accepted, f"{res.warned} with warnings", delta_color="off")
        m[2].metric("Rejected", res.rejected)
        m[3].metric("Blank lines", res.skipped)
        st.caption("Header mapping: " + ", ".join(f"{k} -> {v}" for k, v in res.columns_mapped.items()))
        with st.expander("Row-by-row import log", expanded=True):
            st.code("\n".join(res.log), language="text")
        st.download_button("Download import log", "\n".join(res.log), file_name="import_errors.log")
        if res.rows:
            show_df(pd.DataFrame(res.rows).astype(str))
            if st.button(f"Add {res.accepted} accepted rows to the dataset"):
                ws.merge_rows(res.rows)
                st.session_state.pop("import_res")
                st.success("Rows added.")
                st.rerun()


def page_export(ws: Workspace) -> None:
    st.subheader("Export")
    a, b, c, d = st.columns(4)
    a.download_button("Markdown report", ws.markdown(), file_name="report.md", mime="text/markdown")
    b.download_button("Audit log (.txt)", ws.audit_log(), file_name="audit_log.txt")
    c.download_button("Issues report (.csv)", ws.issues_csv(), file_name="issues_report.csv", mime="text/csv")
    d.download_button("Dataset (.csv)", rows_df(ws).drop(columns="#").to_csv(index=False), file_name="dataset.csv", mime="text/csv")
    if st.button("Save all three reports into the reports/ folder"):
        for p in ws.export():
            st.write(f"Saved `{p}`")
    with st.expander("Preview Markdown report"):
        st.markdown(ws.markdown())


def page_settings(ws: Workspace) -> None:
    st.subheader("Threshold warnings")
    th = ws.thresholds
    c1, c2, c3 = st.columns(3)
    th["missing_pct_column"] = c1.number_input("Max % missing per column", 0.0, 100.0, float(th["missing_pct_column"]))
    th["inconsistent_pct_column"] = c2.number_input("Max % inconsistent per column", 0.0, 100.0, float(th["inconsistent_pct_column"]))
    th["duplicate_pct"] = c3.number_input("Max % duplicate rows", 0.0, 100.0, float(th["duplicate_pct"]))
    th["quality_warning"] = c1.number_input("Quality warning below", 0.0, 100.0, float(th["quality_warning"]))
    th["quality_critical"] = c2.number_input("Quality critical below", 0.0, 100.0, float(th["quality_critical"]))
    ws.scan(log_history=False)
    st.divider()
    st.subheader("Dataset")
    a, b = st.columns(2)
    if a.button("Load the 40-row sample dataset"):
        ws.load_sample()
        st.success("Sample dataset loaded.")
        st.rerun()
    if b.button("Start with an empty dataset"):
        ws.reset_empty()
        st.rerun()
    up = st.file_uploader("Replace the dataset with a CSV or JSON file", type=["csv", "json"], key="replace_up")
    if up is not None and st.button("Load uploaded file"):
        tmp = Path(tempfile.gettempdir()) / up.name
        tmp.write_bytes(up.getvalue())
        try:
            n = ws.load_file(tmp)
            st.success(f"Loaded {n} rows from {up.name}.")
            st.rerun()
        except Exception as exc:
            st.error(f"Could not load file: {exc}")
    st.caption(f"Autosaved to `{ws.path}`")


PAGES = {"Dashboard": page_dashboard, "Records": page_records, "Issues": page_issues,
         "Clean & Fix": page_clean, "Charts": page_charts, "Bulk Import": page_import,
         "Export": page_export, "Settings": page_settings}


def main() -> None:
    ws = get_ws()
    st.markdown('<div class="cc-hero"><h1>🧹 Campus Catalyst</h1>'
                '<p>Simple Data Cleaning Assistant - find missing values, duplicate rows and inconsistent entries</p></div>',
                unsafe_allow_html=True)
    for note in ws.notes:
        st.info(note)
    ws.notes = []
    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio("Go to", list(PAGES), label_visibility="collapsed")
        st.divider()
        s = ws.summary
        st.metric("Quality score", s.get("quality_score", "-"), s.get("status", ""), delta_color="off")
        st.caption(f"{s.get('rows', 0)} records - autosaved")
    PAGES[page](ws)


main()
