import streamlit as st
import pandas as pd
from datetime import datetime
import re
import plotly.graph_objects as go
import os
import io
import requests
from auth import sign_out
from supabase import create_client, Client
import time

# Use st.secrets for Supabase credentials
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Add this near the top, after SUPABASE_KEY
ADMIN_EMAILS = st.secrets.get("ADMIN_EMAILS", [])

def is_admin(user_email):
    return user_email in ADMIN_EMAILS

# === CONSTANTS ===
COLOR_MAP = {
    "TE": "#1f77b4",
    "FK": "#ff7f0e",
    "TS": "#2ca02c",
    "FH": "#d62728",
    "Angle 1 - o": "#9467bd",
    "Angle 1 - a": "#8c564b",
    "Angle 1 - b": "#e377c2"
}

def extract_youtube_id(url):
    patterns = [
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def plot_custom_lines(df, x_col="Time (ms)", chart_key="default", selected_metrics=None):
    fig = go.Figure()
    metrics = selected_metrics if selected_metrics else COLOR_MAP.keys()

    for col in df.columns:
        if col in metrics and col in COLOR_MAP and col != x_col:
            fig.add_trace(go.Scatter(
                x=df[x_col],
                y=df[col],
                mode='lines',
                name=col,
                line=dict(color=COLOR_MAP.get(col, "#cccccc"))
            ))
    fig.update_layout(
        xaxis_title=x_col,
        yaxis_title="Speed (px/s)",
        height=400,
        legend_title="Metric",
        template="simple_white"
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)

# === MAIN APP ===
def main_app(user_email):
    st.title("Pitcher Biomechanics Tracker")
    st.success(f"Welcome, {user_email}!")

    admin_mode = is_admin(user_email)

    if st.button("Logout"):
        sign_out()

    tab1, tab2, tab3, tab4 = st.tabs([" Upload Session", " View Sessions", " Compare Sessions", "Admin"])

    # === TAB 1: Upload Session ===
    with tab1:
        st.header("Upload New Session")
        with st.form("upload_form"):
            name = st.text_input("Player Name")
            team = st.text_input("Team")
            session_name = st.text_input("Session Name")
            session_date = st.date_input("Session Date")
            video_option = st.radio("Video Source", ["YouTube Link", "Upload Video File"])
            notes = st.text_area("Notes")

            youtube_link_disabled = video_option == "Upload Video File"
            youtube_link = st.text_input("YouTube Link", disabled=youtube_link_disabled)
            uploaded_file = st.file_uploader("Upload Kinematic CSV or Video", type=["csv", "mp4", "mov", "avi", "*"])

            submitted = st.form_submit_button("Upload")

            if submitted:
                final_video_source = None
                kinovea_csv_url = None
                if not uploaded_file:
                    st.warning("⚠️ Please upload a file (CSV or video).")
                    return
                base, ext = os.path.splitext(uploaded_file.name)
                unique_filename = f"{base}_{int(time.time())}{ext}"
                if uploaded_file.type == "text/csv":
                    # CSV upload
                    try:
                        supabase.storage.from_("csvs").upload(
                            path=unique_filename,
                            file=uploaded_file.getvalue(),
                            file_options={"content-type": "text/csv"}
                        )
                        st.success(f"CSV file '{unique_filename}' uploaded!", icon="✅")
                    except Exception as e:
                        st.error(f"CSV upload to Supabase failed: {e}")
                        return
                    final_video_source = youtube_link
                    kinovea_csv_url = f"https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/csvs/{unique_filename}"
                elif uploaded_file.type in ["video/mp4", "video/quicktime", "video/x-msvideo"]:
                    # Video upload
                    try:
                        supabase.storage.from_("videos").upload(
                            path=unique_filename,
                            file=uploaded_file.getvalue(),
                            file_options={"content-type": uploaded_file.type}
                        )
                        st.success(f"Video file '{unique_filename}' uploaded!", icon="✅")
                    except Exception as e:
                        st.error(f"Video upload to Supabase failed: {e}")
                        return
                    final_video_source = f"https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/videos/{unique_filename}"
                    kinovea_csv_url = f"https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/videos/{unique_filename}"
                else:
                    st.warning("⚠️ Please upload a valid CSV or video file (mp4, mov, avi).")
                    return

                # Upsert player into Supabase (do NOT set kinovea_csv)
                try:
                    # Use unique constraint on (name, team, user_email) for upsert
                    player_query = supabase.table("players").select("id").eq("name", name).eq("team", team)
                    if not admin_mode:
                        player_query = player_query.eq("user_email", user_email)
                    player_res = player_query.execute()
                    if player_res.data and len(player_res.data) > 0:
                        player_id = player_res.data[0]["id"]
                        supabase.table("players").update({"notes": notes}).eq("id", player_id).execute()
                    else:
                        player_insert = supabase.table("players").insert({
                            "name": name,
                            "team": team,
                            "notes": notes,
                            "user_email": user_email
                        }).execute()
                        player_id = player_insert.data[0]["id"]
                except Exception as e:
                    st.error(f"❌ Error inserting/finding player: {e}")
                    player_id = None

                # Insert session into Supabase (set kinovea_csv as full URL)
                try:
                    supabase.table("sessions").insert({
                        "player_id": player_id,
                        "date": str(session_date),
                        "session_name": session_name,
                        "video_source": final_video_source,
                        "kinovea_csv": kinovea_csv_url,
                        "notes": notes,
                        "user_email": user_email
                    }).execute()
                    st.success("✅ Session uploaded!", icon="✅")
                except Exception as e:
                    st.error(f"❌ Error uploading session to Supabase: {e}")

            elif submitted:
                st.warning("⚠️ Please upload a video (YouTube link or file).")

    # === TAB 2: View Sessions ===
    with tab2:
        st.header("View & Analyze Session")
        # Get all players for this user (or all if admin)
        player_query = supabase.table("players").select("id", "name")
        if not admin_mode:
            player_query = player_query.eq("user_email", user_email)
        player_res = player_query.execute()
        player_df = pd.DataFrame(player_res.data) if player_res.data else pd.DataFrame()

        if player_df.empty:
            st.warning("No players found for your account." if not admin_mode else "No players found.")
        else:
            selected_player = st.selectbox("Select a player", player_df["name"])
            player_id = int(player_df[player_df["name"] == selected_player]["id"].values[0])
            # Get sessions for this player (or all if admin)
            session_query = supabase.table("sessions").select("*").eq("player_id", player_id)
            if not admin_mode:
                session_query = session_query.eq("user_email", user_email)
            session_res = session_query.execute()
            session_df = pd.DataFrame(session_res.data) if session_res.data else pd.DataFrame()
            if session_df.empty:
                st.warning("No sessions found for this player.")
            else:
                session_df["label"] = session_df["date"] + " - " + session_df["session_name"]
                selected_session = st.selectbox("Select a session", session_df["label"])
                session_match = session_df[session_df["label"] == selected_session]
                if not session_match.empty:
                    session_row = session_match.iloc[0]
                    st.subheader("Video Playback")
                    video_source = session_row["video_source"]
                    # --- Insert debug log for video view ---
                    try:
                        video_id_val = None
                        if video_source.startswith("https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/videos/") or video_source.startswith("https://npvwctwurhttdzvbvgcz.supabase.co/storage/v1/object/public/videos/"):
                            video_id_val = os.path.basename(video_source)  # Always log file name only
                        else:
                            video_id_val = video_source  # Always log full URL for YouTube/other
                        supabase.table("debug_logs").insert({
                            "player_id": player_id,
                            "video_id": video_id_val,
                            "view_email_id": user_email,
                            "is_admin": admin_mode,
                            "is_user": not admin_mode
                        }).execute()
                    except Exception as e:
                        st.warning(f"Could not log video view: {e}")
                    # --- End debug log insert ---
                    if video_source.startswith("http"):
                        if "youtube.com" in video_source or "youtu.be" in video_source:
                            video_id = extract_youtube_id(video_source)
                            if video_id:
                                st.video(f"https://www.youtube.com/embed/{video_id}")
                            else:
                                st.warning("⚠️ Could not extract video ID. Check the YouTube link.")
                        else:
                            st.video(video_source)
                    else:
                        st.warning("⚠️ Local video file not found.")
                    st.subheader("Session Notes")
                    st.markdown(session_row["notes"].replace('\n', '  \n') if session_row["notes"] else "_No notes provided._", unsafe_allow_html=True)
                    st.subheader("Kinematic Data")
                    csv_path = session_row["kinovea_csv"]
                    if not csv_path or not csv_path.lower().endswith(".csv"):
                        st.info("No Kinovea data uploaded for this session.")
                    else:
                        try:
                            if csv_path.startswith("http"):
                                response = requests.get(csv_path)
                                kin_df = pd.read_csv(io.StringIO(response.text))
                            else:
                                kin_df = pd.read_csv(csv_path)
                            st.write(kin_df.head())
                            if "Time (ms)" in kin_df.columns:
                                available_metrics_view = [col for col in kin_df.columns if col in COLOR_MAP]
                                selected_metrics_view = st.multiselect(
                                    "Select metrics to show",
                                    options=available_metrics_view,
                                    default=available_metrics_view,
                                    key="view_metric_select"
                                )
                                plot_custom_lines(kin_df, chart_key="view_plot", selected_metrics=selected_metrics_view)
                            else:
                                st.warning("Column 'Time (ms)' not found. Plotting by row index.")
                                st.line_chart(kin_df.select_dtypes(include=['float', 'int']))
                        except Exception as e:
                            st.error(f"Error reading CSV: {e}")

    # === TAB 3: Compare Sessions ===
    with tab3:
        st.header("Compare Two Sessions Side-by-Side")
        # Get all players for this user (or all if admin)
        player_query = supabase.table("players").select("id", "name")
        if not admin_mode:
            player_query = player_query.eq("user_email", user_email)
        player_res = player_query.execute()
        player_df = pd.DataFrame(player_res.data) if player_res.data else pd.DataFrame()
        if player_df.empty:
            st.warning("No players found for your account.")
        else:
            col1, col2 = st.columns(2)
            # === LEFT SESSION ===
            with col1:
                st.markdown("### Left Player")
                selected_player_left = st.selectbox("Select Player (Left)", player_df["name"], key="left_player")
                player_left_id = int(player_df[player_df["name"] == selected_player_left]["id"].values[0])
                session_res_left = supabase.table("sessions").select("*").eq("player_id", player_left_id).execute()
                left_sessions_df = pd.DataFrame(session_res_left.data) if session_res_left.data else pd.DataFrame()
                if left_sessions_df.empty:
                    st.warning("No sessions found for this player.")
                else:
                    left_sessions_df["label"] = left_sessions_df["date"] + " - " + left_sessions_df["session_name"]
                    session_left = st.selectbox("Select Session (Left)", left_sessions_df["label"], key="left_session")
                    left_match = left_sessions_df[left_sessions_df["label"] == session_left]
                    if not left_match.empty:
                        left_row = left_match.iloc[0]
                        video_source = left_row["video_source"]
                        # --- Insert debug log for left video view ---
                        try:
                            video_id_val = None
                            if video_source.startswith("https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/videos/") or video_source.startswith("https://npvwctwurhttdzvbvgcz.supabase.co/storage/v1/object/public/videos/"):
                                video_id_val = os.path.basename(video_source)
                            else:
                                video_id_val = video_source
                            supabase.table("debug_logs").insert({
                                "player_id": player_left_id,
                                "video_id": video_id_val,
                                "view_email_id": user_email,
                                "is_admin": admin_mode,
                                "is_user": not admin_mode
                            }).execute()
                        except Exception as e:
                            st.warning(f"Could not log video view: {e}")
                        # --- End debug log insert ---
                        if video_source.startswith("http"):
                            if "youtube.com" in video_source or "youtu.be" in video_source:
                                video_id = extract_youtube_id(video_source)
                                if video_id:
                                    st.video(f"https://www.youtube.com/embed/{video_id}")
                                else:
                                    st.warning("⚠️ Invalid YouTube link for left session.")
                            else:
                                st.video(video_source)
                        else:
                            st.warning("⚠️ Local video file not found for left session.")
                        st.subheader("Session Notes (Left)")
                        st.markdown(left_row["notes"].replace('\n', '  \n') if left_row["notes"] else "_No notes provided._", unsafe_allow_html=True)
                        csv_path_left = left_row["kinovea_csv"]
                        if not csv_path_left or not csv_path_left.lower().endswith(".csv"):
                            st.info("No Kinovea data uploaded for this session.")
                        else:
                            try:
                                response = requests.get(csv_path_left)
                                response.raise_for_status()
                                df_left = pd.read_csv(io.StringIO(response.text))
                                if "Time (ms)" in df_left.columns:
                                    available_metrics_left = [col for col in df_left.columns if col in COLOR_MAP]
                                    selected_left_metrics = st.multiselect(
                                        "Select metrics to show (Left)",
                                        options=available_metrics_left,
                                        default=available_metrics_left,
                                        key="metric_select_left",
                                        help="Select which metrics to plot for the left session.",
                                        max_selections=None
                                    )
                                    plot_custom_lines(df_left, chart_key="left_plot", selected_metrics=selected_left_metrics)
                                else:
                                    st.warning("Column 'Time (ms)' not found in left session.")
                                    st.line_chart(df_left.select_dtypes(include=['float', 'int']))
                            except Exception as e:
                                st.error(f"Error reading left CSV from Supabase: {e}")
            # === RIGHT SESSION ===
            with col2:
                st.markdown("### Right Player")
                selected_player_right = st.selectbox("Select Player (Right)", player_df["name"], key="right_player")
                player_right_id = int(player_df[player_df["name"] == selected_player_right]["id"].values[0])
                session_res_right = supabase.table("sessions").select("*").eq("player_id", player_right_id).execute()
                right_sessions_df = pd.DataFrame(session_res_right.data) if session_res_right.data else pd.DataFrame()
                if right_sessions_df.empty:
                    st.warning("No sessions found for this player.")
                else:
                    right_sessions_df["label"] = right_sessions_df["date"] + " - " + right_sessions_df["session_name"]
                    session_right = st.selectbox("Select Session (Right)", right_sessions_df["label"], key="right_session")
                    right_match = right_sessions_df[right_sessions_df["label"] == session_right]
                    if not right_match.empty:
                        right_row = right_match.iloc[0]
                        video_source = right_row["video_source"]
                        # --- Insert debug log for right video view ---
                        try:
                            video_id_val = None
                            if video_source.startswith("https://ggqnlqhncarooowdgfpo.supabase.co/storage/v1/object/public/videos/") or video_source.startswith("https://npvwctwurhttdzvbvgcz.supabase.co/storage/v1/object/public/videos/"):
                                video_id_val = os.path.basename(video_source)
                            else:
                                video_id_val = video_source
                            supabase.table("debug_logs").insert({
                                "player_id": player_right_id,
                                "video_id": video_id_val,
                                "view_email_id": user_email,
                                "is_admin": admin_mode,
                                "is_user": not admin_mode
                            }).execute()
                        except Exception as e:
                            st.warning(f"Could not log video view: {e}")
                        # --- End debug log insert ---
                        if video_source.startswith("http"):
                            if "youtube.com" in video_source or "youtu.be" in video_source:
                                video_id = extract_youtube_id(video_source)
                                if video_id:
                                    st.video(f"https://www.youtube.com/embed/{video_id}")
                                else:
                                    st.warning("⚠️ Invalid YouTube link for right session.")
                            else:
                                st.video(video_source)
                        else:
                            st.warning("⚠️ Local video file not found for right session.")
                        st.subheader("Session Notes (Right)")
                        st.markdown(right_row["notes"].replace('\n', '  \n') if right_row["notes"] else "_No notes provided._", unsafe_allow_html=True)
                        csv_path_right = right_row["kinovea_csv"]
                        if not csv_path_right or not csv_path_right.lower().endswith(".csv"):
                            st.info("No Kinovea data uploaded for this session.")
                        else:
                            try:
                                response = requests.get(csv_path_right)
                                response.raise_for_status()
                                df_right = pd.read_csv(io.StringIO(response.text))
                                if "Time (ms)" in df_right.columns:
                                    available_metrics_right = [col for col in df_right.columns if col in COLOR_MAP]
                                    selected_right_metrics = st.multiselect(
                                        "Select metrics to show (Right)",
                                        options=available_metrics_right,
                                        default=available_metrics_right,
                                        key="metric_select_right",
                                        help="Select which metrics to plot for the right session.",
                                        max_selections=None
                                    )
                                    plot_custom_lines(df_right, chart_key="right_plot", selected_metrics=selected_right_metrics)
                                else:
                                    st.warning("Column 'Time (ms)' not found in right session.")
                                    st.line_chart(df_right.select_dtypes(include=['float', 'int']))
                            except Exception as e:
                                st.error(f"Error reading right CSV from Supabase: {e}")
    # === TAB 4: Admin Tools ===
    with tab4:
        if not admin_mode:
            st.header("User Tools")
            st.markdown("---")
            # --- Delete a Session (user can only delete their own) ---
            st.subheader("Delete a Session")
            # Get all players for this user
            player_query = supabase.table("players").select("id", "name").eq("user_email", user_email)
            player_res = player_query.execute()
            player_df = pd.DataFrame(player_res.data) if player_res.data else pd.DataFrame()
            selected_player_id = None
            selected_session_id = None
            session_df = pd.DataFrame()
            if not player_df.empty:
                player_name = st.selectbox("Select a player", player_df["name"], key="user_admin_player_select")
                selected_player_id = int(player_df[player_df["name"] == player_name]["id"].values[0])
                # Get sessions for this player (only user's sessions)
                session_res = supabase.table("sessions").select("id", "date", "session_name").eq("player_id", selected_player_id).eq("user_email", user_email).execute()
                session_df = pd.DataFrame(session_res.data) if session_res.data else pd.DataFrame()
                if not session_df.empty:
                    session_df["label"] = session_df["date"] + " - " + session_df["session_name"]
                    session_label = st.selectbox("Select a session to delete", session_df["label"], key="user_admin_session_select")
                    selected_session_id = int(session_df[session_df["label"] == session_label]["id"].values[0])
                    confirm_delete = st.checkbox("I understand this will permanently delete the session and its files.", key="user_admin_confirm_delete")
                    if st.button("Delete Session", disabled=not confirm_delete):
                        try:
                            session_row = session_df[session_df["id"] == selected_session_id].iloc[0]
                            kinovea_csv_url = session_row.get("kinovea_csv", "")
                            if kinovea_csv_url:
                                if "/csvs/" in kinovea_csv_url:
                                    file_path = kinovea_csv_url.split("/csvs/")[-1]
                                    supabase.storage.from_("csvs").remove([file_path])
                                elif "/videos/" in kinovea_csv_url:
                                    file_path = kinovea_csv_url.split("/videos/")[-1]
                                    supabase.storage.from_("videos").remove([file_path])
                            supabase.table("sessions").delete().eq("id", selected_session_id).eq("user_email", user_email).execute()
                            st.success("Session and its files deleted.")
                        except Exception as e:
                            st.error(f"Error deleting session: {e}")
            else:
                st.info("No players found.")
            st.markdown("---")
            # --- Raw Database (user only) ---
            st.subheader("Raw Database")
            show_raw = st.checkbox("Show Raw Database (Players + Sessions)")
            if show_raw:
                st.markdown("**Players Table**")
                player_all_res = supabase.table("players").select("*").eq("user_email", user_email).execute()
                player_all_df = pd.DataFrame(player_all_res.data) if player_all_res.data else pd.DataFrame()
                st.dataframe(player_all_df, height=300, use_container_width=True)
                st.markdown("**Sessions Table**")
                session_all_res = supabase.table("sessions").select("*").eq("user_email", user_email).execute()
                session_all_df = pd.DataFrame(session_all_res.data) if session_all_res.data else pd.DataFrame()
                st.dataframe(session_all_df, height=300, use_container_width=True)
            return
        st.header("Admin Tools")
        st.markdown("---")
        # --- Delete a Session ---
        st.subheader("Delete a Session")
        # Get all players for this user (or all if admin)
        player_query = supabase.table("players").select("id", "name")
        if not admin_mode:
            player_query = player_query.eq("user_email", user_email)
        player_res = player_query.execute()
        player_df = pd.DataFrame(player_res.data) if player_res.data else pd.DataFrame()
        selected_player_id = None
        selected_session_id = None
        session_df = pd.DataFrame()
        if not player_df.empty:
            player_name = st.selectbox("Select a player", player_df["name"], key="admin_player_select")
            selected_player_id = int(player_df[player_df["name"] == player_name]["id"].values[0])
            # Get sessions for this player
            session_res = supabase.table("sessions").select("id", "date", "session_name").eq("player_id", selected_player_id).execute()
            session_df = pd.DataFrame(session_res.data) if session_res.data else pd.DataFrame()
            if not session_df.empty:
                session_df["label"] = session_df["date"] + " - " + session_df["session_name"]
                session_label = st.selectbox("Select a session to delete", session_df["label"], key="admin_session_select")
                selected_session_id = int(session_df[session_df["label"] == session_label]["id"].values[0])
                confirm_delete = st.checkbox("I understand this will permanently delete the session and its files.", key="admin_confirm_delete")
                if st.button("Delete Session", disabled=not confirm_delete):
                    try:
                        # Get session row for file URLs
                        session_row = session_df[session_df["id"] == selected_session_id].iloc[0]
                        # Delete CSV/video from storage if present
                        kinovea_csv_url = session_row.get("kinovea_csv", "")
                        if kinovea_csv_url:
                            if "/csvs/" in kinovea_csv_url:
                                file_path = kinovea_csv_url.split("/csvs/")[-1]
                                supabase.storage.from_("csvs").remove([file_path])
                            elif "/videos/" in kinovea_csv_url:
                                file_path = kinovea_csv_url.split("/videos/")[-1]
                                supabase.storage.from_("videos").remove([file_path])
                        # Delete session row
                        supabase.table("sessions").delete().eq("id", selected_session_id).execute()
                        # Check if player has any more sessions
                        remaining_sessions = supabase.table("sessions").select("id").eq("player_id", selected_player_id).execute()
                        if not remaining_sessions.data:
                            # Delete player if no more sessions
                            supabase.table("players").delete().eq("id", selected_player_id).execute()
                        st.success("Session and its files deleted. Player deleted if no more sessions remain.")
                    except Exception as e:
                        st.error(f"Error deleting session: {e}")
        else:
            st.info("No players found.")
        st.markdown("---")
        # --- Delete Players With No Sessions ---
        st.subheader("Delete Players With No Sessions")
        # Find players with no sessions
        player_ids = player_df["id"].tolist() if not player_df.empty else []
        players_no_sessions = []
        if player_ids:
            for pid in player_ids:
                session_count = supabase.table("sessions").select("id").eq("player_id", pid).execute()
                if not session_count.data:
                    players_no_sessions.append(pid)
        if not players_no_sessions:
            st.success("No players found without session data.")
        else:
            if st.button("Delete All Players With No Sessions"):
                try:
                    for pid in players_no_sessions:
                        supabase.table("players").delete().eq("id", pid).execute()
                    st.success("Deleted all players without session data.")
                except Exception as e:
                    st.error(f"Error deleting players: {e}")
        st.markdown("---")
        # --- Raw Database ---
        st.subheader("Raw Database")
        show_raw = st.checkbox("Show Raw Database (Players + Sessions)")
        if show_raw:
            # Show players
            st.markdown("**Players Table**")
            # Fetch all player fields
            if admin_mode:
                player_all_res = supabase.table("players").select("*").execute()
            else:
                player_all_res = supabase.table("players").select("*").eq("user_email", user_email).execute()
            player_all_df = pd.DataFrame(player_all_res.data) if player_all_res.data else pd.DataFrame()
            # Set height for vertical scroll, use_container_width for horizontal scroll
            st.dataframe(player_all_df, height=300, use_container_width=True)
            # Show sessions
            if admin_mode:
                session_all_res = supabase.table("sessions").select("*").execute()
            else:
                session_all_res = supabase.table("sessions").select("*").eq("user_email", user_email).execute()
            session_all_df = pd.DataFrame(session_all_res.data) if session_all_res.data else pd.DataFrame()
            st.markdown("**Sessions Table**")
            st.dataframe(session_all_df, height=300, use_container_width=True)
