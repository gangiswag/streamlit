import streamlit as st
st.set_page_config(layout="wide")

import json, io
import time
import random
import uuid
import os
from difflib import SequenceMatcher
from google.cloud import storage
from google.oauth2 import service_account

# Load GCP secrets
gcp_conf = st.secrets["gcp"]
sa_info = json.loads(gcp_conf["service_account_info"])

# Build GCS client
credentials = service_account.Credentials.from_service_account_info(sa_info)
client      = storage.Client(project=gcp_conf["project_id"], credentials=credentials)
bucket      = client.bucket(gcp_conf["bucket_name"])

# Paths
# JSON_PATH = "human_data_single_edit_v2.json"
OUTPUT_PATH = "."

# if logs directory doesn't exist, create it
if not os.path.exists("logs"):
    os.makedirs("logs")

@st.cache_data
def load_entries(path):
    """
    Load JSON entries and assign a stable UID to each entry.
    Cached so it's only read and UUIDs generated once per session.
    """
    with open(path, "r") as f:
        raw = json.load(f)
    entries = list(raw.values()) if isinstance(raw, dict) else raw
    for index, entry in enumerate(entries):
        entry.setdefault('uid', str(index))
    return entries

@st.cache_data
def load_entries_from_file(uploaded_file):
    """
    Load JSON entries from an uploaded file object and assign a stable UID to each entry.
    Cached so it's only read and UUIDs generated once per session for the same file.
    """
    raw = json.load(uploaded_file)
    entries_list = list(raw.values()) if isinstance(raw, dict) else raw
    for index, entry in enumerate(entries_list):
        entry.setdefault('uid', str(uuid.uuid4())) # Use uuid for more robust unique IDs
    return entries_list

# Initialize state once
if 'entries' not in st.session_state:
    st.session_state.entries = [] # Initialize as empty
    st.session_state.entries_by_uid = {}
    st.session_state.uids = []
    st.session_state.current_uid = None
    st.session_state.file_processed = False

# File uploader
uploaded_file = st.sidebar.file_uploader("Upload JSON file", type="json")

if uploaded_file is not None and not st.session_state.file_processed:
    try:
        # To read file as string:
        # string_data = uploaded_file.read().decode()
        # st.write(string_data) # Optional: display raw string
        
        # To load json:
        # uploaded_file.seek(0) # Reset file pointer to the beginning
        
        st.session_state.entries = load_entries_from_file(uploaded_file)
        st.session_state.entries_by_uid = {e['uid']: e for e in st.session_state.entries}
        st.session_state.uids = list(st.session_state.entries_by_uid.keys())
        if st.session_state.uids:
            st.session_state.current_uid = st.session_state.uids[0]
        st.session_state.file_processed = True # Mark file as processed
        st.sidebar.success("File loaded successfully!")
        st.rerun() # Rerun to update the UI with loaded data
    except json.JSONDecodeError:
        st.sidebar.error("Invalid JSON file. Please upload a valid JSON file.")
        st.session_state.file_processed = False # Reset on error
    except Exception as e:
        st.sidebar.error(f"An error occurred: {e}")
        st.session_state.file_processed = False # Reset on error


# Only proceed if a file has been processed and entries are loaded
if not st.session_state.get('file_processed') or not st.session_state.get('entries'):
    st.info("Please upload a JSON file to begin.")
    st.stop()

# Aliases
entries = st.session_state.entries
entries_by_uid = st.session_state.entries_by_uid
uids = st.session_state.uids
selection = st.session_state.current_uid

# Handle case where uids might be empty after a bad file or initial load
if not uids or selection is None:
    st.error("No entries found or no selection made. Please check the uploaded file.")
    st.stop()

# Sidebar: select entry
st.sidebar.header("Select Entry")
sel_index = uids.index(selection)
new_selection = st.sidebar.selectbox(
    "Entity (ID: Section)",
    options=uids,
    format_func=lambda uid: (
        f"{entries_by_uid[uid]['entity_id']}: "
        f"{entries_by_uid[uid].get('section_name','')} "
        f"({uid[:8]})"      # show first 8 chars of the UID
    ),
    index=sel_index
)
# Reset per-review state on change
if new_selection != selection:
    for key in list(st.session_state.keys()):
        if key.startswith(('q', 'claims_', 'review_submitted')):
            del st.session_state[key]
    st.session_state.current_uid = new_selection
    selection = new_selection

# Current entry
entry = entries_by_uid[selection]

