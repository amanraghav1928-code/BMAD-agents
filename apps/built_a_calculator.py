import streamlit as st
import numpy as np
from scipy import constants
import altair as alt
import matplotlib.pyplot as plt

# UI Design System
st.markdown(
    """
    <style>
    body {
        background-color: #0F0F1A;
        font-family: Inter, sans-serif;
    }
    .stApp {
        background-color: #0F0F1A;
    }
    .stHeader {
        background-color: #0F0F1A;
        color: #FFFFFF;
    }
    .stTitle {
        font-size: 2rem;
        font-weight: bold;
        color: #6C63FF;
    }
    .stSubTitle {
        font-size: 1rem;
        font-weight: regular;
        color: #FFFFFF;
    }
    .stCard {
        background-color: #1A1A2E;
        padding: 24px;
        border-radius: 2xl;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.2);
        glassmorphism blur;
    }
    .stButton {
        background-color: #6C63FF;
        color: #FFFFFF;
        padding: 12px 24px;
        border-radius: 2xl;
        font-size: 1rem;
        font-weight: bold;
    }
    .stInput {
        padding: 12px 24px;
        border-radius: 2xl;
        font-size: 1rem;
        font-weight: regular;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Color Palette
primary_color = "#6C63FF"
secondary_color = "#F50057"
background_color = "#0F0F1A"
surface_color = "#1A1A2E"
text_color = "#FFFFFF"
success_color = "#00E676"
warning_color = "#FFD740"
danger_color = "#FF5252"

# Calculator
def calculator():
    try:
        # Basic Arithmetic Operations
        num1 = st.number_input("Number 1", min_value=-1000, max_value=1000, value=0)
        num2 = st.number_input("Number 2", min_value=-1000, max_value=1000, value=0)
        operation = st.selectbox("Operation", ["Addition", "Subtraction", "Multiplication", "Division"])
        if operation == "Addition":
            result = num1 + num2
        elif operation == "Subtraction":
            result = num1 - num2
        elif operation == "Multiplication":
            result = num1 * num2
        elif operation == "Division":
            if num2 != 0:
                result = num1 / num2
            else:
                st.error("Error: Division by zero is not allowed.")
                return
        st.write(f"Result: {result}")

        # Algebraic Expressions
        algebraic_expression = st.text_input("Algebraic Expression", value="")
        try:
            result = eval(algebraic_expression)
            st.write(f"Result: {result}")
        except Exception as e:
            st.error(f"Error: {str(e)}")

        # Trigonometric Functions
        angle = st.number_input("Angle (in degrees)", min_value=-360, max_value=360, value=0)
        trigonometric_function = st.selectbox("Trigonometric Function", ["Sine", "Cosine", "Tangent"])
        if trigonometric_function == "Sine":
            result = np.sin(np.radians(angle))
        elif trigonometric_function == "Cosine":
            result = np.cos(np.radians(angle))
        elif trigonometric_function == "Tangent":
            result = np.tan(np.radians(angle))
        st.write(f"Result: {result}")

        # Memory Functions
        memory = st.session_state.get("memory", {})
        st.write("Memory:")
        for key, value in memory.items():
            st.write(f"{key}: {value}")
        new_key = st.text_input("New Key")
        new_value = st.number_input("New Value", min_value=-1000, max_value=1000, value=0)
        if st.button("Add to Memory"):
            memory[new_key] = new_value
            st.session_state.memory = memory
            st.write(f"Added {new_key}: {new_value} to memory.")

        # Unit Conversion
        unit = st.selectbox("Unit", ["Length", "Mass", "Time"])
        value = st.number_input("Value", min_value=-1000, max_value=1000, value=0)
        if unit == "Length":
            converted_value = value * constants.meter
            st.write(f"Converted value: {converted_value} meters")
        elif unit == "Mass":
            converted_value = value * constants.kilogram
            st.write(f"Converted value: {converted_value} kilograms")
        elif unit == "Time":
            converted_value = value * constants.second
            st.write(f"Converted value: {converted_value} seconds")

        # Graphing Function
        x = np.linspace(-10, 10, 100)
        y = np.sin(x)
        chart = alt.Chart(alt.Data(values=[{"x": x_i, "y": y_i} for x_i, y_i in zip(x, y)])).mark_line().encode(x="x", y="y")
        st.altair_chart(chart)

        # History Function
        history = st.session_state.get("history", [])
        st.write("History:")
        for item in history:
            st.write(item)
        new_item = st.text_input("New Item")
        if st.button("Add to History"):
            history.append(new_item)
            st.session_state.history = history
            st.write(f"Added {new_item} to history.")

    except Exception as e:
        st.error(f"Error: {str(e)}")

# Main Function
def main():
    st.title("CalcMate")
    st.subheader("A user-friendly calculator designed to simplify complex calculations for users.")
    calculator()

# Run the application
if __name__ == "__main__":
    main()