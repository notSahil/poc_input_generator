"""Streamlit UI page for Task Scheduler and Automated Ingest Operations."""

from datetime import datetime, time as dt_time, timedelta
import logging
from pathlib import Path
import streamlit as st

from config import settings
from core import job_store, scheduler
from core.config_loader import YamlConfigLoader
from ui.components import render_back_button, render_header
from ui.styles import render_pill

logger = logging.getLogger(__name__)


def render(go):
    """Render the Task Scheduler management view."""
    render_header(
        "⏰ Task Scheduler & Automated Runs",
        "Configure automated data reconciliation on recurring intervals or specific calendar dates with multi-channel alerts.",
    )

    render_back_button(go, label="⬅ Back to Home", target="home")

    # Ensure DB is initialized
    job_store.init_db()

    tab_active, tab_create, tab_history = st.tabs([
        "📋 Active Schedules",
        "➕ Create New Schedule",
        "📜 Execution History & Queue",
    ])

    # =========================================================================
    # TAB 1: ACTIVE SCHEDULES
    # =========================================================================
    with tab_active:
        schedules = job_store.list_schedules()

        if not schedules:
            st.info("No task schedules have been created yet. Use the **➕ Create New Schedule** tab above to configure your first automated run.")
        else:
            col_hdr1, col_hdr2 = st.columns([3, 1])
            with col_hdr1:
                st.subheader(f"Configured Schedules ({len(schedules)})")
            with col_hdr2:
                if st.button("🔄 Refresh Status", key="refresh_sched_list", use_container_width=True):
                    st.rerun()

            for sched in schedules:
                s_id = sched["id"]
                s_name = sched["name"]
                r_name = sched["report_name"]
                prof = sched["profile"]
                is_active = bool(sched["is_active"])
                s_type = sched["schedule_type"]
                freq = sched.get("frequency") or "daily"
                exec_mode = sched.get("execution_mode", "reconcile_only")
                last_stat = sched.get("last_run_status") or "Never Run"
                next_run_iso = sched.get("next_run_at", "")
                total_runs = sched.get("total_runs", 0)

                # Format Next Run
                next_display = "N/A"
                if next_run_iso:
                    try:
                        ndt = datetime.fromisoformat(next_run_iso.replace("Z", "+00:00"))
                        next_display = ndt.strftime("%d/%m/%Y %H:%M UK")
                    except Exception:
                        next_display = next_run_iso[:16].replace("T", " ")

                # Status pill
                if not is_active:
                    status_badge = render_pill("Paused", "grey")
                elif last_stat == "SUCCESS":
                    status_badge = render_pill("Active • Healthy", "green")
                elif last_stat == "FAILED":
                    status_badge = render_pill("Active • Last Failed", "red")
                elif last_stat == "SKIPPED":
                    status_badge = render_pill("Active • Last Skipped", "amber")
                else:
                    status_badge = render_pill("Active", "blue")

                # Profile pill
                prof_color = "purple" if prof == "partial" else ("amber" if prof == "sandbox" else "blue")
                prof_label = settings.PROFILES.get(prof, prof.title())

                # Card display
                with st.container():
                    st.markdown(
                        f"""
                        <div class="slds-card" style="margin-bottom: 14px; border-left: 4px solid {'#0176D3' if is_active else '#94A3B8'};">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div>
                                    <div style="font-size: 1.1rem; font-weight: 700; color: #032D60;">{s_name}</div>
                                    <div style="margin-top: 4px; display: flex; gap: 8px; align-items: center;">
                                        {render_pill(r_name, "blue")}
                                        {render_pill(prof_label, prof_color)}
                                        {status_badge}
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 0.75rem; color: #64748B; font-weight: 600; text-transform: uppercase;">Next Execution</div>
                                    <div style="font-weight: 700; color: #032D60; font-size: 0.95rem;">{next_display}</div>
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    # Controls
                    col_info, col_run, col_toggle, col_del = st.columns([3, 1.2, 1.2, 0.8])
                    with col_info:
                        mode_label = "📊 Reconcile Only" if exec_mode == "reconcile_only" else "🚀 Reconcile & Push"
                        type_label = f"📌 One-Off" if s_type == "one_off" else f"🔄 Recurring ({freq.title()})"
                        st.caption(f"**Mode:** {mode_label} | **Type:** {type_label} | **Total Executions:** {total_runs}")

                    with col_run:
                        if st.button("▶ Run Now", key=f"run_now_{s_id}", use_container_width=True, help="Trigger immediate execution"):
                            with st.spinner(f"Executing {s_name}..."):
                                res = scheduler.execute_scheduled_task(s_id)
                                if res.get("status") == "SUCCESS":
                                    st.success(f"Execution complete! {res.get('successful_records', 0)} records updated.")
                                elif res.get("status") == "SKIPPED":
                                    st.warning(f"Task skipped: {res.get('reason')}")
                                else:
                                    st.error(f"Execution failed: {res.get('error')}")
                            st.rerun()

                    with col_toggle:
                        toggle_label = "⏸ Pause" if is_active else "▶ Resume"
                        if st.button(toggle_label, key=f"toggle_{s_id}", use_container_width=True):
                            job_store.update_schedule(s_id, is_active=0 if is_active else 1)
                            st.rerun()

                    with col_del:
                        if st.button("🗑", key=f"del_{s_id}", use_container_width=True, help="Delete this schedule"):
                            job_store.delete_schedule(s_id)
                            st.rerun()

                    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

    # =========================================================================
    # TAB 2: CREATE NEW SCHEDULE
    # =========================================================================
    with tab_create:
        st.subheader("Configure New Automated Schedule")
        st.caption("Create a recurring timer or a specific one-off datetime run.")

        all_reports = YamlConfigLoader.list_reports()
        report_names = [r.name for r in all_reports] if all_reports else ["Apollo 10G", "Master Site Listing"]

        with st.form("create_schedule_form"):
            col_name, col_rep = st.columns([1.5, 1.5])
            with col_name:
                sched_name = st.text_input("Schedule Name *", placeholder="e.g. Apollo 10G Daily 08:30 Sync")
            with col_rep:
                report_choice = st.selectbox("Target Report *", options=report_names)

            col_prof, col_mode = st.columns([1.5, 1.5])
            with col_prof:
                profile_choice = st.radio(
                    "Target Environment Profile *",
                    options=["sandbox", "partial", "prod"],
                    format_func=lambda p: settings.PROFILES.get(p, p),
                    index=0,
                    horizontal=True,
                )
            with col_mode:
                schedule_type_choice = st.radio(
                    "Schedule Timing Mode *",
                    options=["recurring", "one_off"],
                    format_func=lambda t: "🔄 Recurring Interval" if t == "recurring" else "📌 Specific Date & Time (One-Off)",
                    index=0,
                    horizontal=True,
                )

            st.divider()

            # Dynamic fields based on Timing Mode
            run_on_day = None
            run_at_time = "08:30"
            one_off_iso = None
            frequency_choice = None

            if schedule_type_choice == "one_off":
                st.markdown("##### 📌 Specific Date & Time Selection")
                col_d, col_t = st.columns(2)
                with col_d:
                    spec_date = st.date_input("Execution Date (UK)", value=datetime.now().date() + timedelta(days=1))
                with col_t:
                    spec_time = st.time_input("Execution Time (UK - 24h)", value=dt_time(8, 30))

                uk_tz = scheduler.get_uk_timezone()
                target_dt = datetime.combine(spec_date, spec_time, tzinfo=uk_tz)
                one_off_iso = target_dt.isoformat()
                st.info(f"📅 This task will execute once on **{target_dt.strftime('%d/%m/%Y at %H:%M UK')}**, then automatically deactivate.")

            else:
                st.markdown("##### 🔄 Recurring Interval Selection")
                col_freq, col_time = st.columns(2)
                with col_freq:
                    frequency_choice = st.selectbox(
                        "Frequency *",
                        options=["hourly", "daily", "weekly", "monthly"],
                        format_func=lambda f: f.title(),
                        index=1,
                    )

                with col_time:
                    if frequency_choice == "hourly":
                        minute_choice = st.selectbox("Minute of the hour", options=[0, 15, 30, 45], index=2)
                        run_at_time = str(minute_choice)
                        st.info(f"🔄 Runs every hour at minute **:{minute_choice:02d}**.")

                    elif frequency_choice == "daily":
                        time_choice = st.time_input("Daily Run Time (UK - 24h)", value=dt_time(8, 30))
                        run_at_time = time_choice.strftime("%H:%M")
                        st.info(f"🔄 Runs every day at **{run_at_time} UK time**.")

                    elif frequency_choice == "weekly":
                        day_choice = st.selectbox(
                            "Day of the Week",
                            options=["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
                            format_func=lambda d: {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday", "SUN": "Sunday"}[d],
                        )
                        time_choice = st.time_input("Weekly Run Time (UK - 24h)", value=dt_time(9, 0))
                        run_on_day = day_choice
                        run_at_time = time_choice.strftime("%H:%M")
                        st.info(f"🔄 Runs every **{day_choice} at {run_at_time} UK time**.")

                    elif frequency_choice == "monthly":
                        dom_choice = st.slider("Day of the Month", min_value=1, max_value=28, value=1)
                        time_choice = st.time_input("Monthly Run Time (UK - 24h)", value=dt_time(7, 0))
                        run_on_day = str(dom_choice)
                        run_at_time = time_choice.strftime("%H:%M")
                        st.info(f"🔄 Runs on day **{dom_choice} of each month at {run_at_time} UK time**.")

            st.divider()

            # Execution Mode & Safety Gate
            st.markdown("##### ⚙️ Execution Mode & Safety Controls")
            exec_mode_choice = st.radio(
                "Execution Action",
                options=["reconcile_only", "reconcile_and_push"],
                format_func=lambda m: "📊 Reconcile Only (Compute deltas & generate 5-file audit package, no Salesforce write)" if m == "reconcile_only" else "🚀 Reconcile & Push (Generate deltas AND automatically upload to Salesforce)",
                index=0,
            )

            auto_push_confirmed = False
            batch_size = 15

            if exec_mode_choice == "reconcile_and_push":
                st.warning("⚠️ **AUTOMATED PRODUCTION/SANDBOX WRITE WARNING**: Enabling auto-push will write records directly to Salesforce during scheduled execution without manual review.")
                auto_push_confirmed = st.checkbox("I confirm that this schedule is authorized to push records automatically.")
                batch_size = st.select_slider("Micro-Batch Size", options=[5, 10, 15, 25, 50], value=15)

            submitted = st.form_submit_button("Create Schedule ➔", type="primary", use_container_width=True)

            if submitted:
                if not sched_name.strip():
                    st.error("Please enter a Schedule Name.")
                elif exec_mode_choice == "reconcile_and_push" and not auto_push_confirmed:
                    st.error("You must check the confirmation checkbox to authorize scheduled auto-push.")
                else:
                    # Compute initial next_run_at
                    next_dt = scheduler.compute_next_run(
                        schedule_type=schedule_type_choice,
                        frequency=frequency_choice,
                        run_at_time=run_at_time,
                        run_on_day=run_on_day,
                        one_off_datetime=one_off_iso,
                    )

                    if not next_dt:
                        st.error("The specified date and time is in the past. Please select a future time.")
                    else:
                        try:
                            job_store.create_schedule(
                                name=sched_name.strip(),
                                report_name=report_choice,
                                profile=profile_choice,
                                schedule_type=schedule_type_choice,
                                frequency=frequency_choice,
                                run_at_time=run_at_time,
                                run_on_day=run_on_day,
                                one_off_datetime=one_off_iso,
                                execution_mode=exec_mode_choice,
                                auto_push_confirmed=auto_push_confirmed,
                                batch_size=batch_size,
                                next_run_at=next_dt.isoformat(),
                            )
                            st.success(f"Schedule '{sched_name}' created successfully! Next run: {next_dt.strftime('%d/%m/%Y %H:%M UK')}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to create schedule: {e}")

    # =========================================================================
    # TAB 3: EXECUTION HISTORY & QUEUE
    # =========================================================================
    with tab_history:
        st.subheader("Job Queue & Execution History")
        active_jobs = job_store.get_active_jobs()
        if active_jobs:
            st.markdown("##### ⚡ Currently Active / Queued Jobs")
            for aj in active_jobs:
                st.info(f"**Job ID:** `{aj['id']}` | **Report:** {aj['report_name']} | **Status:** {aj['status']} | **Processed:** {aj.get('processed', 0)}/{aj.get('total_records', 0)}")

        st.markdown("<div style='margin-top: 16px;'></div>", unsafe_allow_html=True)
        # Recent jobs query
        with job_store.get_db() as conn:
            cursor = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 30")
            recent_jobs = [dict(r) for r in cursor.fetchall()]

        if not recent_jobs:
            st.caption("No execution history recorded in the persistent queue yet.")
        else:
            import pandas as pd
            display_data = []
            for j in recent_jobs:
                created_str = j.get("created_at", "")[:19].replace("T", " ")
                display_data.append({
                    "Date (UTC)": created_str,
                    "Report": j.get("report_name"),
                    "Profile": j.get("profile"),
                    "Status": j.get("status"),
                    "Trigger": j.get("triggered_by", "manual"),
                    "Records": f"{j.get('successful', 0)} / {j.get('total_records', 0)}",
                    "Error": j.get("error_summary") or "—",
                })
            st.dataframe(pd.DataFrame(display_data), use_container_width=True)
