import streamlit as st
st.title('Abouttt')

test_list = ['Un', 'deux', 'trois']

if('choix' not in st.session_state):
    st.session_state['choix'] = '0'

choix = st.selectbox("choix", test_list)
st.session_state['choix'] = choix