# CSS styling
st.markdown(
    """
    <style>
    body { font-size: 18px !important; }
    .added { background-color: #c8e6c9; }
    .removed { background-color: #ffcdd2; }
    del { text-decoration: line-through; color: #d32f2f; }
    ins { text-decoration: none; color: #388e3c; }
    .bold-large { font-size: 22px; font-weight: bold; }
    .section-desc { font-style: italic; color: #555; }
    .diff-content { font-size: 18px; }
    [role="radiogroup"] label { font-size: 18px !important; }
    [data-testid="stRadio"] > div { font-size: 18px !important; }
    .stRadio > div:first-child { margin-top: 10px; margin-bottom: 10px; }
    </style>
    """,
    unsafe_allow_html=True
)

# Header
st.markdown(f"<div class='bold-large'>Entity Name: {entry['entity_id']}</div>", unsafe_allow_html=True)
st.markdown(f"<div class='bold-large'>Section Name: {entry.get('section_name','')}</div>", unsafe_allow_html=True)

# Wiki link
wiki_url = f"https://en.wikipedia.org/wiki/{entry['entity_id'].replace(' ', '_')}"
st.markdown(f"Wikipedia Page: [View on Wikipedia]({wiki_url})")

# Entity Links
st.markdown("**Entity Links:**")
if entry.get('url'):
    st.markdown(f"- [{entry['url'][0]}]({entry['url'][0]})")

# Diff highlight function
def get_text_diff_v2_highlight(a, b):
    a_words, b_words = a.split(), b.split()
    sm = SequenceMatcher(None, a_words, b_words)
    a_hl, b_hl = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            a_hl += a_words[i1:i2]
            b_hl += b_words[j1:j2]
        elif tag == 'delete':
            a_hl.append(f"<del>{' '.join(a_words[i1:i2])}</del>")
        elif tag == 'insert':
            b_hl.append(f"<ins>{' '.join(b_words[j1:j2])}</ins>")
        elif tag == 'replace':
            a_hl.append(f"<del>{' '.join(a_words[i1:i2])}</del>")
            b_hl.append(f"<ins>{' '.join(b_words[j1:j2])}</ins>")
    return ' '.join(a_hl), ' '.join(b_hl)

# Display diff side-by-side
orig = entry.get('original_section', '')
upd = entry.get('agent_updated_section', '')
a_hl, b_hl = get_text_diff_v2_highlight(orig, upd)
col1, col2 = st.columns(2, gap="large")
with col1:
    st.subheader("Before")
    st.markdown(f'<div class="diff-content">{a_hl}</div>', unsafe_allow_html=True)
with col2:
    st.subheader("After")
    st.markdown(f'<div class="diff-content">{b_hl}</div>', unsafe_allow_html=True)

# Initialize question states
st.session_state.setdefault('q1', None)
st.session_state.setdefault('q3', None)

# Questions text
q_texts = entry.get('questions', [
    "Question 1: Provided above is a suggested edit for the Wikipedia article. Please identify any errors with the suggested edit (select all that apply)",
    "Question 2: Would you (1) accept, (2) accept w/ revision, and (3) reject the suggested edit above?",
    "Question 3: Was the human edit placed in the correct section of the Wikipedia page?"
])

# Q1
# Q1 as checkbox
q1_key_prefix = f"q1_{selection[:8]}"  # change prefix based on entry
q1_options = {
    "style": "Stylistic/clarity: Phrasing redundant or tone is too informal",
    "minor_fix": "Minor factual fix: Small date/number correction needed",
    "formatting": "Wikipedia Formatting: Text in the human edit is not formatted properly",
    "citation": "Missing citation(s): One or more facts in the edit lack a reference",
    "subjective": "Subjective: Opinion or superlative without attribution (“most unexpected”)",
    "duplicate": "Duplicate: Overlaps substantially with another accepted fact.",
    "insignificant": "Insignificant: Majority of the edit is not worthy of being included in Wikipedia",
    "irrelevant": "Irrelevant: The facts presented in the edit are not relevant for the entity",
    "policy": "Policy violation: Conflict with WP:OR, WP:NPOV, etc.",
    "other": "Other:"
}

st.markdown(f'<div class="diff-content"><br><b>{q_texts[0]}</b><br></div>', unsafe_allow_html=True)

selected_q1_options = []
show_other_text = False
for subkey, label in q1_options.items():
    full_key = f"{q1_key_prefix}_{subkey}"
    checked = st.checkbox(label, key=full_key)
    if checked:
        selected_q1_options.append(label)
        if subkey == "other":
            show_other_text = True

# Text input if "Other:" selected
other_input_key = f"{q1_key_prefix}_other_text"
other_text = ""
if show_other_text:
    other_text = st.text_input("Please specify other issue:", key=other_input_key)
    if other_text.strip():
        selected_q1_options.append(f"Other (Please specify reason below): {other_text.strip()}")

# Store in session
st.session_state['q1'] = selected_q1_options if selected_q1_options else None


