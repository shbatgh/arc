#!/usr/bin/env python3
"""
Safe Cell Clustering Analysis GUI

A thread-safe GUI that avoids macOS threading issues by running analysis
on the main thread with periodic UI updates.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import sys
import json
from pathlib import Path
import time

# Basic imports that should always be available
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("Warning: pandas not available")

try:
    import matplotlib
    matplotlib.use('Agg')  # Set non-interactive backend immediately
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("Warning: matplotlib not available")

# Try to import clustering module
try:
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from cell_clustering import CellClusteringAnalyzer
    CLUSTERING_AVAILABLE = True
except ImportError as e:
    CLUSTERING_AVAILABLE = False
    CellClusteringAnalyzer = None
    print(f"Warning: clustering module not available: {e}")

# Try to import feature database
try:
    from feature_database import FeatureDatabase
    FEATURE_DB_AVAILABLE = True
except ImportError as e:
    FEATURE_DB_AVAILABLE = False
    print(f"Warning: feature database not available: {e}")


class SafeCellClusteringGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cell Clustering Analysis Tool (Safe Mode)")
        self.root.geometry("1000x700")
        
        # Initialize variables
        self.analyzer = None
        self.current_file = None
        self.analysis_running = False
        self.optimal_k = None
        self.results_dir = None  # Directory for saving results
        
        # Default settings
        self.settings = {
            'n_clusters': 5,
            'correlation_threshold': 0.85,
            'remove_correlated': True,
            'figure_width': 10,
            'figure_height': 8,
            'dpi': 300
        }
        
        self.create_gui()
        self.check_dependencies()
    
    def check_dependencies(self):
        """Check and report on available dependencies."""
        missing = []
        if not PANDAS_AVAILABLE:
            missing.append("pandas")
        if not MATPLOTLIB_AVAILABLE:
            missing.append("matplotlib")
        if not CLUSTERING_AVAILABLE:
            missing.append("clustering module")
        
        if missing:
            msg = f"Missing dependencies: {', '.join(missing)}\n"
            msg += "Some features may not be available.\n"
            msg += "Run 'pip install pandas matplotlib seaborn scikit-learn umap-learn' to install missing packages."
            self.log_message(msg)
    
    def create_gui(self):
        """Create the main GUI."""
        # Create notebook for tabs
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Data tab
        self.create_data_tab(notebook)
        
        # Features tab (simplified)
        self.create_features_tab(notebook)
        
        # Analysis tab (includes settings)
        self.create_analysis_tab(notebook)
        
        # Results tab
        self.create_results_tab(notebook)
    
    def create_data_tab(self, notebook):
        """Create data loading tab."""
        data_frame = ttk.Frame(notebook)
        notebook.add(data_frame, text="Data")
        
        # File selection
        file_frame = ttk.LabelFrame(data_frame, text="Data File", padding=10)
        file_frame.pack(fill=tk.X, padx=10, pady=5)
        
        ttk.Label(file_frame, text="Select CSV file with cell outline data:").pack(anchor=tk.W)
        
        file_select_frame = ttk.Frame(file_frame)
        file_select_frame.pack(fill=tk.X, pady=5)
        
        self.file_path_var = tk.StringVar()
        ttk.Entry(file_select_frame, textvariable=self.file_path_var, width=60).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(file_select_frame, text="Browse", command=self.browse_file).pack(side=tk.RIGHT, padx=(5, 0))
        
        ttk.Button(file_frame, text="Load Data", command=self.load_data).pack(pady=5)
        
        # Data info
        info_frame = ttk.LabelFrame(data_frame, text="Data Information", padding=10)
        info_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.data_info_var = tk.StringVar(value="No data loaded")
        ttk.Label(info_frame, textvariable=self.data_info_var, wraplength=800).pack(anchor=tk.W)
        
        # Requirements info
        req_frame = ttk.LabelFrame(data_frame, text="Data Requirements", padding=10)
        req_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        requirements_text = """Your CSV file should contain these columns:

For pre-computed features (quant_data.csv format):
• Cell ID: Unique identifier for each cell
• outlines: Cell boundary coordinates as string
• mean_volume: Mean volume of the cell
• mean_surface_area: Mean surface area of the cell  
• total_distance_traveled: Total distance the cell has traveled

Example quant_data.csv format:
Cell ID,outlines,mean_volume,mean_surface_area,total_distance_traveled
1,"[[10,20,5], [15,25,6], [12,30,5], [8,25,4]]",150.5,85.2,120.8
2,"[[50,60,8], [55,65,9], [52,70,8], [48,65,7]]",180.3,92.7,95.4

For raw outline data (legacy format):
• Cell ID: Unique identifier for each cell
• Timepoint: Time of observation (numeric)
• Outline Points: Cell boundary coordinates as string (2D data)
• Outline Points 3D: Cell boundary coordinates as string (3D data)

Example legacy format (2D):
Cell ID,Timepoint,Outline Points
1,0,"[[10,20], [15,25], [12,30], [8,25]]"

