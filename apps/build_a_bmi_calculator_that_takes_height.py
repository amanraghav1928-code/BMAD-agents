import streamlit as st
import pandas as pd
import numpy as np

# Define color palette
PRIMARY_COLOR = "#6C63FF"
SECONDARY_COLOR = "#F50057"
BACKGROUND_COLOR = "#0F0F1A"
SURFACE_COLOR = "#1A1A2E"
TEXT_COLOR = "#FFFFFF"
SUCCESS_COLOR = "#00E676"
WARNING_COLOR = "#FFD740"
DANGER_COLOR = "#FF5252"

# Define typography
FONT = "Inter"
HEADING_FONT_SIZE = 2
BODY_FONT_SIZE = 1

# Define layout
STYLE = "dark glassmorphism"
CARDS = "rounded-2xl, box-shadow, glassmorphism blur"
SPACING = 24
GAP = 16

# Define animations
ANIMATION_DURATION = 0.3

def calculate_bmi(height, weight):
    try:
        height_in_meters = height / 100
        bmi = weight / (height_in_meters ** 2)
        return bmi
    except ZeroDivisionError:
        st.error("Height cannot be zero.")
        return None
    except Exception as e:
        st.error("An error occurred: " + str(e))
        return None

def get_bmi_category(bmi):
    if bmi < 18.5:
        return "Underweight"
    elif bmi < 25:
        return "Normal"
    elif bmi < 30:
        return "Overweight"
    else:
        return "Obese"

def get_health_tip(bmi_category):
    if bmi_category == "Underweight":
        return "You are underweight. Consider eating more nutritious food to gain weight in a healthy way."
    elif bmi_category == "Normal":
        return "You are at a normal weight. Keep up the good work and maintain a healthy lifestyle."
    elif bmi_category == "Overweight":
        return "You are overweight. Consider reducing your calorie intake and exercising regularly to lose weight."
    else:
        return "You are obese. Consider seeking professional help to develop a weight loss plan."

def main():
    st.title("BMI Calculator")
    st.write("This application calculates your Body Mass Index (BMI) based on your height and weight.")

    with st.form("bmi_form"):
        height = st.number_input("Enter your height in centimeters", min_value=0, max_value=250)
        weight = st.number_input("Enter your weight in kilograms", min_value=0, max_value=500)
        submit_button = st.form_submit_button("Calculate BMI")

    if submit_button:
        bmi = calculate_bmi(height, weight)
        if bmi is not None:
            bmi_category = get_bmi_category(bmi)
            health_tip = get_health_tip(bmi_category)

            st.write("Your BMI is: " + str(round(bmi, 2)))
            st.write("Your BMI category is: " + bmi_category)

            if bmi_category == "Underweight":
                st.markdown(f"<font color='{DANGER_COLOR}'>You are underweight.</font>", unsafe_allow_html=True)
            elif bmi_category == "Normal":
                st.markdown(f"<font color='{SUCCESS_COLOR}'>You are at a normal weight.</font>", unsafe_allow_html=True)
            elif bmi_category == "Overweight":
                st.markdown(f"<font color='{WARNING_COLOR}'>You are overweight.</font>", unsafe_allow_html=True)
            else:
                st.markdown(f"<font color='{DANGER_COLOR}'>You are obese.</font>", unsafe_allow_html=True)

            st.write("Health tip: " + health_tip)

            st.write("Your height in meters is: " + str(round(height / 100, 2)))
            st.write("Your weight in pounds is: " + str(round(weight * 2.20462, 2)))

if __name__ == "__main__":
    main()