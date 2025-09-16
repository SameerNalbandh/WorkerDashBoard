"""
EcoGuard Dashboard - Environmental Monitoring & Safety Dashboard
==============================================================

File: dashboard_qt (2).py
Location: c:\Users\acer\Downloads\dashboard_qt (2).py

Description:
    A modern, beautiful dashboard for environmental monitoring and safety management.
    Features two main modules: Mining Safety Dashboard and Pollution Control Agent.

Features:
    - Modern dark theme with professional UI
    - Card-based layout with hover effects
    - Exit confirmation dialog
    - Success notifications
    - Fullscreen mode with ESC to exit
    - Responsive design

Usage:
    Run this file directly with Python to launch the dashboard.
    Press ESC to exit fullscreen mode.
    Click the red X button to exit the application.

Dependencies:
    - tkinter (built-in with Python)
    - time (built-in with Python)

Author: AI Assistant
Date: 2024
"""

import tkinter as tk
from tkinter import ttk
import time
import os
import subprocess

# =============================================================================
# FILE PATH CONFIGURATION - PASTE YOUR PYTHON FILE PATHS HERE
# =============================================================================

# Mining Safety Dashboard Python file path
MINING_SAFETY_SCRIPT = r"/home/sam/SIH/WorkerDashBoardWithFireBase.py"

# Pollution Control Agent Python file path  
POLLUTION_CONTROL_SCRIPT = r"/home/sam/SIH/PUCDashboard.py"

# =============================================================================

class EcoGuardDashboard:
    def __init__(self):
        self.root = tk.Tk()
        self.setup_window()
        self.create_styles()
        self.create_widgets()
        
    def setup_window(self):
        self.root.title("EcoGuard - Environmental Monitoring Dashboard")
        self.root.configure(bg="#0a0e27")

# Make fullscreen
        self.root.attributes("-fullscreen", True)