# st.checkbox("", ["Accept", "Accept with Revision", "Reject"], key='q1')
# if st.session_state['q1'] == "Accept with Revision":
#     st.multiselect("Reason:", [
#         "Stylistic/clarity: Phrasing redundant or tone is too informal",
#         "Minor factual fix: Small date/number correction needed",
#         "Wikipedia Formatting: Text in the human edit is not formatted properly",
#         "Missing citation(s): One or more facts in the edit lack a reference",
#         "Other"
#     ], key='q1_rev')
# elif st.session_state['q1'] == "Reject":
#     st.multiselect("Reason:", [
#         "Insignificant: Majority of the edit is not worthy of being included in Wikipedia",
#         "Irrelevant: The facts presented in the edit are not relevant for the entity",
#         "Policy violation: Conflict with WP:OR, WP:NPOV, etc..",
#         "Other"
#     ], key='q1_rev')

# Q2
# claims_key = f"claims_{selection}"
# if st.session_state['q1']:
#     st.markdown(f'<div class="diff-content"><b>{q_texts[1]}</b></div>', unsafe_allow_html=True)
#     if claims_key not in st.session_state:
#         st.session_state[claims_key] = random.sample(entry.get('claims', []), min(5, len(entry.get('claims', []))))
#     for i, claim in enumerate(st.session_state[claims_key], start=1):
#         st.markdown(f'<div class="diff-content">Claim {i}: {claim}</div>', unsafe_allow_html=True)
#         st.radio("", ["Accept","Accept w/ Revision", "Reject"], key=f'q2_{i}', index=None)
        # if st.session_state.get(f'q2_{i}') == "Reject":
        #     st.multiselect("Reasons:", [
        #         "Subjective: Opinion or superlative without attribution ('most unexpected')",
        #         "Trivial/insignificant: Not major enough to be included",
        #         "Duplicate: Overlaps substantially with another accepted fact.",
        #         "Out of scope: Not directly related to the target entity.",
        #         "Other"
        #     ], key=f'q2_{i}_reasons')
# Q2
if st.session_state['q1']:
    st.markdown(f'<div class="diff-content"><b>{q_texts[1]}</b></div>', unsafe_allow_html=True)
    st.radio("", ["Accept","Accept w/ Revision", "Reject"], key=f'q2', index=None)



# Q3 & Submit
if st.session_state['q1'] and st.session_state['q2']:
    st.markdown(f'<div class="diff-content"><b>{q_texts[2]}</b></div>', unsafe_allow_html=True)
    st.radio("", ["Yes", "If No, which section:"], key='q3')
    if st.session_state.get('q3') == "If No, which section:":
        st.text_input("Section to write to:", key='q3_section')
    submitted = st.button("Submit Review", key="submit_review")
    if submitted:
        review = {
            'q1': st.session_state['q1'],
            "q2": st.session_state['q2'],
            'q3': st.session_state['q3'],
            'q3_section': st.session_state.get('q3_section')
        }
        # for i in range(1, len(st.session_state.get(claims_key, []))+1):
        #     text = st.session_state[claims_key][i-1]
        #     review['claims'][f'claim_{i}'] = {
        #         'text': text,
        #         'response': st.session_state.get(f'q2_{i}'),
        #         'reasons': st.session_state.get(f'q2_{i}_reasons')
        #     }
        entry['review'] = review
        # Save updated entries list
        # saved_path = os.path.join(OUTPUT_PATH, f"{selection}.json")
        # with open(saved_path, 'w') as out_f:
        #     json.dump(entry, out_f, indent=4)
        
        # Prepare JSON data for upload
        json_string = json.dumps(entry, indent=4)
        json_bytes = json_string.encode('utf-8')
        buf = io.BytesIO(json_bytes)
        buf.seek(0)

        # choose a “folder” in your bucket
        blob = bucket.blob(f"test/{selection}.json")
        blob.upload_from_file(buf, content_type="application/json")
        st.success("Review submitted and saved to GCS.")
        st.session_state['review_submitted'] = True

    # Next-step buttons
    if st.session_state.get('review_submitted'):
        next_idx = (uids.index(selection) + 1) % len(uids)
        next_uid = uids[next_idx]
        next_entry = entries_by_uid[next_uid]
        st.info(f"Ready to move to next entry: {next_entry['entity_id']}: {next_entry.get('section_name','')}")
        col_next, col_stay = st.columns(2)
        with col_next:
            if st.button("Go to Next Entry", key="go_next"):
                # Clear per-review keys
                for k in list(st.session_state.keys()):
                    if (
                        k.startswith(('q2_', 'q3', 'review_submitted')) or 
                        k == 'q1'
                    ):
                        del st.session_state[k]
                st.session_state.current_uid = next_uid
                st.rerun()
        with col_stay:
            if st.button("Stay on This Entry", key="stay"):
                st.info("You can review or revise your answers.")
