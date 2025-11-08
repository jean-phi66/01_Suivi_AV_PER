import streamlit as st
from streamlit import session_state as ss
st.title("TESTTTT")
st.dataframe(ss['df_allocations'])
#st.write(st.session_state['choix'])