# Escape key exits fullscreen
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))
        
        # Handle window close event
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Center the window
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        
    def create_styles(self):
        # Define color scheme
        self.colors = {
            'primary': '#0a0e27',
            'secondary': '#1a1f3a',
            'accent': '#00d4ff',
            'success': '#00ff88',
            'warning': '#ff6b35',
            'danger': '#ff4757',
            'text_primary': '#ffffff',
            'text_secondary': '#b0b3b8',
            'card_bg': '#1e2139',
            'hover_bg': '#2a2f4a'
        }
        
    def create_gradient_frame(self, parent, color1, color2, width, height):
        """Create a frame with gradient background effect"""
        frame = tk.Frame(parent, bg=color1, width=width, height=height)
        return frame
        
    def create_widgets(self):
        # Main container with padding
        main_container = tk.Frame(self.root, bg=self.colors['primary'])
        main_container.pack(fill=tk.BOTH, expand=True, padx=40, pady=30)
        
        # Header section
        self.create_header(main_container)
        
        # Content section
        self.create_content(main_container)
        
        # Footer section
        self.create_footer(main_container)
        
    def create_header(self, parent):
        header_frame = tk.Frame(parent, bg=self.colors['primary'])
        header_frame.pack(fill=tk.X, pady=(0, 40))
        
        # Top bar with title and exit button
        top_bar = tk.Frame(header_frame, bg=self.colors['primary'])
        top_bar.pack(fill=tk.X)
        
        # Logo/Title section
        title_frame = tk.Frame(top_bar, bg=self.colors['primary'])
        title_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Main title with icon
        title_label = tk.Label(
            title_frame,
            text="🌍 EcoGuard",
            font=("Segoe UI", 56, "bold"),
            fg=self.colors['accent'],
            bg=self.colors['primary']
        )
        title_label.pack(anchor=tk.W)
        
        # Subtitle
        subtitle_label = tk.Label(
            title_frame,
            text="Environmental Monitoring & Safety Dashboard",
            font=("Segoe UI", 18),
            fg=self.colors['text_secondary'],
            bg=self.colors['primary']
        )
        subtitle_label.pack(anchor=tk.W, pady=(5, 0))
        
        # Exit button
        exit_button = tk.Button(
            top_bar,
            text="✕",
            font=("Segoe UI", 24, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['danger'],
            activebackground="#ff2d2d",
            activeforeground=self.colors['text_primary'],
            relief=tk.FLAT,
            bd=0,
            width=3,
            height=1,
            cursor="hand2",
            command=self.on_closing
        )
        exit_button.pack(side=tk.RIGHT, padx=(20, 0))
        
        # Add hover effects for exit button
        def on_enter(e):
            exit_button.configure(bg="#ff2d2d")
            
        def on_leave(e):
            exit_button.configure(bg=self.colors['danger'])
            
        exit_button.bind("<Enter>", on_enter)
        exit_button.bind("<Leave>", on_leave)
        
        # Status bar
        status_frame = tk.Frame(header_frame, bg=self.colors['secondary'], relief=tk.RAISED, bd=1)
        status_frame.pack(fill=tk.X, pady=(20, 0))
        
        status_label = tk.Label(
            status_frame,
            text="🟢 System Online • Last Updated: " + time.strftime("%H:%M:%S"),
            font=("Segoe UI", 12),
            fg=self.colors['success'],
            bg=self.colors['secondary'],
            pady=10
        )
        status_label.pack()
        
    def create_content(self, parent):
        content_frame = tk.Frame(parent, bg=self.colors['primary'])
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Create cards container
        cards_frame = tk.Frame(content_frame, bg=self.colors['primary'])
        cards_frame.pack(expand=True)
        
        # Mining Safety Card
        self.create_mining_card(cards_frame)
        
        # Pollution Control Card
        self.create_pollution_card(cards_frame)
        
    def create_mining_card(self, parent):
        # Card container
        card_frame = tk.Frame(
            parent,
            bg=self.colors['card_bg'],
            relief=tk.RAISED,
            bd=2
        )
        card_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 20))
        
        # Card header
        header_frame = tk.Frame(card_frame, bg=self.colors['danger'], height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        header_label = tk.Label(
            header_frame,
            text="⛏️ Mining Safety",
            font=("Segoe UI", 24, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['danger']
        )
        header_label.pack(expand=True)
        
        # Card content
        content_frame = tk.Frame(card_frame, bg=self.colors['card_bg'])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        # Description
        desc_label = tk.Label(
            content_frame,
            text="Monitor mining operations for safety compliance and environmental impact",
            font=("Segoe UI", 14),
            fg=self.colors['text_secondary'],
            bg=self.colors['card_bg'],
            wraplength=300,
            justify=tk.CENTER
        )
        desc_label.pack(pady=(0, 30))
        
        # Features list
        features = [
            "🔍 Real-time monitoring",
            "⚠️ Safety alerts",
            "📊 Compliance reports",
            "🌱 Environmental impact"
        ]
        
        for feature in features:
            feature_label = tk.Label(
                content_frame,
                text=feature,
                font=("Segoe UI", 12),
                fg=self.colors['text_primary'],
                bg=self.colors['card_bg'],
                anchor=tk.W
            )
            feature_label.pack(fill=tk.X, pady=2)
        
        # Action button
        self.create_action_button(
            content_frame,
            "Access Dashboard",
            self.mining_action,
            self.colors['danger'],
            self.colors['hover_bg']
        )
        
    def create_pollution_card(self, parent):
        # Card container
        card_frame = tk.Frame(
            parent,
            bg=self.colors['card_bg'],
            relief=tk.RAISED,
            bd=2
        )
        card_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 0))
        
        # Card header
        header_frame = tk.Frame(card_frame, bg=self.colors['success'], height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        header_label = tk.Label(
            header_frame,
            text="🌿 Pollution Control",
            font=("Segoe UI", 24, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['success']
        )
        header_label.pack(expand=True)
        
        # Card content
        content_frame = tk.Frame(card_frame, bg=self.colors['card_bg'])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        # Description
        desc_label = tk.Label(
            content_frame,
            text="Track and control pollution levels with intelligent monitoring systems",
            font=("Segoe UI", 14),
            fg=self.colors['text_secondary'],
            bg=self.colors['card_bg'],
            wraplength=300,
            justify=tk.CENTER
        )
        desc_label.pack(pady=(0, 30))
        
        # Features list
        features = [
            "🌡️ Air quality monitoring",
            "💧 Water quality tracking",
            "📈 Trend analysis",
            "🤖 AI-powered alerts"
        ]
        
        for feature in features:
            feature_label = tk.Label(
                content_frame,
                text=feature,
                font=("Segoe UI", 12),
                fg=self.colors['text_primary'],
                bg=self.colors['card_bg'],
                anchor=tk.W
            )
            feature_label.pack(fill=tk.X, pady=2)
        
        # Action button
        self.create_action_button(
            content_frame,
            "Launch Agent",
            self.pollution_action,
            self.colors['success'],
            self.colors['hover_bg']
        )
        
    def create_action_button(self, parent, text, command, bg_color, hover_color):
        button_frame = tk.Frame(parent, bg=self.colors['card_bg'])
        button_frame.pack(fill=tk.X, pady=(30, 0))
        
        button = tk.Button(
            button_frame,
            text=text,
            font=("Segoe UI", 16, "bold"),
            bg=bg_color,
            fg=self.colors['text_primary'],
            activebackground=hover_color,
            activeforeground=self.colors['text_primary'],
            relief=tk.FLAT,
            bd=0,
            pady=15,
            cursor="hand2",
            command=command
        )
        button.pack(fill=tk.X)
        
        # Add hover effects
        def on_enter(e):
            button.configure(bg=hover_color)
            
        def on_leave(e):
            button.configure(bg=bg_color)
            
        button.bind("<Enter>", on_enter)
        button.bind("<Leave>", on_leave)
        
    def create_footer(self, parent):
        footer_frame = tk.Frame(parent, bg=self.colors['primary'])
        footer_frame.pack(fill=tk.X, pady=(40, 0))
        
        footer_label = tk.Label(
            footer_frame,
            text="© 2024 EcoGuard • Protecting Our Environment Through Technology",
            font=("Segoe UI", 10),
            fg=self.colors['text_secondary'],
            bg=self.colors['primary']
        )
        footer_label.pack()
        
    def mining_action(self):
        """Execute the Mining Safety Dashboard Python script"""
        try:
            if os.path.exists(MINING_SAFETY_SCRIPT):
                print(f"🚀 Launching Mining Safety Dashboard: {MINING_SAFETY_SCRIPT}")
                subprocess.Popen(['python', MINING_SAFETY_SCRIPT])
                self.show_notification("Mining Safety Dashboard", "Dashboard launched successfully!")
            else:
                print(f"❌ Mining Safety script not found at: {MINING_SAFETY_SCRIPT}")
                self.show_error_notification("File Not Found", f"Mining Safety script not found at:\n{MINING_SAFETY_SCRIPT}")
        except Exception as e:
            print(f"❌ Error launching Mining Safety Dashboard: {e}")
            self.show_error_notification("Launch Error", f"Failed to launch Mining Safety Dashboard:\n{str(e)}")
        
    def pollution_action(self):
        """Execute the Pollution Control Agent Python script"""
        try:
            if os.path.exists(POLLUTION_CONTROL_SCRIPT):
                print(f"🌱 Launching Pollution Control Agent: {POLLUTION_CONTROL_SCRIPT}")
                subprocess.Popen(['python', POLLUTION_CONTROL_SCRIPT])
                self.show_notification("Pollution Control Agent", "Agent activated successfully!")
            else:
                print(f"❌ Pollution Control script not found at: {POLLUTION_CONTROL_SCRIPT}")
                self.show_error_notification("File Not Found", f"Pollution Control script not found at:\n{POLLUTION_CONTROL_SCRIPT}")
        except Exception as e:
            print(f"❌ Error launching Pollution Control Agent: {e}")
            self.show_error_notification("Launch Error", f"Failed to launch Pollution Control Agent:\n{str(e)}")
        
    def on_closing(self):
        """Handle application exit with confirmation"""
        # Create confirmation dialog
        confirm_window = tk.Toplevel(self.root)
        confirm_window.title("Exit EcoGuard")
        confirm_window.configure(bg=self.colors['primary'])
        confirm_window.geometry("400x200")
        confirm_window.attributes("-topmost", True)
        confirm_window.resizable(False, False)
        
        # Center the confirmation window
        confirm_window.update_idletasks()
        x = (confirm_window.winfo_screenwidth() // 2) - (400 // 2)
        y = (confirm_window.winfo_screenheight() // 2) - (200 // 2)
        confirm_window.geometry(f"400x200+{x}+{y}")
        
        # Make it modal
        confirm_window.transient(self.root)
        confirm_window.grab_set()
        
        # Content frame
        content_frame = tk.Frame(confirm_window, bg=self.colors['primary'])
        content_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=30)
        
        # Warning icon and message
        warning_label = tk.Label(
            content_frame,
            text="⚠️",
            font=("Segoe UI", 48),
            fg=self.colors['warning'],
            bg=self.colors['primary']
        )
        warning_label.pack(pady=(0, 10))
        
        message_label = tk.Label(
            content_frame,
            text="Are you sure you want to exit EcoGuard?",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['primary'],
            wraplength=300
        )
        message_label.pack(pady=(0, 20))
        
        # Buttons frame
        buttons_frame = tk.Frame(content_frame, bg=self.colors['primary'])
        buttons_frame.pack()
        
        # Cancel button
        cancel_btn = tk.Button(
            buttons_frame,
            text="Cancel",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors['secondary'],
            fg=self.colors['text_primary'],
            activebackground=self.colors['hover_bg'],
            activeforeground=self.colors['text_primary'],
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=confirm_window.destroy
        )
        cancel_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # Exit button
        exit_btn = tk.Button(
            buttons_frame,
            text="Exit",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors['danger'],
            fg=self.colors['text_primary'],
            activebackground="#ff2d2d",
            activeforeground=self.colors['text_primary'],
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=8,
            cursor="hand2",
            command=self.force_exit
        )
        exit_btn.pack(side=tk.LEFT, padx=(10, 0))
        
    def force_exit(self):
        """Force exit the application"""
        print("🚪 EcoGuard Dashboard closed by user")
        self.root.quit()
        self.root.destroy()
        
    def show_notification(self, title, message):
        # Create a temporary notification
        notification = tk.Toplevel(self.root)
        notification.title(title)
        notification.configure(bg=self.colors['success'])
        notification.geometry("400x100")
        notification.attributes("-topmost", True)
        
        # Center the notification
        notification.update_idletasks()
        x = (notification.winfo_screenwidth() // 2) - (400 // 2)
        y = (notification.winfo_screenheight() // 2) - (100 // 2)
        notification.geometry(f"400x100+{x}+{y}")
        
        label = tk.Label(
            notification,
            text=f"✅ {message}",
            font=("Segoe UI", 14, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['success']
        )
        label.pack(expand=True)
        
        # Auto-close after 3 seconds
        notification.after(3000, notification.destroy)
        
    def show_error_notification(self, title, message):
        # Create an error notification
        notification = tk.Toplevel(self.root)
        notification.title(title)
        notification.configure(bg=self.colors['danger'])
        notification.geometry("500x150")
        notification.attributes("-topmost", True)
        
        # Center the notification
        notification.update_idletasks()
        x = (notification.winfo_screenwidth() // 2) - (500 // 2)
        y = (notification.winfo_screenheight() // 2) - (150 // 2)
        notification.geometry(f"500x150+{x}+{y}")
        
        label = tk.Label(
            notification,
            text=f"❌ {message}",
            font=("Segoe UI", 12, "bold"),
            fg=self.colors['text_primary'],
            bg=self.colors['danger'],
            wraplength=450,
            justify=tk.LEFT
        )
        label.pack(expand=True, padx=20, pady=20)
        
        # Auto-close after 5 seconds
        notification.after(5000, notification.destroy)
        
    def run(self):
        self.root.mainloop()

def main():
    """Main function to run the EcoGuard Dashboard"""
    try:
        # Get the current file path for logging
        current_file = os.path.abspath(__file__)
        print(f"🚀 Starting EcoGuard Dashboard from: {current_file}")
        
        # Create and run the dashboard
        dashboard = EcoGuardDashboard()
        dashboard.run()
        
    except Exception as e:
        print(f"❌ Error starting EcoGuard Dashboard: {e}")
        input("Press Enter to exit...")

if __name__ == "__main__":
    main()
