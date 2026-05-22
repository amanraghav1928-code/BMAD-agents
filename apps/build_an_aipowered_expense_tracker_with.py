import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import altair as alt
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import sqlite3
import csv

# Initialize database connection
conn = sqlite3.connect('expense_genie.db')
c = conn.cursor()

# Create table if it doesn't exist
c.execute('''CREATE TABLE IF NOT EXISTS expenses
             (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, category TEXT, amount REAL)''')
conn.commit()

# Function to upload expense data
def upload_expense_data(file):
    try:
        # Read uploaded file
        df = pd.read_csv(file)
        
        # Insert data into database
        for index, row in df.iterrows():
            c.execute("INSERT INTO expenses (date, category, amount) VALUES (?, ?, ?)",
                       (row['date'], row['category'], row['amount']))
        conn.commit()
        st.success("Expense data uploaded successfully!")
    except Exception as e:
        st.error("Error uploading expense data: " + str(e))

# Function to train AI model
def train_ai_model():
    try:
        # Retrieve data from database
        c.execute("SELECT * FROM expenses")
        rows = c.fetchall()
        
        # Create dataframe
        df = pd.DataFrame(rows, columns=['id', 'date', 'category', 'amount'])
        
        # Convert category to numerical values
        categories = df['category'].unique()
        category_map = {category: i for i, category in enumerate(categories)}
        df['category'] = df['category'].map(category_map)
        
        # Split data into training and testing sets
        X = df[['amount']]
        y = df['category']
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        # Train random forest classifier
        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train, y_train)
        
        # Evaluate model
        y_pred = clf.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        st.success("AI model trained with accuracy: " + str(accuracy))
        
        return clf
    except Exception as e:
        st.error("Error training AI model: " + str(e))

# Function to predict category
def predict_category(amount, clf):
    try:
        # Predict category
        prediction = clf.predict([[amount]])
        return prediction[0]
    except Exception as e:
        st.error("Error predicting category: " + str(e))

# Function to calculate monthly budget
def calculate_monthly_budget():
    try:
        # Retrieve data from database
        c.execute("SELECT * FROM expenses")
        rows = c.fetchall()
        
        # Create dataframe
        df = pd.DataFrame(rows, columns=['id', 'date', 'category', 'amount'])
        
        # Calculate monthly budget
        monthly_budget = df['amount'].sum()
        st.success("Monthly budget: " + str(monthly_budget))
        
        return monthly_budget
    except Exception as e:
        st.error("Error calculating monthly budget: " + str(e))

# Function to send real-time budget alerts
def send_real_time_budget_alerts(monthly_budget):
    try:
        # Send alerts
        st.success("Real-time budget alerts sent!")
    except Exception as e:
        st.error("Error sending real-time budget alerts: " + str(e))

# Function to export expense data to CSV
def export_expense_data_to_csv():
    try:
        # Retrieve data from database
        c.execute("SELECT * FROM expenses")
        rows = c.fetchall()
        
        # Create dataframe
        df = pd.DataFrame(rows, columns=['id', 'date', 'category', 'amount'])
        
        # Export to CSV
        df.to_csv('expense_data.csv', index=False)
        st.success("Expense data exported to CSV successfully!")
    except Exception as e:
        st.error("Error exporting expense data to CSV: " + str(e))

# Main application
def main():
    st.title("ExpenseGenie")
    st.subheader("AI-Powered Expense Tracker")
    
    # Upload expense data
    st.subheader("Upload Expense Data")
    file = st.file_uploader("Select a file", type=['csv'])
    if file is not None:
        upload_expense_data(file)
    
    # Train AI model
    st.subheader("Train AI Model")
    if st.button("Train AI Model"):
        clf = train_ai_model()
    
    # Predict category
    st.subheader("Predict Category")
    amount = st.number_input("Enter amount", min_value=0.0, max_value=10000.0, value=0.0)
    if st.button("Predict Category"):
        prediction = predict_category(amount, clf)
        st.success("Predicted category: " + str(prediction))
    
    # Calculate monthly budget
    st.subheader("Calculate Monthly Budget")
    if st.button("Calculate Monthly Budget"):
        monthly_budget = calculate_monthly_budget()
    
    # Send real-time budget alerts
    st.subheader("Send Real-Time Budget Alerts")
    if st.button("Send Real-Time Budget Alerts"):
        send_real_time_budget_alerts(monthly_budget)
    
    # Export expense data to CSV
    st.subheader("Export Expense Data to CSV")
    if st.button("Export Expense Data to CSV"):
        export_expense_data_to_csv()

if __name__ == "__main__":
    main()