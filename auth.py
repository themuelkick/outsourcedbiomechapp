import streamlit as st
from supabase import create_client, Client
import os

@st.cache_resource
def get_supabase_client():
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = get_supabase_client()

# Add this at the top of the file
try:
    from your_main_app import is_admin
except ImportError:
    ADMIN_EMAILS = st.secrets.get("ADMIN_EMAILS", [])
    def is_admin(email):
        return email in ADMIN_EMAILS

if 'user' not in st.session_state:
    st.session_state.user = None
if 'profile' not in st.session_state:
    st.session_state.profile = {}

def login():
    st.subheader("Login")
    email = st.text_input("Email", key="login_email")
    pwd = st.text_input("Password", type="password", key="login_pwd")
    if st.button("Login"):
        try:
            # Query the profiles table for a matching email and password
            result = supabase.table("profiles").select("id, email, is_admin").eq("email", email).eq("password", pwd).execute()
            if result.data and len(result.data) > 0:
                user_profile = result.data[0]
                st.session_state.user = user_profile["id"]
                st.session_state.user_email = user_profile["email"]
                st.session_state.profile = {"is_admin": user_profile.get("is_admin", False)}
                st.success("✅ Logged in")
                st.rerun()
            else:
                st.error("❌ Login failed. Please check your credentials.")
        except Exception as e:
            st.error(f"❌ Login error: {e}")

def signup():
    st.subheader("Create Account")
    email = st.text_input("Email", key="su_email")
    pwd = st.text_input("Password", type="password", key="su_pwd")
    if st.button("Sign Up"):
        try:
            # Check if email already exists
            existing = supabase.table("profiles").select("id").eq("email", email).execute()
            if existing.data and len(existing.data) > 0:
                st.error("❌ Email already registered. Please log in or use another email.")
                return
            # Insert new profile with email and password
            import uuid
            user_id = str(uuid.uuid4())
            profile_data = {"id": user_id, "email": email, "password": pwd, "is_admin": is_admin(email)}
            supabase.table("profiles").insert(profile_data).execute()
            st.success("✅ Account created successfully! You can now log in.")
        except Exception as e:
            st.error(f"❌ Sign-up error: {e}")

def auth_screen():
    st.title("Login Page")
    option = st.selectbox("Choose an Action:", ["Login", "Sign Up"])
    if option == "Login":
        login()
    else:
        signup()

def sign_out():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.session = None
    st.session_state.user_email = None
    st.session_state.profile = {}
    st.rerun()

def main():
    auth_screen()

if __name__ == "__main__":
    main()









