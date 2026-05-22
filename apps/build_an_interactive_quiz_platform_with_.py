import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import hashlib
import time
import os
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# =======================
# CONFIGURATION & CONSTANTS
# =======================

# Security: Use PBKDF2 instead of raw SHA-256
HASH_ITERATIONS = 100_000  # Number of iterations for PBKDF2
SALT_SIZE = 32  # Random salt size in bytes

# Database path
DB_PATH = "quizmaster.db"

# UI Constants
PRIMARY_COLOR = "#6C63FF"
SECONDARY_COLOR = "#F50057"
BACKGROUND_COLOR = "#0F0F1A"
SURFACE_COLOR = "#1A1A2E"
TEXT_COLOR = "#FFFFFF"
SUCCESS_COLOR = "#00E676"
WARNING_COLOR = "#FFD740"
DANGER_COLOR = "#FF5252"

# Quiz settings
DEFAULT_DIFFICULTY = "medium"
DIFFICULTY_LEVELS = ["easy", "medium", "hard"]
QUESTIONS_PER_QUIZ = 5
TIME_LIMIT_PER_QUESTION = 15  # seconds

# =======================
# DATABASE SETUP
# =======================

def init_db() -> None:
    """Initialize the SQLite database with required tables."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Questions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_text TEXT NOT NULL,
                    option_a TEXT NOT NULL,
                    option_b TEXT NOT NULL,
                    option_c TEXT NOT NULL,
                    option_d TEXT NOT NULL,
                    correct_answer TEXT NOT NULL CHECK(correct_answer IN ('A', 'B', 'C', 'D')),
                    difficulty TEXT NOT NULL CHECK(difficulty IN ('easy', 'medium', 'hard')),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Quiz attempts table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS quiz_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    total_questions INTEGER NOT NULL,
                    difficulty TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                )
            """)
            
            conn.commit()
            
            # Insert sample questions if none exist
            cursor.execute("SELECT COUNT(*) FROM questions")
            if cursor.fetchone()[0] == 0:
                _insert_sample_questions(cursor)
                
    except sqlite3.Error as e:
        st.error(f"Database initialization error: {str(e)}")
        raise

def _insert_sample_questions(cursor: sqlite3.Cursor) -> None:
    """Insert sample questions into the database."""
    sample_questions = [
        ("What is the capital of France?", "Berlin", "Madrid", "Paris", "Rome", "C", "easy"),
        ("Which planet is known as the Red Planet?", "Venus", "Mars", "Jupiter", "Saturn", "B", "easy"),
        ("What is 2 + 2?", "3", "4", "5", "6", "B", "easy"),
        ("Who wrote 'Romeo and Juliet'?", "Charles Dickens", "William Shakespeare", "Jane Austen", "Mark Twain", "B", "medium"),
        ("What is the chemical symbol for gold?", "Go", "Gd", "Au", "Ag", "C", "medium"),
        ("In which year did World War II end?", "1944", "1945", "1946", "1947", "B", "medium"),
        ("What is the largest organ in the human body?", "Liver", "Brain", "Skin", "Heart", "C", "hard"),
        ("Which element has the atomic number 1?", "Helium", "Hydrogen", "Oxygen", "Carbon", "B", "hard"),
        ("Who developed the theory of relativity?", "Isaac Newton", "Nikola Tesla", "Albert Einstein", "Stephen Hawking", "C", "hard"),
        ("What is the smallest country in the world?", "Monaco", "Maldives", "Vatican City", "San Marino", "C", "hard")
    ]
    
    cursor.executemany("""
        INSERT INTO questions 
        (question_text, option_a, option_b, option_c, option_d, correct_answer, difficulty)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, sample_questions)

# =======================
# SECURITY UTILITIES
# =======================

def hash_password(password: str, salt: bytes) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, HASH_ITERATIONS)
    return pwd_hash.hex()

def create_password_hash(password: str) -> Tuple[str, str]:
    """Create a password hash and random salt."""
    salt = os.urandom(SALT_SIZE)
    pwd_hash = hash_password(password, salt)
    return pwd_hash, salt.hex()

def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    """Verify a password against its hash and salt."""
    try:
        salt = bytes.fromhex(salt_hex)
        pwd_hash = hash_password(password, salt)
        return pwd_hash == stored_hash
    except Exception:
        return False

# =======================
# DATA MODELS
# =======================

@dataclass
class Question:
    id: int
    question_text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str
    difficulty: str

@dataclass
class QuizAttempt:
    id: int
    user_id: int
    score: int
    total_questions: int
    difficulty: str
    completed_at: datetime

@dataclass
class User:
    id: int
    username: str
    created_at: datetime

# =======================
# DATABASE REPOSITORIES
# =======================

class UserRepository:
    @staticmethod
    def create_user(username: str, password: str) -> bool:
        """Create a new user with hashed password."""
        try:
            pwd_hash, salt = create_password_hash(password)
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                    (username, pwd_hash, salt)
                )
                conn.commit()
            return True
        except sqlite3.IntegrityError:
            st.error("Username already exists.")
            return False
        except Exception as e:
            st.error(f"Error creating user: {str(e)}")
            return False

    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[User]:
        """Authenticate user and return user object if successful."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, username, password_hash, salt, created_at FROM users WHERE username = ?",
                    (username,)
                )
                row = cursor.fetchone()
                
                if row and verify_password(password, row[2], row[3]):
                    return User(id=row[0], username=row[1], created_at=row[4])
                return None
        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            return None