Example legacy format (3D):
Cell ID,Timepoint,Outline Points 3D
1,0,"[[10,20,5], [15,25,5], [12,30,5], [8,25,5]]"
        """
        
        text_widget = tk.Text(req_frame, height=10, wrap=tk.WORD)
        text_widget.insert(1.0, requirements_text)
        text_widget.config(state=tk.DISABLED)
        text_widget.pack(fill=tk.BOTH, expand=True)
    
    def create_features_tab(self, notebook):
        """Create comprehensive individual feature selection tab."""
        features_frame = ttk.Frame(notebook)
        notebook.add(features_frame, text="Features")
        
        if not FEATURE_DB_AVAILABLE:
            ttk.Label(features_frame, text="Feature database not available. Using default features.", 
                     foreground="orange").pack(pady=20)
            return
        
        # Initialize feature database and variables
        self.feature_db = FeatureDatabase()
        self.feature_vars = {}
        
        # Control panel at top
        control_frame = ttk.Frame(features_frame)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Quick selection buttons
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(side=tk.LEFT)
        
        ttk.Button(button_frame, text="Select All", command=self.select_all_individual_features).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Deselect All", command=self.deselect_all_individual_features).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="All Essential", command=self.select_shape_individual_features).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Reset Defaults", command=self.reset_individual_features).pack(side=tk.LEFT, padx=2)
        
        # Feature count display
        self.feature_count_var = tk.StringVar()
        ttk.Label(control_frame, textvariable=self.feature_count_var, font=('TkDefaultFont', 10, 'bold')).pack(side=tk.RIGHT, padx=10)
        
        # Scrollable frame for individual feature checkboxes - full width
        main_container = ttk.Frame(features_frame)
        main_container.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        
        # Create canvas and scrollbar with proper layout
        canvas = tk.Canvas(main_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        # Configure scrollable region
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def configure_canvas_width(event):
            # Make the scrollable frame match the canvas width
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        scrollable_frame.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_canvas_width)
        
        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Create individual feature checkboxes organized by category
        for category_name, features in self.feature_db.feature_categories.items():
            # Category frame
            cat_frame = ttk.LabelFrame(scrollable_frame, text=category_name, padding=10)
            cat_frame.pack(fill=tk.X, padx=5, pady=5)
            
            # Category header with select all/none for this category
            cat_header = ttk.Frame(cat_frame)
            cat_header.pack(fill=tk.X, pady=(0, 10))
            
            # Category descriptions
            category_descriptions = {
                "Essential Features": "Core cell measurements: surface area, centroid coordinates, radius, volume, speed, total distance"
            }
                
            desc_text = category_descriptions.get(category_name, "Advanced cell measurements")
            ttk.Label(cat_header, text=desc_text, foreground="gray", font=('TkDefaultFont', 9)).pack(side=tk.LEFT)
            
            # Category controls
            cat_controls = ttk.Frame(cat_header)
            cat_controls.pack(side=tk.RIGHT)
            
            ttk.Button(cat_controls, text="All", 
                      command=lambda cat=category_name: self.select_category_features(cat)).pack(side=tk.LEFT, padx=2)
            ttk.Button(cat_controls, text="None", 
                        command=lambda cat=category_name: self.deselect_category_features(cat)).pack(side=tk.LEFT, padx=2)
                
            # Individual feature checkboxes
            for feature_id, feature_info in features.items():
                feature_frame = ttk.Frame(cat_frame)
                feature_frame.pack(fill=tk.X, pady=2, padx=10)
                
                # Create checkbox variable
                var = tk.BooleanVar(value=feature_info.get("enabled", False))
                self.feature_vars[feature_id] = var
                var.trace('w', self.update_individual_feature_count)
                
                # Feature checkbox
                checkbox = ttk.Checkbutton(feature_frame, text=feature_info["name"], variable=var)
                checkbox.pack(side=tk.LEFT)
                
                # Feature description
                desc_label = ttk.Label(feature_frame, text=f"- {feature_info['description']}", 
                                     foreground="gray", wraplength=600, font=('TkDefaultFont', 9))
                desc_label.pack(side=tk.LEFT, padx=(10, 0))        # Pack canvas and scrollbar to fill the entire width
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # Initialize feature count
        self.update_individual_feature_count()
        
        # Enhanced scrolling functionality
        def _on_mousewheel(event):
            # Handle different platforms
            if hasattr(event, 'delta') and event.delta:
                # Windows and macOS
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif hasattr(event, 'num'):
                # Linux
                if event.num == 4:
                    canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    canvas.yview_scroll(1, "units")
        
        # Bind mouse wheel scrolling directly to canvas
        canvas.bind("<MouseWheel>", _on_mousewheel)  # Windows/macOS
        canvas.bind("<Button-4>", _on_mousewheel)    # Linux scroll up
        canvas.bind("<Button-5>", _on_mousewheel)    # Linux scroll down
        
        # Also bind to the scrollable frame for better coverage
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<Button-4>", _on_mousewheel)
        scrollable_frame.bind("<Button-5>", _on_mousewheel)
        
        # Keyboard navigation
        def _on_key(event):
            if event.keysym == 'Up':
                canvas.yview_scroll(-1, "units")
                return "break"
            elif event.keysym == 'Down':
                canvas.yview_scroll(1, "units")
                return "break"
            elif event.keysym == 'Page_Up':
                canvas.yview_scroll(-10, "units")
                return "break"
            elif event.keysym == 'Page_Down':
                canvas.yview_scroll(10, "units")
                return "break"
            elif event.keysym == 'Home':
                canvas.yview_moveto(0)
                return "break"
            elif event.keysym == 'End':
                canvas.yview_moveto(1)
                return "break"
        
        # Make canvas focusable for keyboard events
        canvas.focus_set()
        canvas.bind('<Key>', _on_key)
        
        # Propagate focus to canvas when clicking on scrollable content
        def _focus_canvas(event):
            canvas.focus_set()
        
        scrollable_frame.bind('<Button-1>', _focus_canvas)
    
    def select_all_individual_features(self):
        """Select all individual features."""
        if not hasattr(self, 'feature_vars'):
            return
        for var in self.feature_vars.values():
            var.set(True)
    
    def deselect_all_individual_features(self):
        """Deselect all individual features."""
        if not hasattr(self, 'feature_vars'):
            return
        for var in self.feature_vars.values():
            var.set(False)
    
    def select_shape_individual_features(self):
        """Select essential + motion features individually."""
        if not hasattr(self, 'feature_db') or not hasattr(self, 'feature_vars'):
            return
        
        # First deselect all
        for var in self.feature_vars.values():
            var.set(False)
        
        # Then select essential features including motion
        essential_features = ['surface_area', 'centroid_x', 'centroid_y', 'centroid_z', 'radius', 'volume', 'instantaneous_speed', 'total_distance']
        for feature_id in essential_features:
            if feature_id in self.feature_vars:
                self.feature_vars[feature_id].set(True)
    
    def reset_individual_features(self):
        """Reset individual features to their default enabled state."""
        if not hasattr(self, 'feature_db') or not hasattr(self, 'feature_vars'):
            return
        
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                if feature_id in self.feature_vars:
                    default_enabled = feature_info.get("enabled", False)
                    self.feature_vars[feature_id].set(default_enabled)
    
    def select_category_features(self, category_name):
        """Select all features in a specific category."""
        if not hasattr(self, 'feature_db') or not hasattr(self, 'feature_vars'):
            return
        
        category_features = self.feature_db.feature_categories.get(category_name, {})
        for feature_id in category_features.keys():
            if feature_id in self.feature_vars:
                self.feature_vars[feature_id].set(True)
    
    def deselect_category_features(self, category_name):
        """Deselect all features in a specific category."""
        if not hasattr(self, 'feature_db') or not hasattr(self, 'feature_vars'):
            return
        
        category_features = self.feature_db.feature_categories.get(category_name, {})
        for feature_id in category_features.keys():
            if feature_id in self.feature_vars:
                self.feature_vars[feature_id].set(False)
    
    def update_individual_feature_count(self, *args):
        """Update the individual feature count display."""
        if not hasattr(self, 'feature_vars'):
            return
        
        enabled_count = sum(1 for var in self.feature_vars.values() if var.get())
        total_count = len(self.feature_vars)
        self.feature_count_var.set(f"Selected: {enabled_count}/{total_count} features")
    
    def get_selected_individual_features(self):
        """Get list of individually selected feature IDs."""
        if not hasattr(self, 'feature_vars'):
            return []
        
        return [feature_id for feature_id, var in self.feature_vars.items() if var.get()]
    
    def apply_individual_feature_selection(self):
        """Apply individual feature selection to the feature database."""
        if not hasattr(self, 'feature_db') or not hasattr(self, 'feature_vars'):
            return
        
        # Update feature database based on individual selections
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                if feature_id in self.feature_vars:
                    feature_info["enabled"] = self.feature_vars[feature_id].get()
    
    def select_basic_features(self):
        """Select only basic geometric features."""
        if not FEATURE_DB_AVAILABLE:
            return
        
        # Enable only basic features
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                if category_name == "Basic Geometric":
                    feature_info["enabled"] = True
                else:
                    feature_info["enabled"] = False
        
        self.update_feature_display()
    
    def select_shape_features(self):
        """Select basic + shape descriptor features."""
        if not FEATURE_DB_AVAILABLE:
            return
        
        # Enable basic and shape features
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                if category_name in ["Basic Geometric", "Shape Descriptors", "Radius Features"]:
                    feature_info["enabled"] = True
                else:
                    feature_info["enabled"] = False
        
        self.update_feature_display()
    
    def select_advanced_features(self):
        """Select all except the most computationally expensive features."""
        if not FEATURE_DB_AVAILABLE:
            return
        
        # Enable most features except Fourier and Moments
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                if category_name not in ["Fourier Descriptors", "Moment Features"]:
                    feature_info["enabled"] = True
                else:
                    feature_info["enabled"] = False
        
        self.update_feature_display()
    
    def select_all_features(self):
        """Select all available features."""
        if not FEATURE_DB_AVAILABLE:
            return
        
        # Enable all features
        for category_name, features in self.feature_db.feature_categories.items():
            for feature_id, feature_info in features.items():
                feature_info["enabled"] = True
        
        self.update_feature_display()
    
    def update_feature_display(self):
        """Update the feature display text."""
        if not FEATURE_DB_AVAILABLE:
            return
        
        # Count enabled features
        enabled_count = 0
        total_count = 0
        feature_text = ""
        
        for category_name, features in self.feature_db.feature_categories.items():
            category_enabled = []
            for feature_id, feature_info in features.items():
                total_count += 1
                if feature_info["enabled"]:
                    enabled_count += 1
                    category_enabled.append(f"  • {feature_info['name']}: {feature_info['description']}")
            
            if category_enabled:
                feature_text += f"{category_name}:\n"
                feature_text += "\n".join(category_enabled)
                feature_text += "\n\n"
        
        # Update display
        self.feature_count_var.set(f"Selected: {enabled_count}/{total_count} features")
        
        self.features_text.config(state=tk.NORMAL)
        self.features_text.delete(1.0, tk.END)
        self.features_text.insert(1.0, feature_text)
        self.features_text.config(state=tk.DISABLED)
    
    def _on_method_change(self, event=None):
        """Handle clustering method change."""
        method = self.clustering_method_combo.get()
        if method == 'HDBSCAN':
            self.n_clusters_label.config(state="disabled")
            self.n_clusters_spinbox.config(state="disabled")
            # Don't disable the find optimal checkbox for HDBSCAN since it doesn't apply
        else:
            self.n_clusters_label.config(state="normal")
            self.n_clusters_spinbox.config(state="normal")

    def create_analysis_tab(self, notebook):
        """Create combined analysis and settings tab."""
        analysis_frame = ttk.Frame(notebook)
        notebook.add(analysis_frame, text="Analysis & Settings")
        
        # Create a scrollable frame for all content
        canvas = tk.Canvas(analysis_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(analysis_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        # Configure scrolling
        def configure_scroll_region(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        def configure_canvas_width(event):
            # Make the scrollable frame match the canvas width
            canvas_width = event.width
            canvas.itemconfig(canvas_window, width=canvas_width)
        
        scrollable_frame.bind("<Configure>", configure_scroll_region)
        canvas.bind("<Configure>", configure_canvas_width)
        
        # Create window in canvas
        canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack canvas and scrollbar to fill the entire width
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Clustering settings
        settings_frame = ttk.LabelFrame(scrollable_frame, text="Clustering Settings", padding=10)
        settings_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Configure grid weights for proper expansion
        settings_frame.grid_columnconfigure(1, weight=1)

        # Clustering method
        ttk.Label(settings_frame, text="Clustering Method:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.clustering_method_var = tk.StringVar(value='KMeans')
        self.clustering_method_combo = ttk.Combobox(settings_frame, textvariable=self.clustering_method_var, values=['KMeans', 'Spectral', 'HDBSCAN'], state="readonly")
        self.clustering_method_combo.set('KMeans')
        self.clustering_method_combo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.clustering_method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        # Number of clusters
        self.n_clusters_label = ttk.Label(settings_frame, text="Number of Clusters:")
        self.n_clusters_label.grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.n_clusters_var = tk.IntVar(value=3)
        self.n_clusters_spinbox = ttk.Spinbox(settings_frame, from_=2, to=20, width=5, textvariable=self.n_clusters_var)
        self.n_clusters_spinbox.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # Feature settings
        feature_frame = ttk.LabelFrame(scrollable_frame, text="Feature Settings", padding=10)
        feature_frame.pack(fill=tk.X, padx=10, pady=5)
        
        # Configure grid weights for proper expansion
        feature_frame.grid_columnconfigure(1, weight=1)

        # Correlation threshold
        ttk.Label(feature_frame, text="Correlation Threshold:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.correlation_threshold_var = tk.DoubleVar(value=0.85)
        self.correlation_threshold_spinbox = ttk.Spinbox(feature_frame, from_=0.5, to=1.0, increment=0.05, width=5, textvariable=self.correlation_threshold_var)
        self.correlation_threshold_spinbox.grid(row=0, column=1, padx=5, pady=5, sticky="w")
        
        # Remove correlated features
        self.remove_correlated_var = tk.BooleanVar(value=True)
        self.remove_correlated_check = ttk.Checkbutton(feature_frame, text="Remove Correlated Features", variable=self.remove_correlated_var)
        self.remove_correlated_check.grid(row=0, column=2, padx=5, pady=5, sticky="w")
        
        # Analysis options
        options_frame = ttk.LabelFrame(scrollable_frame, text="Analysis Steps", padding=10)
        options_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.extract_features_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Extract cell features", variable=self.extract_features_var).pack(anchor=tk.W)
        
        self.find_optimal_var = tk.BooleanVar(value=False)
        optimal_check = ttk.Checkbutton(options_frame, text="Find optimal number of clusters", 
                                       variable=self.find_optimal_var, command=self.toggle_n_clusters_spinbox)
        optimal_check.pack(anchor=tk.W)
        
        self.perform_clustering_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Perform clustering", variable=self.perform_clustering_var).pack(anchor=tk.W)
        
        self.create_visualizations_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Create visualizations", variable=self.create_visualizations_var).pack(anchor=tk.W)
        
        self.save_results_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame, text="Save results", variable=self.save_results_var).pack(anchor=tk.W)
        
        # Control buttons
        control_frame = ttk.LabelFrame(scrollable_frame, text="Analysis Controls", padding=10)
        control_frame.pack(fill=tk.X, padx=10, pady=5)
        
        button_frame = ttk.Frame(control_frame)
        button_frame.pack(fill=tk.X)
        
        self.run_button = ttk.Button(button_frame, text="Run Analysis", command=self.run_analysis)
        self.run_button.pack(side=tk.LEFT, padx=5)
        
        self.validate_button = ttk.Button(button_frame, text="Validate Clustering", command=self.validate_clustering)
        self.validate_button.pack(side=tk.LEFT, padx=5)
        
        # Progress section
        progress_frame = ttk.LabelFrame(scrollable_frame, text="Progress", padding=10)
        progress_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        self.progress_var = tk.StringVar(value="Ready to start analysis")
        ttk.Label(progress_frame, textvariable=self.progress_var).pack(anchor=tk.W)
        
        self.progress_bar = ttk.Progressbar(progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # Log
        self.log_text = scrolledtext.ScrolledText(progress_frame, height=15, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=5)
        
        # Enable mouse wheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind("<MouseWheel>", _on_mousewheel)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel)
    
    def create_results_tab(self, notebook):
        """Create results viewing tab."""
        results_frame = ttk.Frame(notebook)
        notebook.add(results_frame, text="Results")
        
        # Summary
        summary_frame = ttk.LabelFrame(results_frame, text="Analysis Summary", padding=10)
        summary_frame.pack(fill=tk.X, padx=10, pady=5)
        
        self.results_summary_var = tk.StringVar(value="No analysis completed yet")
        ttk.Label(summary_frame, textvariable=self.results_summary_var, wraplength=800).pack(anchor=tk.W)
        
        # Files
        files_frame = ttk.LabelFrame(results_frame, text="Generated Files", padding=10)
        files_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        # File list
        self.files_listbox = tk.Listbox(files_frame)
        self.files_listbox.pack(fill=tk.BOTH, expand=True)
        
        # File buttons
        file_buttons = ttk.Frame(files_frame)
        file_buttons.pack(fill=tk.X, pady=5)
        
        ttk.Button(file_buttons, text="Refresh", command=self.refresh_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_buttons, text="Open File", command=self.open_selected_file).pack(side=tk.LEFT, padx=5)
        ttk.Button(file_buttons, text="Open Folder", command=self.open_results_folder).pack(side=tk.LEFT, padx=5)
    
    def browse_file(self):
        """Browse for data file."""
        filename = filedialog.askopenfilename(
            title="Select cell outline data file",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filename:
            self.file_path_var.set(filename)
    
    def load_data(self):
        """Load and validate data file."""
        file_path = self.file_path_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Error", "Please select a valid data file")
            return
        
        if not PANDAS_AVAILABLE:
            messagebox.showerror("Error", "pandas is required for data loading. Please install it.")
            return
        
        try:
            # Load data
            data = pd.read_csv(file_path)
            
            # --- Validation ---
            is_new_format = 'outlines' in data.columns and 'mean_volume' in data.columns
            is_old_format = 'Timepoint' in data.columns and ('Outline Points' in data.columns or 'Outline Points 3D' in data.columns)

            if not (is_new_format or is_old_format):
                messagebox.showerror("Error", "Invalid CSV format. The file must contain either ('outlines' and 'mean_volume') for pre-computed features, or ('Timepoint' and 'Outline Points'/'Outline Points 3D') for raw outline data.")
                return

            # Update info
            info_text = f"✓ Data loaded successfully!\n"
            info_text += f"• {len(data)} rows\n"
            info_text += f"• {len(data.columns)} columns\n"
            info_text += f"• {data['Cell ID'].nunique()} unique cells\n"
            if 'Timepoint' in data.columns:
                info_text += f"• {data['Timepoint'].nunique()} timepoints"
            
            self.data_info_var.set(info_text)
            
            # Initialize analyzer if available
            if CLUSTERING_AVAILABLE:
                self.analyzer = CellClusteringAnalyzer(file_path)
                self.current_file = file_path
                self.log_message(f"✓ Data loaded: {file_path}")
            else:
                messagebox.showwarning("Warning", "Clustering module not available. Data loaded for preview only.")
                self.log_message("⚠ Data loaded but clustering not available")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load data: {str(e)}")
            self.log_message(f"✗ Error loading data: {str(e)}")
    
    def update_corr_label(self, *args):
        """Update correlation threshold label."""
        value = self.corr_threshold_var.get()
        self.corr_label.config(text=f"{value:.2f}")
    
    def save_settings(self):
        """Save current settings."""
        filename = filedialog.asksaveasfilename(
            title="Save settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            try:
                settings = {
                    'n_clusters': self.n_clusters_var.get(),
                    'correlation_threshold': self.correlation_threshold_var.get(),
                    'remove_correlated': self.remove_correlated_var.get()
                }
                
                with open(filename, 'w') as f:
                    json.dump(settings, f, indent=2)
                
                messagebox.showinfo("Success", "Settings saved successfully")
                self.log_message(f"✓ Settings saved: {filename}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save settings: {str(e)}")
    
    def load_settings(self):
        """Load settings from file."""
        filename = filedialog.askopenfilename(
            title="Load settings",
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    settings = json.load(f)
                
                # Apply settings
                if 'n_clusters' in settings:
                    self.n_clusters_var.set(settings['n_clusters'])
                if 'correlation_threshold' in settings:
                    self.correlation_threshold_var.set(settings['correlation_threshold'])
                if 'remove_correlated' in settings:
                    self.remove_correlated_var.set(settings['remove_correlated'])
                
                messagebox.showinfo("Success", "Settings loaded successfully")
                self.log_message(f"✓ Settings loaded: {filename}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load settings: {str(e)}")
    
    def reset_settings(self):
        """Reset to default settings."""
        self.n_clusters_var.set(5)
        self.correlation_threshold_var.set(0.85)
        self.remove_correlated_var.set(True)
        
        messagebox.showinfo("Success", "Settings reset to defaults")
        self.log_message("✓ Settings reset to defaults")
    
    def toggle_n_clusters_spinbox(self):
        """Enable or disable the n_clusters spinbox based on the checkbox."""
        if self.find_optimal_var.get():
            self.n_clusters_spinbox.config(state=tk.DISABLED)
        else:
            self.n_clusters_spinbox.config(state=tk.NORMAL)
    
    def run_analysis(self):
        """Run clustering analysis on main thread with progress updates."""
        if not self.analyzer:
            messagebox.showerror("Error", "Please load data first")
            return
        
        if not CLUSTERING_AVAILABLE:
            messagebox.showerror("Error", "Clustering module not available")
            return
        
        if self.analysis_running:
            messagebox.showwarning("Warning", "Analysis is already running")
            return
        
        # Start analysis
        self.analysis_running = True
        self.run_button.config(state=tk.DISABLED)
        self.log_text.delete(1.0, tk.END)
        
        try:
            # Create a unique directory for this analysis run
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.results_dir = Path(f"analysis_results_{timestamp}")
            self.results_dir.mkdir(exist_ok=True)
            self.analyzer.results_dir = self.results_dir
            self.log_message(f"Results will be saved to: {self.results_dir}")

            self._run_analysis_steps()
        except Exception as e:
            messagebox.showerror("Analysis Error", f"Analysis failed: {str(e)}")
            self.log_message(f"✗ Analysis error: {str(e)}")
        finally:
            self.analysis_running = False
            self.run_button.config(state=tk.NORMAL)
            self.progress_bar['value'] = 0
    
    def _run_analysis_steps(self):
        """Run analysis steps with progress updates."""
        steps = []
        if self.extract_features_var.get():
            steps.extend(["load_data", "extract_features"])
        if self.find_optimal_var.get():
            steps.append("find_optimal")
        if self.perform_clustering_var.get():
            steps.append("perform_clustering")
        if self.create_visualizations_var.get():
            steps.append("create_visualizations")
        if self.save_results_var.get():
            steps.append("save_results")
        
        total_steps = len(steps)
        
        for i, step in enumerate(steps):
            progress = (i / total_steps) * 100
            self.progress_bar['value'] = progress
            
            if step == "load_data":
                self.progress_var.set("Loading data...")
                self.root.update()
                self.analyzer.load_data()
                self.log_message("✓ Data loaded")
                
            elif step == "extract_features":
                self.progress_var.set("Extracting features...")
                self.root.update()
                
                # Apply individual feature selection if available
                if FEATURE_DB_AVAILABLE and hasattr(self, 'feature_db') and hasattr(self, 'feature_vars'):
                    # Apply individual feature selections to the database
                    self.apply_individual_feature_selection()
                    
                    # Count selected features
                    selected_features = self.get_selected_individual_features()
                    if selected_features:
                        self.log_message(f"Using {len(selected_features)} selected features")
                        self.analyzer.extract_features_custom(self.feature_db)
                    else:
                        self.log_message("No features selected, using default extraction")
                        self.analyzer.extract_features()
                else:
                    self.analyzer.extract_features()
                
                # Validate that features were extracted
                if self.analyzer.features is None or len(self.analyzer.features) == 0:
                    self.log_message("❌ Error: No features were extracted")
                    return
                
                # Check if the features we need for analysis are available
                available_features = [col for col in self.analyzer.features.columns if col != 'cell_id']
                self.log_message(f"Available features: {', '.join(available_features)}")
                self.log_message("✓ Features extracted")
                
            elif step == "find_optimal":
                self.progress_var.set("Finding optimal clusters...")
                self.root.update()
                try:
                    # Get selected features for optimal cluster finding
                    selected_features = self.get_selected_individual_features()

                    if selected_features:
                        self.log_message(f"Finding optimal clusters using {len(selected_features)} selected features")
                    else:
                        self.log_message("Finding optimal clusters using all available features")
                    
                    clustering_method = self.clustering_method_var.get().lower()
                    self.log_message(f"Finding optimal clusters for method: {clustering_method}")

                    self.optimal_k = self.analyzer.find_optimal_clusters(
                        method=clustering_method,
                        remove_correlated=self.remove_correlated_var.get(),
                        correlation_threshold=self.correlation_threshold_var.get(),
                        selected_features=selected_features if selected_features else None
                    )
                    self.log_message(f"✓ Optimal clusters found: {self.optimal_k}")
                    # Update the spinbox for user feedback
                    self.n_clusters_var.set(self.optimal_k)

                except Exception as e:
                    self.log_message(f"⚠ Optimal cluster finding failed: {str(e)}")
                
            elif step == "perform_clustering":
                self.progress_var.set("Performing clustering...")
                self.root.update()
                
                # Get selected features for clustering
                selected_features = self.get_selected_individual_features()
                if selected_features:
                    self.log_message(f"Using {len(selected_features)} selected features for clustering")
                else:
                    self.log_message("No features selected, using all available features")

                # Determine number of clusters to use
                if self.find_optimal_var.get() and self.optimal_k is not None:
                    n_clusters = self.optimal_k
                    self.log_message(f"Using optimal k = {n_clusters} for clustering.")
                else:
                    n_clusters = self.n_clusters_var.get()
                    self.log_message(f"Using manually set n_clusters = {n_clusters} for clustering.")

                # Get clustering method
                clustering_method = self.clustering_method_var.get().lower()
                self.log_message(f"Using clustering method: {clustering_method}")

                self.analyzer.perform_clustering(
                    n_clusters=n_clusters,
                    method=clustering_method,
                    remove_correlated=self.remove_correlated_var.get(),
                    correlation_threshold=self.correlation_threshold_var.get(),
                    selected_features=selected_features if selected_features else None
                )
                self.log_message("✓ Clustering completed")
                
            elif step == "create_visualizations":
                self.progress_var.set("Creating visualizations...")
                self.root.update()
                try:
                    self.analyzer.visualize_clusters()
                    self.log_message("✓ Visualizations created")
                except Exception as e:
                    self.log_message(f"⚠ Visualization creation failed: {str(e)}")
                
            elif step == "save_results":
                self.progress_var.set("Saving results...")
                self.root.update()
                try:
                    self.analyzer.save_results()
                    self.log_message("✓ Results saved")
                except Exception as e:
                    self.log_message(f"⚠ Results saving failed: {str(e)}")
        
        # Complete
        self.progress_bar['value'] = 100
        self.progress_var.set("✓ Analysis completed successfully!")
        self.update_results_summary()
        self.refresh_files()
        self.log_message("🎉 Analysis complete!")
    
    def update_results_summary(self):
        """Update results display."""
        if not self.analyzer or not hasattr(self.analyzer, 'features'):
            return
        
        try:
            n_cells = len(self.analyzer.features)
            n_clusters = len(self.analyzer.features['cluster'].unique()) if 'cluster' in self.analyzer.features.columns else 0
            
            if hasattr(self.analyzer, 'clusters') and self.analyzer.clusters:
                silhouette = self.analyzer.clusters.get('silhouette_score', 'N/A')
                summary = f"✓ Analysis completed!\n\n"
                summary += f"• Cells analyzed: {n_cells}\n"
                summary += f"• Clusters found: {n_clusters}\n"
                summary += f"• Quality score: {silhouette:.3f}" if silhouette != 'N/A' else f"• Quality score: {silhouette}"
            else:
                summary = f"Features extracted for {n_cells} cells"
            
            self.results_summary_var.set(summary)
            
        except Exception as e:
            self.results_summary_var.set(f"Error updating results: {str(e)}")
    
    def refresh_files(self):
        """Refresh file list."""
        self.files_listbox.delete(0, tk.END)
        
        results_dir = self.results_dir if self.results_dir else Path(".")
        
        if not results_dir.is_dir():
            self.log_message(f"Results directory not found: {results_dir}")
            return

        for file_path in results_dir.iterdir():
            if file_path.is_file() and file_path.suffix in ['.csv', '.png', '.txt', '.json']:
                self.files_listbox.insert(tk.END, file_path.name)
    
    def open_selected_file(self):
        """Open selected file."""
        selection = self.files_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file")
            return
        
        file_name = self.files_listbox.get(selection[0])
        results_dir = self.results_dir if self.results_dir else Path(".")
        file_path = results_dir / file_name
        
        if file_path.exists():
            import subprocess
            import platform
            
            try:
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", str(file_path)])
                elif platform.system() == "Windows":
                    subprocess.run(["start", str(file_path)], shell=True)
                else:  # Linux
                    subprocess.run(["xdg-open", str(file_path)])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open file: {str(e)}")
    
    def open_results_folder(self):
        """Open results folder."""
        results_dir = self.results_dir if self.results_dir else Path(".")
        import subprocess
        import platform
        
        try:
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(results_dir)])
            elif platform.system() == "Windows":
                subprocess.run(["explorer", str(results_dir)])
            else:  # Linux
                subprocess.run(["xdg-open", str(results_dir)])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open folder: {str(e)}")
    
    def log_message(self, message):
        """Add message to log."""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def run_full_analysis(self):
        """Helper to run a full analysis by checking all steps."""
        self.extract_features_var.set(True)
        self.find_optimal_var.set(False)
        self.perform_clustering_var.set(True)
        self.create_visualizations_var.set(True)
        self.save_results_var.set(True)
        self.run_analysis()

    def validate_clustering(self):
        messagebox.showinfo("Not Implemented", "Validation logic is not yet implemented.")

    def save_settings(self):
        """Save current settings."""
        filename = filedialog.asksaveasfilename(
            title="Save settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            try:
                settings = {
                    'n_clusters': self.n_clusters_var.get(),
                    'correlation_threshold': self.correlation_threshold_var.get(),
                    'remove_correlated': self.remove_correlated_var.get()
                }
                
                with open(filename, 'w') as f:
                    json.dump(settings, f, indent=2)
                
                messagebox.showinfo("Success", "Settings saved successfully")
                self.log_message(f"✓ Settings saved: {filename}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save settings: {str(e)}")
    
    def load_settings(self):
        """Load settings from file."""
        filename = filedialog.askopenfilename(
            title="Load settings",
            filetypes=[("JSON files", "*.json")]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    settings = json.load(f)
                
                # Apply settings
                if 'n_clusters' in settings:
                    self.n_clusters_var.set(settings['n_clusters'])
                if 'correlation_threshold' in settings:
                    self.correlation_threshold_var.set(settings['correlation_threshold'])
                if 'remove_correlated' in settings:
                    self.remove_correlated_var.set(settings['remove_correlated'])
                
                messagebox.showinfo("Success", "Settings loaded successfully")
                self.log_message(f"✓ Settings loaded: {filename}")
                
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load settings: {str(e)}")
    
    def reset_settings(self):
        """Reset to default settings."""
        self.n_clusters_var.set(5)
        self.correlation_threshold_var.set(0.85)
        self.remove_correlated_var.set(True)
        
        messagebox.showinfo("Success", "Settings reset to defaults")
        self.log_message("✓ Settings reset to defaults")
    
    def toggle_n_clusters_spinbox(self):
        """Enable or disable the n_clusters spinbox based on the checkbox."""
        if self.find_optimal_var.get():
            self.n_clusters_spinbox.config(state=tk.DISABLED)
        else:
            self.n_clusters_spinbox.config(state=tk.NORMAL)
    
    def run_analysis(self):
        """Run clustering analysis on main thread with progress updates."""
        if not self.analyzer:
            messagebox.showerror("Error", "Please load data first")
            return
        
        if not CLUSTERING_AVAILABLE:
            messagebox.showerror("Error", "Clustering module not available")
            return
        
        if self.analysis_running:
            messagebox.showwarning("Warning", "Analysis is already running")
            return
        
        # Start analysis
        self.analysis_running = True
        self.run_button.config(state=tk.DISABLED)
        self.log_text.delete(1.0, tk.END)
        
        try:
            # Create a unique directory for this analysis run
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            self.results_dir = Path(f"analysis_results_{timestamp}")
            self.results_dir.mkdir(exist_ok=True)
            self.analyzer.results_dir = self.results_dir
            self.log_message(f"Results will be saved to: {self.results_dir}")

            self._run_analysis_steps()
        except Exception as e:
            messagebox.showerror("Analysis Error", f"Analysis failed: {str(e)}")
            self.log_message(f"✗ Analysis error: {str(e)}")
        finally:
            self.analysis_running = False
            self.run_button.config(state=tk.NORMAL)
            self.progress_bar['value'] = 0
    
    def _run_analysis_steps(self):
        """Run analysis steps with progress updates."""
        steps = []
        if self.extract_features_var.get():
            steps.extend(["load_data", "extract_features"])
        if self.find_optimal_var.get():
            steps.append("find_optimal")
        if self.perform_clustering_var.get():
            steps.append("perform_clustering")
        if self.create_visualizations_var.get():
            steps.append("create_visualizations")
        if self.save_results_var.get():
            steps.append("save_results")
        
        total_steps = len(steps)
        
        for i, step in enumerate(steps):
            progress = (i / total_steps) * 100
            self.progress_bar['value'] = progress
            
            if step == "load_data":
                self.progress_var.set("Loading data...")
                self.root.update()
                self.analyzer.load_data()
                self.log_message("✓ Data loaded")
                
            elif step == "extract_features":
                self.progress_var.set("Extracting features...")
                self.root.update()
                
                # Apply individual feature selection if available
                if FEATURE_DB_AVAILABLE and hasattr(self, 'feature_db') and hasattr(self, 'feature_vars'):
                    # Apply individual feature selections to the database
                    self.apply_individual_feature_selection()
                    
                    # Count selected features
                    selected_features = self.get_selected_individual_features()
                    if selected_features:
                        self.log_message(f"Using {len(selected_features)} selected features")
                        self.analyzer.extract_features_custom(self.feature_db)
                    else:
                        self.log_message("No features selected, using default extraction")
                        self.analyzer.extract_features()
                else:
                    self.analyzer.extract_features()
                
                # Validate that features were extracted
                if self.analyzer.features is None or len(self.analyzer.features) == 0:
                    self.log_message("❌ Error: No features were extracted")
                    return
                
                # Check if the features we need for analysis are available
                available_features = [col for col in self.analyzer.features.columns if col != 'cell_id']
                self.log_message(f"Available features: {', '.join(available_features)}")
                self.log_message("✓ Features extracted")
                
            elif step == "find_optimal":
                self.progress_var.set("Finding optimal clusters...")
                self.root.update()
                try:
                    # Get selected features for optimal cluster finding
                    selected_features = self.get_selected_individual_features()

                    if selected_features:
                        self.log_message(f"Finding optimal clusters using {len(selected_features)} selected features")
                    else:
                        self.log_message("Finding optimal clusters using all available features")
                    
                    clustering_method = self.clustering_method_var.get().lower()
                    self.log_message(f"Finding optimal clusters for method: {clustering_method}")

                    self.optimal_k = self.analyzer.find_optimal_clusters(
                        method=clustering_method,
                        remove_correlated=self.remove_correlated_var.get(),
                        correlation_threshold=self.correlation_threshold_var.get(),
                        selected_features=selected_features if selected_features else None
                    )
                    self.log_message(f"✓ Optimal clusters found: {self.optimal_k}")
                    # Update the spinbox for user feedback
                    self.n_clusters_var.set(self.optimal_k)

                except Exception as e:
                    self.log_message(f"⚠ Optimal cluster finding failed: {str(e)}")
                
            elif step == "perform_clustering":
                self.progress_var.set("Performing clustering...")
                self.root.update()
                
                # Get selected features for clustering
                selected_features = self.get_selected_individual_features()
                if selected_features:
                    self.log_message(f"Using {len(selected_features)} selected features for clustering")
                else:
                    self.log_message("No features selected, using all available features")

                # Determine number of clusters to use
                if self.find_optimal_var.get() and self.optimal_k is not None:
                    n_clusters = self.optimal_k
                    self.log_message(f"Using optimal k = {n_clusters} for clustering.")
                else:
                    n_clusters = self.n_clusters_var.get()
                    self.log_message(f"Using manually set n_clusters = {n_clusters} for clustering.")

                # Get clustering method
                clustering_method = self.clustering_method_var.get().lower()
                self.log_message(f"Using clustering method: {clustering_method}")

                self.analyzer.perform_clustering(
                    n_clusters=n_clusters,
                    method=clustering_method,
                    remove_correlated=self.remove_correlated_var.get(),
                    correlation_threshold=self.correlation_threshold_var.get(),
                    selected_features=selected_features if selected_features else None
                )
                self.log_message("✓ Clustering completed")
                
            elif step == "create_visualizations":
                self.progress_var.set("Creating visualizations...")
                self.root.update()
                try:
                    self.analyzer.visualize_clusters()
                    self.log_message("✓ Visualizations created")
                except Exception as e:
                    self.log_message(f"⚠ Visualization creation failed: {str(e)}")
                
            elif step == "save_results":
                self.progress_var.set("Saving results...")
                self.root.update()
                try:
                    self.analyzer.save_results()
                    self.log_message("✓ Results saved")
                except Exception as e:
                    self.log_message(f"⚠ Results saving failed: {str(e)}")
        
        # Complete
        self.progress_bar['value'] = 100
        self.progress_var.set("✓ Analysis completed successfully!")
        self.update_results_summary()
        self.refresh_files()
        self.log_message("🎉 Analysis complete!")
    
    def update_results_summary(self):
        """Update results display."""
        if not self.analyzer or not hasattr(self.analyzer, 'features'):
            return
        
        try:
            n_cells = len(self.analyzer.features)
            n_clusters = len(self.analyzer.features['cluster'].unique()) if 'cluster' in self.analyzer.features.columns else 0
            
            if hasattr(self.analyzer, 'clusters') and self.analyzer.clusters:
                silhouette = self.analyzer.clusters.get('silhouette_score', 'N/A')
                summary = f"✓ Analysis completed!\n\n"
                summary += f"• Cells analyzed: {n_cells}\n"
                summary += f"• Clusters found: {n_clusters}\n"
                summary += f"• Quality score: {silhouette:.3f}" if silhouette != 'N/A' else f"• Quality score: {silhouette}"
            else:
                summary = f"Features extracted for {n_cells} cells"
            
            self.results_summary_var.set(summary)
            
        except Exception as e:
            self.results_summary_var.set(f"Error updating results: {str(e)}")
    
    def refresh_files(self):
        """Refresh file list."""
        self.files_listbox.delete(0, tk.END)
        
        results_dir = self.results_dir if self.results_dir else Path(".")
        
        if not results_dir.is_dir():
            self.log_message(f"Results directory not found: {results_dir}")
            return

        for file_path in results_dir.iterdir():
            if file_path.is_file() and file_path.suffix in ['.csv', '.png', '.txt', '.json']:
                self.files_listbox.insert(tk.END, file_path.name)
    
    def open_selected_file(self):
        """Open selected file."""
        selection = self.files_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Please select a file")
            return
        
        file_name = self.files_listbox.get(selection[0])
        results_dir = self.results_dir if self.results_dir else Path(".")
        file_path = results_dir / file_name
        
        if file_path.exists():
            import subprocess
            import platform
            
            try:
                if platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", str(file_path)])
                elif platform.system() == "Windows":
                    subprocess.run(["start", str(file_path)], shell=True)
                else:  # Linux
                    subprocess.run(["xdg-open", str(file_path)])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to open file: {str(e)}")
    
    def open_results_folder(self):
        """Open results folder."""
        results_dir = self.results_dir if self.results_dir else Path(".")
        import subprocess
        import platform
        
        try:
            if platform.system() == "Darwin":  # macOS
                subprocess.run(["open", str(results_dir)])
            elif platform.system() == "Windows":
                subprocess.run(["explorer", str(results_dir)])
            else:  # Linux
                subprocess.run(["xdg-open", str(results_dir)])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open folder: {str(e)}")
    
    def log_message(self, message):
        """Add message to log."""
        self.log_text.insert(tk.END, f"{message}\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def run_full_analysis(self):
        """Helper to run a full analysis by checking all steps."""
        self.extract_features_var.set(True)
        self.find_optimal_var.set(False)
        self.perform_clustering_var.set(True)
        self.create_visualizations_var.set(True)
        self.save_results_var.set(True)
        self.run_analysis()

    def validate_clustering(self):
        messagebox.showinfo("Not Implemented", "Validation logic is not yet implemented.")