class QuestionRepository:
    @staticmethod
    def get_questions_by_difficulty(difficulty: str, limit: int = 10) -> List[Question]:
        """Get random questions of specified difficulty."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, question_text, option_a, option_b, option_c, option_d, correct_answer, difficulty
                    FROM questions 
                    WHERE difficulty = ?
                    ORDER BY RANDOM() 
                    LIMIT ?
                """, (difficulty, limit))
                
                rows = cursor.fetchall()
                return [
                    Question(
                        id=row[0], question_text=row[1], option_a=row[2], option_b=row[3],
                        option_c=row[4], option_d=row[5], correct_answer=row[6], difficulty=row[7]
                    ) for row in rows
                ]
        except Exception as e:
            st.error(f"Error loading questions: {str(e)}")
            return []

class QuizAttemptRepository:
    @staticmethod
    def save_attempt(user_id: int, score: int, total_questions: int, difficulty: str) -> None:
        """Save quiz attempt to database."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO quiz_attempts (user_id, score, total_questions, difficulty)
                    VALUES (?, ?, ?, ?)
                """, (user_id, score, total_questions, difficulty))
                conn.commit()
        except Exception as e:
            st.error(f"Error saving quiz attempt: {str(e)}")

    @staticmethod
    def get_leaderboard(limit: int = 10) -> pd.DataFrame:
        """Get top quiz scores."""
        try:
            with sqlite3.connect(DB_PATH) as conn:
                df = pd.read_sql_query("""
                    SELECT u.username, qa.score, qa.total_questions, qa.difficulty, qa.completed_at
                    FROM quiz_attempts qa
                    JOIN users u ON qa.user_id = u.id
                    ORDER BY qa.score DESC, qa.completed_at DESC
                    LIMIT ?
                """, conn, params=(limit,))
                
                if not df.empty:
                    df['accuracy'] = (df['score'] / df['total_questions'] * 100).round(1)
                    df['completed_at'] = pd.to_datetime(df['completed_at']).dt.strftime('%Y-%m-%d %H:%M')
                    df.rename(columns={
                        'username': 'Username',
                        'score': 'Score',
                        'total_questions': 'Total',
                        'difficulty': 'Difficulty',
                        'completed_at': 'Completed',
                        'accuracy': 'Accuracy (%)'
                    }, inplace=True)
                return df
        except Exception as e:
            st.error(f"Error loading leaderboard: {str(e)}")
            return pd.DataFrame()

# =======================
# SESSION STATE MANAGEMENT
# =======================

def init_session_state() -> None:
    """Initialize session state variables."""
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
    if 'current_page' not in st.session_state:
        st.session_state.current_page = 'login'
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'quiz_started' not in st.session_state:
        st.session_state.quiz_started = False
    if 'questions' not in st.session_state:
        st.session_state.questions = []
    if 'current_question_index' not in st.session_state:
        st.session_state.current_question_index = 0
    if 'answers' not in st.session_state:
        st.session_state.answers = {}
    if 'start_time' not in st.session_state:
        st.session_state.start_time = None
    if 'time_left' not in st.session_state:
        st.session_state.time_left = TIME_LIMIT_PER_QUESTION
    if 'quiz_completed' not in st.session_state:
        st.session_state.quiz_completed = False
    if 'score' not in st.session_state:
        st.session_state.score = 0

# =======================
# UI COMPONENTS
# =======================

def apply_custom_css() -> None:
    """Apply custom CSS for glassmorphism design."""
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
        
        html, body, [class*="css"] {{
            font-family: 'Inter', sans-serif;
        }}
        
        .stApp {{
            background-color: {BACKGROUND_COLOR};
            color: {TEXT_COLOR};
        }}
        
        .main .block-container {{
            max-width: 1200px;
            padding-top: 2rem;
            padding-bottom: 2rem;
        }}
        
        h1, h2, h3 {{
            color: {TEXT_COLOR} !important;
            font-weight: 700 !important;
        }}
        
        .quiz-card {{
            background: {SURFACE_COLOR};
            border-radius: 1rem;
            padding: 1.5rem;
            margin: 1rem 0;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }}
        
        .quiz-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
        }}
        
        .stButton>button {{
            background-color: {PRIMARY_COLOR};
            color: white;
            border: none;
            border-radius: 0.5rem;
            padding: 0.75rem 1.5rem;
            font-weight: 600;
            transition: all 0.3s ease;
        }}
        
        .stButton>button:hover {{
            background-color: #5a54d8;
            transform: translateY(-1px);
        }}
        
        .secondary-button {{
            background-color: {SECONDARY_COLOR} !important;
        }}
        
        .success-text {{
            color: {SUCCESS_COLOR} !important;
        }}
        
        .danger-text {{
            color: {DANGER_COLOR} !important;
        }}
        
        .timer {{
            font-size: 1.5rem;
            font-weight: bold;
            color: {WARNING_COLOR};
            margin: 1rem 0;
        }}
        
        .difficulty-selector .stRadio > div {{
            flex-direction: row;
            gap: 1rem;
        }}
        
        .difficulty-selector label {{
            background: {SURFACE_COLOR};
            padding: 0.75rem 1rem;
            border-radius: 0.5rem;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
            cursor: pointer;
        }}
        
        .difficulty-selector label:hover {{
            border-color: {PRIMARY_COLOR};
        }}
        
        .stRadio > div > label[data-baseweb="radio"] > div:first-child {{
            background-color: transparent !important;
            border: 2px solid rgba(255, 255, 255, 0.3) !important;
        }}
        
        .stRadio > div > label[aria-checked="true"] > div:first-child {{
            background-color: {PRIMARY_COLOR} !important;
            border-color: {PRIMARY_COLOR} !important;
        }}
        
        .leaderboard-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}
        
        .leaderboard-table th {{
            background-color: rgba(108, 99, 255, 0.1);
            color: {PRIMARY_COLOR};
            padding: 1rem;
            text-align: left;
        }}
        
        .leaderboard-table td {{
            padding: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }}
        
        .leaderboard-table tr:hover {{
            background-color: rgba(255, 255, 255, 0.05);
        }}
        
        .fade-in {{
            animation: fadeIn 0.5s ease-in;
        }}
        
        @keyframes fadeIn {{
            from {{ opacity: 0; }}
            to {{ opacity: 1; }}
        }}
        
        .pulse {{
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0% {{ box-shadow: 0 0 0 0 rgba(108, 99, 255, 0.7); }}
            70% {{ box-shadow: 0 0 0 10px rgba(108, 99, 255, 0); }}
            100% {{ box-shadow: 0 0 0 0 rgba(108, 99, 255, 0); }}
        }}
    </style>
    """, unsafe_allow_html=True)

# =======================
# PAGE COMPONENTS
# =======================

def show_login_page() -> None:
    """Display the login page."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 style='text-align: center; color: white;'>🔐 QuizMaster</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #B0B0B0;'>Test your knowledge and climb the leaderboard!</p>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            submitted = st.form_submit_button("Log In")
            
            if submitted:
                if not username or not password:
                    st.error("Please enter both username and password.")
                else:
                    user = UserRepository.authenticate_user(username, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user = user
                        st.session_state.current_page = 'dashboard'
                        st.rerun()
                    else:
                        st.error("Invalid username or password.")
        
        st.markdown("<p style='text-align: center;'>Don't have an account?</p>", unsafe_allow_html=True)
        if st.button("Create Account", key="show_signup"):
            st.session_state.current_page = 'signup'
            st.rerun()

def show_signup_page() -> None:
    """Display the signup page."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h1 style='text-align: center;'>📝 Create Account</h1>", unsafe_allow_html=True)
        
        with st.form("signup_form"):
            username = st.text_input("Choose a Username")
            password = st.text_input("Choose a Password", type="password")
            password_confirm = st.text_input("Confirm Password", type="password")
            submitted = st.form_submit_button("Create Account")
            
            if submitted:
                if not username or not password:
                    st.error("Please fill in all fields.")
                elif password != password_confirm:
                    st.error("Passwords do not match.")
                elif len(password) < 6:
                    st.error("Password must be at least 6 characters long.")
                else:
                    if UserRepository.create_user(username, password):
                        st.success("Account created successfully! Please log in.")
                        time.sleep(1)
                        st.session_state.current_page = 'login'
                        st.rerun()
        
        if st.button("Back to Login", key="back_to_login"):
            st.session_state.current_page = 'login'
            st.rerun()

def show_dashboard() -> None:
    """Display the main dashboard."""
    st.markdown("<h1>🎯 Dashboard</h1>", unsafe_allow_html=True)
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.markdown("""
        <div class="quiz-card fade-in">
            <h2>Start a New Quiz</h2>
            <p>Test your knowledge with our interactive quiz. Choose your difficulty level and see how you rank!</p>
        </div>
        """, unsafe_allow_html=True)
        
        difficulty = st.radio(
            "Select Difficulty",
            options=DIFFICULTY_LEVELS,
            format_func=str.capitalize,
            index=DIFFICULTY_LEVELS.index(DEFAULT_DIFFICULTY),
            key="difficulty_select",
            help="Choose your challenge level"
        )
        
        if st.button("Start Quiz 🚀", key="start_quiz"):
            st.session_state.quiz_started = True
            st.session_state.questions = QuestionRepository.get_questions_by_difficulty(difficulty, QUESTIONS_PER_QUIZ)
            st.session_state.current_question_index = 0
            st.session_state.answers = {}
            st.session_state.start_time = time.time()
            st.session_state.time_left = TIME_LIMIT_PER_QUESTION
            st.session_state.quiz_completed = False
            st.session_state.score = 0
            st.rerun()
    
    with col2:
        st.markdown("""
        <div class="quiz-card fade-in">
            <h3>📊 Your Stats</h3>
            <p>Track your progress and improve over time.</p>
        </div>
        """, unsafe_allow_html=True)
        
        try:
            with sqlite3.connect(DB_PATH) as conn:
                result = pd.read_sql_query("""
                    SELECT COUNT(*) as total_quizzes, AVG(score * 1.0 / total_questions) as avg_accuracy
                    FROM quiz_attempts 
                    WHERE user_id = ?
                """, conn, params=(st.session_state.user.id,))
                
                total_quizzes = int(result.iloc[0]['total_quizzes'])
                avg_accuracy = result.iloc[0]['avg_accuracy']
                
                st.metric("Total Quizzes", total_quizzes)
                if avg_accuracy is not None:
                    st.metric("Average Accuracy", f"{avg_accuracy:.1%}")
                else:
                    st.metric("Average Accuracy", "0%")
        except Exception as e:
            st.error("Could not load user stats.")
    
    # Leaderboard
    st.markdown("<h2>🏆 Leaderboard</h2>", unsafe_allow_html=True)
    leaderboard_df = QuizAttemptRepository.get_leaderboard(10)
    
    if leaderboard_df.empty:
        st.info("No quiz attempts yet. Be the first to take a quiz!")
    else:
        st.dataframe(
            leaderboard_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn(format="%d"),
                "Total": st.column_config.NumberColumn(format="%d"),
                "Accuracy (%)": st.column_config.NumberColumn(format="%.1f%%")
            }
        )

def show_quiz() -> None:
    """Display the quiz interface."""
    if not st.session_state.questions:
        st.error("No questions available. Please return to dashboard.")
        if st.button("Back to Dashboard"):
            st.session_state.current_page = 'dashboard'
            st.session_state.quiz_started = False
            st.rerun()
        return
    
    current_idx = st.session_state.current_question_index
    total_questions = len(st.session_state.questions)
    
    if current_idx >= total_questions:
        st.session_state.quiz_completed = True
        # Calculate score
        score = 0
        questions = st.session_state.questions
        for i, question in enumerate(questions):
            user_answer = st.session_state.answers.get(i)
            if user_answer == question.correct_answer:
                score += 1
        st.session_state.score = score
        st.rerun()
    
    question = st.session_state.questions[current_idx]
    
    # Timer logic
    if st.session_state.start_time:
        elapsed = time.time() - st.session_state.start_time
        st.session_state.time_left = max(0, TIME_LIMIT_PER_QUESTION - int(elapsed))
        
        if st.session_state.time_left <= 0 and not st.session_state.quiz_completed:
            # Auto-advance when time expires
            st.session_state.current_question_index += 1
            st.session_state.start_time = time.time()
            st.rerun()
    
    # Progress bar
    progress = (current_idx) / total_questions
    st.progress(progress, text=f"Question {current_idx + 1} of {total_questions}")
    
    # Timer display
    timer_color = WARNING_COLOR if st.session_state.time_left <= 5 else TEXT_COLOR
    st.markdown(f"""
        <div class="timer" style="color: {timer_color};">
            ⏳ Time left: {st.session_state.time_left} seconds
        </div>
    """, unsafe_allow_html=True)
    
    # Question card
    st.markdown(f"""
        <div class="quiz-card fade-in">
            <h3>{question.question_text}</h3>
        </div>
    """, unsafe_allow_html=True)
    
    # Answer options
    options = {
        'A': question.option_a,
        'B': question.option_b,
        'C': question.option_c,
        'D': question.option_d
    }
    
    selected_answer = st.radio(
        "Choose your answer:",
        options=list(options.keys()),
        format_func=lambda x: f"**{x})** {options[x]}",
        key=f"answer_{current_idx}",
        horizontal=False,
        label_visibility="collapsed"
    )
    
    st.session_state.answers[current_idx] = selected_answer
    
    # Navigation buttons
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col1:
        if st.button("⬅️ Previous", disabled=current_idx == 0):
            st.session_state.current_question_index -= 1
            st.session_state.start_time = time.time()
            st.rerun()
    
    with col3:
        if current_idx == total_questions - 1:
            if st.button("Finish Quiz ✅"):
                st.session_state.quiz_completed = True
                # Calculate score
                score = 0
                for i, q in enumerate(st.session_state.questions):
                    if st.session_state.answers.get(i) == q.correct_answer:
                        score += 1
                st.session_state.score = score
                st.rerun()
        else:
            if st.button("Next ➡️"):
                st.session_state.current_question_index += 1
                st.session_state.start_time = time.time()
                st.rerun()
    
    # Save progress
    st.session_state.start_time = time.time()

def show_quiz_results() -> None:
    """Display quiz results and performance summary."""
    st.markdown("<h1>🎉 Quiz Completed!</h1>", unsafe_allow_html=True)
    
    score = st.session_state.score
    total = len(st.session_state.questions)
    accuracy = score / total
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Your Score", f"{score}/{total}")
    with col2:
        st.metric("Accuracy", f"{accuracy:.1%}")
    with col3:
        if accuracy == 1.0:
            st.markdown("<p class='success-text'>Perfect! 🏆</p>", unsafe_allow_html=True)
        elif accuracy >= 0.7:
            st.markdown("<p class='success-text'>Great job! 👍</p>", unsafe_allow_html=True)
        elif accuracy >= 0.5:
            st.markdown("<p style='color: #FFD740;'>Good effort! 💪</p>", unsafe_allow_html=True)
        else:
            st.markdown("<p class='danger-text'>Keep practicing! 📚</p>", unsafe_allow_html=True)
    
    # Detailed results
    st.markdown("<h2>📝 Detailed Results</h2>", unsafe_allow_html=True)
    
    for i, question in enumerate(st.session_state.questions):
        user_answer = st.session_state.answers.get(i)
        is_correct = user_answer == question.correct_answer
        
        with st.expander(f"Question {i+1}: {question.question_text}"):
            options = {
                'A': question.option_a,
                'B': question.option_b,
                'C': question.option_c,
                'D': question.option_d
            }
            
            for key, value in options.items():
                if key == user_answer:
                    if is_correct:
                        st.markdown(f"<p style='color: {SUCCESS_COLOR};'>✅ {key}) {value} (Your answer)</p>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<p style='color: {DANGER_COLOR};'>❌ {key}) {value} (Your answer)</p>", unsafe_allow_html=True)
                elif key == question.correct_answer:
                    st.markdown(f"<p style='color: {SUCCESS_COLOR};'>✅ {key}) {value} (Correct answer)</p>", unsafe_allow_html=True)
                else:
                    st.markdown(f"<p style='color: #B0B0B0;'>{key}) {value}</p>", unsafe_allow_html=True)
    
    # Save attempt and show leaderboard
    if st.session_state.user and not st.session_state.get('attempt_saved', False):
        difficulty = st.session_state.questions[0].difficulty if st.session_state.questions else DEFAULT_DIFFICULTY
        QuizAttemptRepository.save_attempt(st.session_state.user.id, score, total, difficulty)
        st.session_state.attempt_saved = True
    
    st.markdown("<h2>🏆 Updated Leaderboard</h2>", unsafe_allow_html=True)
    leaderboard_df = QuizAttemptRepository.get_leaderboard(10)
    if not leaderboard_df.empty:
        st.dataframe(
            leaderboard_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn(format="%d"),
                "Total": st.column_config.NumberColumn(format="%d"),
                "Accuracy (%)": st.column_config.NumberColumn(format="%.1f%%")
            }
        )
    
    # Action buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Take Another Quiz 🔄"):
            st.session_state.quiz_started = False
            st.session_state.current_page = 'dashboard'
            st.session_state.attempt_saved = False
            st.rerun()
    with col2:
        if st.button("Back to Dashboard 🏠"):
            st.session_state.quiz_started = False
            st.session_state.current_page = 'dashboard'
            st.session_state.attempt_saved = False
            st.rerun()

def main() -> None:
    """Main application entry point."""
    # Initialize database
    try:
        init_db()
    except Exception as e:
        st.error(f"Failed to initialize database: {str(e)}")
        st.stop()
    
    # Initialize session state
    init_session_state()
    
    # Apply custom CSS
    apply_custom_css()
    
    # Page routing
    if not st.session_state.logged_in:
        if st.session_state.current_page == 'signup':
            show_signup_page()
        else:
            show_login_page()
    else:
        # Sidebar navigation
        with st.sidebar:
            st.markdown(f"<h3 style='color: white;'>Hello, {st.session_state.user.username}!</h3>", unsafe_allow_html=True)
            if st.button("Dashboard"):
                st.session_state.current_page = 'dashboard'
                st.session_state.quiz_started = False
                st.rerun()
            if st.button("Leaderboard"):
                st.session_state.current_page = 'leaderboard'
                st.rerun()
            if st.button("Log Out"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
            st.markdown("<hr>", unsafe_allow_html=True)
            st.markdown("<p style='color: #606060; font-size: 0.8rem;'>QuizMaster v1.0</p>", unsafe_allow_html=True)
        
        # Main content routing
        if st.session_state.quiz_started and not st.session_state.quiz_completed:
            show_quiz()
        elif st.session_state.quiz_completed:
            show_quiz_results()
        elif st.session_state.current_page == 'dashboard':
            show_dashboard()
        else:
            # Leaderboard page
            st.markdown("<h1>🏆 Leaderboard</h1>", unsafe_allow_html=True)
            leaderboard_df = QuizAttemptRepository.get_leaderboard(20)
            if leaderboard_df.empty:
                st.info("No quiz attempts yet. Be the first to take a quiz!")
            else:
                st.dataframe(
                    leaderboard_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Score": st.column_config.NumberColumn(format="%d"),
                        "Total": st.column_config.NumberColumn(format="%d"),
                        "Accuracy (%)": st.column_config.NumberColumn(format="%.1f%%")
                    }
                )
                if st.button("Back to Dashboard"):
                    st.session_state.current_page = 'dashboard'
                    st.rerun()

if __name__ == "__main__":
    main()