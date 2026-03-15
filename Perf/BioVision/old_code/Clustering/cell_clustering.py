import ast
import pandas as pd
import numpy as np
from sklearn.cluster import KMeans, SpectralClustering
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
import matplotlib.pyplot as plt
import seaborn as sns
import umap
from pathlib import Path

try:
    import hdbscan
except ImportError:
    hdbscan = None

class CellClusteringAnalyzer:
    def __init__(self, csv_path):
        """
        Initialize the clustering analyzer with cell outline data.
        
        Args:
            csv_path (str): Path to the outline_data.csv file
        """
        self.csv_path = csv_path
        self.data = None
        self.features = None
        self.clusters = None
        self.scaler = StandardScaler()
        self.clustering_features = None  # Store features used for clustering
        self.results_dir = Path(".")
    
    def get_clustering_features(self):
        """Get the features that were used for clustering, ensuring consistency."""
        if self.clustering_features is not None:
            return self.clustering_features
        else:
            # Fallback to all available features if clustering_features not set
            return [col for col in self.features.columns if col not in ['cell_id', 'cluster']]
        
    def load_data(self):
        """Load and parse the CSV data."""
        print("Loading data...")
        self.data = pd.read_csv(self.csv_path)
        print(f"Loaded {len(self.data)} rows of data")

        # Handle pre-computed features from quant_daeta2.csv
        if 'outlines' in self.data.columns and 'mean_volume' in self.data.columns:
            print("Detected pre-computed features. Loading them and parsing outlines for additional feature computation.")
            
            # Parse the outline points from the string format
            import ast
            self.data['outline_points'] = self.data['outlines'].apply(ast.literal_eval)
            
            # Define feature columns from the new CSV - find all numeric columns except Cell ID and outlines
            feature_columns = []
            for col in self.data.columns:
                if col not in ['Cell ID', 'outlines'] and self.data[col].dtype in ['float64', 'int64']:
                    feature_columns.append(col)
            
            # Create the features DataFrame
            self.features = self.data[['Cell ID'] + feature_columns].rename(columns={'Cell ID': 'cell_id'})
            
            print(f"Loaded pre-computed features for {len(self.features)} cells: {feature_columns}")
            print("Outline points are available for computing additional geometric features on demand.")

        # Handle original outline data format
        elif 'Outline Points 3D' in self.data.columns or 'Outline Points' in self.data.columns:
            if 'Outline Points 3D' in self.data.columns:
                self.data['outline_points'] = self.data['Outline Points 3D'].apply(ast.literal_eval)
            else: # 'Outline Points'
                self.data['outline_points'] = self.data['Outline Points'].apply(ast.literal_eval)

            # This part should only run for the old data format
            if 'Timepoint' in self.data.columns:
                unique_cells = self.data['Cell ID'].unique()
                unique_timepoints = sorted(self.data['Timepoint'].unique())
                print(f"Found {len(unique_cells)} unique cells across {len(unique_timepoints)} timepoints")

        else:
            raise ValueError("CSV file must contain 'outlines' and pre-computed features, or 'Outline Points'/'Outline Points 3D'.")
            
        return self.data
    
    def calculate_cell_features(self, outline_points):
        """
        Calculate features from cell outline points.
        
        Args:
            outline_points (list): List of [x, y] coordinates
            
        Returns:
            dict: Dictionary of calculated features
        """
        points = np.array(outline_points)
        
        # Basic geometric features
        x_coords = points[:, 0]
        y_coords = points[:, 1]
        
        # Centroid
        centroid_x = np.mean(x_coords)
        centroid_y = np.mean(y_coords)
        
        # Area using shoelace formula
        area = 0.5 * abs(sum(x_coords[i] * y_coords[i+1] - x_coords[i+1] * y_coords[i] 
                            for i in range(-1, len(x_coords)-1)))
        
        # Perimeter
        perimeter = sum(np.sqrt((x_coords[i+1] - x_coords[i])**2 + (y_coords[i+1] - y_coords[i])**2) 
                       for i in range(-1, len(x_coords)-1))
        
        # Bounding box
        width = np.max(x_coords) - np.min(x_coords)
        height = np.max(y_coords) - np.min(y_coords)
        
        # Shape descriptors
        circularity = 4 * np.pi * area / (perimeter**2) if perimeter > 0 else 0
        aspect_ratio = width / height if height > 0 else 0
        
        # Distance from centroid statistics
        distances = np.sqrt((x_coords - centroid_x)**2 + (y_coords - centroid_y)**2)
        mean_radius = np.mean(distances)
        std_radius = np.std(distances)
        
        return {
            'area': area,
            'perimeter': perimeter,
            'width': width,
            'height': height,
            'centroid_x': centroid_x,
            'centroid_y': centroid_y,
            'circularity': circularity,
            'aspect_ratio': aspect_ratio,
            'mean_radius': mean_radius,
            'std_radius': std_radius
        }
    
    def calculate_3d_features(self, outline_points_3d):
        """
        Calculate geometric features from 3D cell outline points.
        
        Args:
            outline_points_3d (list): List of 3D outline points [[[x, y, z], ...], ...]
            
        Returns:
            dict: Dictionary of calculated features
        """
        try:
            # Handle nested list structure from quant_daeta2.csv
            if isinstance(outline_points_3d, list) and len(outline_points_3d) > 0:
                if isinstance(outline_points_3d[0], list) and len(outline_points_3d[0]) > 0:
                    # Take the first timepoint/slice if multiple exist
                    points = outline_points_3d[0]
                    if isinstance(points[0], list) and len(points[0]) > 0:
                        points = points[0]  # Handle triple nesting
                else:
                    points = outline_points_3d
            else:
                return {}
            
            if not points or len(points) < 3:
                return {}
            
            points = np.array(points)
            
            # Extract coordinates
            if points.shape[1] >= 3:
                x_coords = points[:, 0]
                y_coords = points[:, 1]
                z_coords = points[:, 2]
            else:
                x_coords = points[:, 0]
                y_coords = points[:, 1]
                z_coords = np.zeros(len(points))  # No Z data
            
            # Centroids
            centroid_x = np.mean(x_coords)
            centroid_y = np.mean(y_coords)
            centroid_z = np.mean(z_coords) if points.shape[1] >= 3 else 0
            
            # 2D projection for area and perimeter calculations
            points_2d = points[:, :2] if points.shape[1] >= 2 else points
            
            # Area using shoelace formula (2D projection)
            area = 0.5 * abs(sum(points_2d[i, 0] * points_2d[i+1, 1] - points_2d[i+1, 0] * points_2d[i, 1] 
                                for i in range(-1, len(points_2d)-1)))
            
            # Perimeter (2D projection)
            perimeter = sum(np.sqrt((points_2d[i+1, 0] - points_2d[i, 0])**2 + 
                                   (points_2d[i+1, 1] - points_2d[i, 1])**2) 
                           for i in range(-1, len(points_2d)-1))
            
            # Bounding box
            width = np.max(x_coords) - np.min(x_coords)
            height = np.max(y_coords) - np.min(y_coords)
            
            # Shape descriptors
            circularity = 4 * np.pi * area / (perimeter**2) if perimeter > 0 else 0
            aspect_ratio = width / height if height > 0 else 0
            
            # Distance from centroid statistics (3D)
            distances_3d = np.sqrt((x_coords - centroid_x)**2 + 
                                  (y_coords - centroid_y)**2 + 
                                  (z_coords - centroid_z)**2)
            mean_radius = np.mean(distances_3d)
            
            return {
                'mean_area': area,
                'mean_perimeter': perimeter,
                'mean_width': width,
                'mean_height': height,
                'mean_centroid_x': centroid_x,
                'mean_centroid_y': centroid_y,
                'mean_centroid_z': centroid_z,
                'mean_circularity': circularity,
                'mean_aspect_ratio': aspect_ratio,
                'mean_radius': mean_radius
            }
            
        except Exception as e:
            print(f"Error calculating 3D features: {e}")
            return {}
    
    def compute_additional_features(self, requested_features=None):
        """
        Compute additional geometric features from outline points when needed.
        
        Args:
            requested_features (list): List of feature names to compute
            
        Returns:
            pandas.DataFrame: Updated features DataFrame with additional computed features
        """
        if self.data is None or 'outline_points' not in self.data.columns:
            print("No outline points available for additional feature computation.")
            return self.features
        
        print("Computing additional geometric features from outline points...")
        
        # Define which features can be computed from outline points
        computable_features = {
            'mean_area', 'mean_perimeter', 'mean_width', 'mean_height',
            'mean_centroid_x', 'mean_centroid_y', 'mean_centroid_z',
            'mean_circularity', 'mean_aspect_ratio', 'mean_radius'
        }
        
        # Determine which features to compute
        if requested_features:
            features_to_compute = set(requested_features) & computable_features
        else:
            features_to_compute = computable_features
        
        if not features_to_compute:
            print("No computable features requested.")
            return self.features
        
        print(f"Computing features: {features_to_compute}")
        
        # Compute features for each cell
        additional_features = {}
        for idx, row in self.data.iterrows():
            cell_id = row['Cell ID']
            outline_points = row.get('outline_points', [])
            
            if outline_points:
                computed = self.calculate_3d_features(outline_points)
                
                # Only keep requested features
                for feature in features_to_compute:
                    if feature in computed:
                        if feature not in additional_features:
                            additional_features[feature] = []
                        additional_features[feature].append(computed[feature])
                    else:
                        if feature not in additional_features:
                            additional_features[feature] = []
                        additional_features[feature].append(0.0)  # Default value
            else:
                # Add default values for missing outline points
                for feature in features_to_compute:
                    if feature not in additional_features:
                        additional_features[feature] = []
                    additional_features[feature].append(0.0)
        
        # Add computed features to the features DataFrame
        for feature, values in additional_features.items():
            if len(values) == len(self.features):
                # Only add the feature if it doesn't already exist
                if feature not in self.features.columns:
                    self.features[feature] = values
                    print(f"✓ Added feature: {feature}")
                else:
                    print(f"⚠ Skipped feature {feature}: already exists")
            else:
                print(f"⚠ Skipped feature {feature}: length mismatch")
        
        print(f"✓ Computed {len(additional_features)} additional features")
        return self.features
    
    def extract_features_custom(self, feature_database):
        """
        Extract features using the custom feature database with user selections.
        
        Args:
            feature_database: FeatureDatabase instance with user selections
        """
        # If features are already loaded from CSV, just check what additional features are needed
        if self.features is not None and not self.features.empty:
            print("Pre-computed features already loaded from CSV.")
            
            # Get enabled features from the feature database
            enabled_features = []
            for category_name, features in feature_database.feature_categories.items():
                for feature_id, feature_info in features.items():
                    if feature_info.get("enabled", False):
                        enabled_features.append(feature_id)
            
            if enabled_features:
                print(f"Computing additional features requested by user: {enabled_features}")
                # Compute additional features that are not in the pre-computed set
                missing_features = [f for f in enabled_features if f not in self.features.columns]
                if missing_features:
                    self.compute_additional_features(missing_features)
                else:
                    print("All requested features are already available.")
            
            return self.features
        
        # If no pre-computed features, fall back to regular extraction
        print("No pre-computed features found, performing regular feature extraction...")
        return self.extract_features(feature_database)

    def extract_features(self, feature_database=None):
        """Extract features for each cell across all timepoints, calculating the mean value."""
        if self.features is not None and not self.features.empty:
            print("Features already loaded from quant_daeta2.csv, skipping extraction.")
            return self.features

        print("Extracting features (mean values only)...")

        if self.data is None or len(self.data) == 0:
            print("Data not loaded. Please load data first.")
            return None

        # Calculate features for each row (timepoint) using the feature database
        feature_rows = []
        for idx, row in self.data.iterrows():
            outline_points = row.get('outline_points', [])
            if not isinstance(outline_points, list) or not outline_points:
                continue
            
            calculated_features = feature_database.calculate_features(outline_points)
            calculated_features['cell_id'] = row['Cell ID']
            calculated_features['timepoint'] = row['Timepoint']
            feature_rows.append(calculated_features)

        if not feature_rows:
            print("Could not extract any features from the data.")
            self.features = pd.DataFrame()
            return self.features

        feature_df = pd.DataFrame(feature_rows)
        
        # Clean data: replace inf and extreme values with NaN
        feature_df = feature_df.replace([np.inf, -np.inf], np.nan)

        # --- Aggregation ---
        
        # Get a list of all feature columns (excluding identifiers and temporal placeholders)
        feature_cols = [col for col in feature_df.columns if col not in ['cell_id', 'timepoint']]

        # Calculate the mean for all morphological features
        cell_features_agg = feature_df.groupby('cell_id')[feature_cols].mean()

        # --- Temporal Feature Calculation ---
        
        # Sort by cell and time to ensure correct order for temporal calculations
        feature_df.sort_values(by=['cell_id', 'timepoint'], inplace=True)
        
        temporal_features = []
        for cell_id, group in feature_df.groupby('cell_id'):
            cell_temporal_features = {'cell_id': cell_id}
            if len(group) > 1:
                # Check if 'centroid_x' and 'centroid_y' were calculated
                if 'centroid_x' in group.columns and 'centroid_y' in group.columns:
                    points = group[['centroid_x', 'centroid_y']].values
                    distances = np.sqrt(np.sum(np.diff(points, axis=0)**2, axis=1))
                    total_distance = np.sum(distances)
                    mean_speed = np.mean(distances) if distances.size > 0 else 0
                else:
                    total_distance = 0
                    mean_speed = 0
            else:
                total_distance = 0
                mean_speed = 0
            
            cell_temporal_features['mean_speed'] = mean_speed
            cell_temporal_features['total_distance'] = total_distance
            temporal_features.append(cell_temporal_features)
        
        if temporal_features:
            temporal_df = pd.DataFrame(temporal_features).set_index('cell_id')
            # Rename speed to mean_speed to avoid conflicts
            if 'speed' in cell_features_agg.columns:
                cell_features_agg.rename(columns={'speed': 'mean_speed'}, inplace=True)
            cell_features_agg = cell_features_agg.join(temporal_df, rsuffix='_temporal')

        self.features = cell_features_agg.reset_index()

        # Final cleanup
        self.features = self.features.replace([np.inf, -np.inf, np.nan], 0)

        zero_columns = self.features.columns[(self.features == 0).all()].tolist()
        if 'cell_id' in zero_columns:
            zero_columns.remove('cell_id')
        if zero_columns:
            self.features.drop(columns=zero_columns, inplace=True)
            print(f"Removed empty feature columns: {zero_columns}")

        print(f"Extracted features for {len(self.features)} cells")
        print(f"Features: {[col for col in self.features.columns if col != 'cell_id']}")
        return self.features
    
    def remove_correlated_features(self, correlation_threshold=0.85):
        """
        Remove features that are highly correlated to reduce redundancy.
        
        Args:
            correlation_threshold (float): Correlation threshold above which features are removed
        """
        print(f"Removing features with correlation > {correlation_threshold}...")
        
        # Get numeric features (exclude cell_id and cluster if present)
        feature_columns = [col for col in self.features.columns 
                          if col not in ['cell_id', 'cluster'] and 
                          self.features[col].dtype in ['int64', 'float64']]
        
        # Calculate correlation matrix
        correlation_data = self.features[feature_columns].fillna(0)
        correlation_matrix = correlation_data.corr().abs()  # Use absolute values
        
        # Find features to remove
        features_to_remove = set()
        
        # Iterate through correlation matrix
        for i in range(len(correlation_matrix.columns)):
            for j in range(i+1, len(correlation_matrix.columns)):
                feature1 = correlation_matrix.columns[i]
                feature2 = correlation_matrix.columns[j]
                corr_val = correlation_matrix.iloc[i, j]
                
                if corr_val > correlation_threshold:
                    # Keep the feature with higher variance (more informative)
                    var1 = self.features[feature1].var()
                    var2 = self.features[feature2].var()
                    
                    if var1 >= var2:
                        features_to_remove.add(feature2)
                        print(f"  Removing {feature2} (corr with {feature1}: {corr_val:.3f})")
                    else:
                        features_to_remove.add(feature1)
                        print(f"  Removing {feature1} (corr with {feature2}: {corr_val:.3f})")
        
        # Remove highly correlated features
        if features_to_remove:
            remaining_features = len(feature_columns) - len(features_to_remove)
            print(f"Removed {len(features_to_remove)} highly correlated features")
            print(f"Remaining features: {remaining_features}")
            
            # Check if we would have enough features left
            if remaining_features < 1:
                print("Warning: Correlation removal would leave no features. Keeping all features.")
                self.removed_features = []
                return set()
            
            # Store removed features for reference
            self.removed_features = list(features_to_remove)
            
            # Keep track of original features
            if not hasattr(self, 'original_features'):
                self.original_features = self.features.copy()
            
            # Remove features from the dataframe
            self.features = self.features.drop(columns=list(features_to_remove))
        else:
            print("No highly correlated features found to remove")
            self.removed_features = []
        
        return features_to_remove
    
    def _remove_correlated_from_selection(self, feature_columns, correlation_threshold=0.85):
        """
        Remove highly correlated features from a specific selection of features.
        This method doesn't modify self.features, just returns filtered feature list.
        
        Args:
            feature_columns (list): List of feature column names to check
            correlation_threshold (float): Correlation threshold above which features are removed
            
        Returns:
            list: Filtered list of feature column names with correlated features removed
        """
        if len(feature_columns) < 2:
            print("Not enough selected features to check correlations.")
            return feature_columns
        
        # Calculate correlation matrix for selected features only
        correlation_data = self.features[feature_columns].fillna(0)
        correlation_matrix = correlation_data.corr().abs()  # Use absolute values
        
        # Find features to remove
        features_to_remove = set()
        
        # Iterate through correlation matrix
        for i in range(len(correlation_matrix.columns)):
            for j in range(i+1, len(correlation_matrix.columns)):
                feature1 = correlation_matrix.columns[i]
                feature2 = correlation_matrix.columns[j]
                corr_val = correlation_matrix.iloc[i, j]
                
                if corr_val > correlation_threshold:
                    # Keep the feature with higher variance (more informative)
                    var1 = self.features[feature1].var()
                    var2 = self.features[feature2].var()
                    
                    if var1 >= var2:
                        features_to_remove.add(feature2)
                        print(f"  Removing {feature2} (corr with {feature1}: {corr_val:.3f})")
                    else:
                        features_to_remove.add(feature1)
                        print(f"  Removing {feature1} (corr with {feature2}: {corr_val:.3f})")
        
        # Remove highly correlated features from selection
        filtered_features = [f for f in feature_columns if f not in features_to_remove]
        
        if features_to_remove:
            remaining_features = len(filtered_features)
            print(f"Removed {len(features_to_remove)} highly correlated features from selection")
            print(f"Remaining selected features: {remaining_features}")
            
            # Check if we would have enough features left
            if remaining_features < 1:
                print("Warning: Correlation removal would leave no selected features. Keeping all selected features.")
                return feature_columns
        else:
            print("No highly correlated features found in selection")
        
        return filtered_features
    
    def _map_selected_features(self, selected_features):
        """Map selected feature names to actual feature columns."""
        if selected_features is None:
            # If no features are selected, use all available features except cell_id and cluster
            available_features = [col for col in self.features.columns if col not in ['cell_id', 'cluster']]
            print(f"No features selected, using all available: {available_features}")
            return available_features

        print(f"User selected features: {selected_features}")
        
        # Direct mapping, if 'speed' is selected, it should map to 'mean_speed'
        mapped = []
        for feature in selected_features:
            if feature == 'speed':
                mapped.append('mean_speed')
            elif feature == 'centroid_x':
                mapped.append('mean_centroid_x')
            elif feature == 'centroid_y':
                mapped.append('mean_centroid_y')
            elif feature == 'centroid_z':
                mapped.append('mean_centroid_z')
            elif feature == 'surface_area':
                mapped.append('mean_surface_area')
            elif feature == 'volume':
                mapped.append('mean_volume')
            else:
                mapped.append(feature)
        
        print(f"Mapped to: {mapped}")
        
        # Ensure we only return features that actually exist in the dataframe
        available_features = [col for col in self.features.columns if col not in ['cell_id', 'cluster']]
        filtered_mapped = [f for f in mapped if f in available_features]
        
        if len(filtered_mapped) < len(mapped):
            missing = set(mapped) - set(filtered_mapped)
            print(f"Warning: Some selected features are not available: {missing}")
            print(f"Available features: {available_features}")
        
        print(f"Final features for clustering: {filtered_mapped}")
        return filtered_mapped
    
    def perform_clustering(self, n_clusters=3, method='kmeans', remove_correlated=True, correlation_threshold=0.85, selected_features=None):
        """
        Perform clustering on the extracted features.
        
        Args:
            n_clusters (int): Number of clusters
            method (str): Clustering method ('kmeans', 'spectral', or 'hdbscan')
            remove_correlated (bool): Whether to remove highly correlated features
            correlation_threshold (float): Correlation threshold for feature removal
            selected_features (list): List of specific features to use for clustering. If None, uses all features.
        """
        print(f"Performing {method} clustering...")
        
        # Check if features exist
        if self.features is None or len(self.features) == 0:
            raise ValueError("No features available for clustering. Please extract features first.")
        
        # Select features for clustering first
        feature_columns = self._map_selected_features(selected_features)
        
        # Remove highly correlated features if requested
        # Apply correlation removal to selected features when user has made selections
        if remove_correlated:
            if selected_features is None:
                # No specific feature selection - remove from all features
                self.remove_correlated_features(correlation_threshold)
                # Re-map features after removal
                feature_columns = self._map_selected_features(selected_features)
            else:
                # User has selected specific features - apply correlation removal to those features only
                print(f"Checking for correlated features among selected features (threshold: {correlation_threshold})...")
                feature_columns = self._remove_correlated_from_selection(feature_columns, correlation_threshold)
        
        if len(feature_columns) == 0:
            raise ValueError("No valid features available for clustering after preprocessing.")
        
        print(f"Using {len(feature_columns)} features for clustering: {feature_columns}")
        
        X = self.features[feature_columns].fillna(0)
        
        # Check if we have enough data points
        if method != 'hdbscan' and len(X) < n_clusters:
            raise ValueError(f"Not enough data points ({len(X)}) for {n_clusters} clusters. "
                           f"Reduce the number of clusters or provide more data.")
        
        # Check for features with zero variance
        feature_variances = X.var()
        zero_var_features = feature_variances[feature_variances == 0].index.tolist()
        if zero_var_features:
            print(f"Warning: Features with zero variance detected: {zero_var_features}")
            print("These features will be removed from clustering.")
            X = X.drop(columns=zero_var_features)
            feature_columns = [col for col in feature_columns if col not in zero_var_features]
        
        if len(feature_columns) == 0:
            raise ValueError("All features have zero variance. Cannot perform clustering.")
        
        # Store the features used for clustering to ensure consistency in visualizations
        self.clustering_features = feature_columns
        
        # Standardize features
        try:
            # Check if X has valid data
            if X.empty or X.isnull().all().all():
                raise ValueError("All feature data is empty or NaN")
            
            # Check for infinite values
            if np.isinf(X.values).any():
                print("Warning: Infinite values detected in features. Replacing with 0.")
                X = X.replace([np.inf, -np.inf], 0)
            
            X_scaled = self.scaler.fit_transform(X)
            
            # Validate scaled data
            if np.isnan(X_scaled).any() or np.isinf(X_scaled).any():
                print("Warning: NaN or infinite values in scaled features. This may cause clustering issues.")
                X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)
                
        except Exception as e:
            print(f"Error during feature standardization: {e}")
            print("This might be due to features with constant values or insufficient data.")
            print(f"Feature statistics:")
            print(X.describe())
            raise ValueError(f"Feature standardization failed: {e}")
        
        # Perform clustering
        try:
            if method == 'kmeans':
                print(f"Clustering with {n_clusters} clusters...")
                model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                cluster_labels = model.fit_predict(X_scaled)
                actual_n_clusters = n_clusters
            elif method == 'spectral':
                print(f"Clustering with {n_clusters} clusters...")
                # Determine n_neighbors for spectral clustering
                n_neighbors = min(len(X_scaled) - 1, 10)
                if n_neighbors < 2:
                    raise ValueError(f"Not enough neighbors ({n_neighbors}) for Spectral Clustering.")
                
                model = SpectralClustering(n_clusters=n_clusters, random_state=42, assign_labels='kmeans', affinity='nearest_neighbors', n_neighbors=n_neighbors)
                cluster_labels = model.fit_predict(X_scaled)
                actual_n_clusters = n_clusters
            elif method == 'hdbscan':
                print("Clustering with HDBSCAN (n_clusters is determined automatically)...")
                model = hdbscan.HDBSCAN(min_cluster_size=5, gen_min_span_tree=True)
                cluster_labels = model.fit_predict(X_scaled)
                # Number of clusters in labels, ignoring noise if present.
                actual_n_clusters = len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)
                print(f"HDBSCAN found {actual_n_clusters} clusters.")
            else:
                raise ValueError(f"Unsupported clustering method: {method}")

        except Exception as e:
            print(f"Error during clustering: {e}")
            raise ValueError(f"Clustering failed: {e}")
        
        # Add cluster labels to features
        self.features['cluster'] = cluster_labels
        
        # Calculate silhouette score
        try:
            if len(set(cluster_labels)) > 1:  # Need at least 2 clusters for silhouette score
                silhouette_avg = silhouette_score(X_scaled, cluster_labels)
            else:
                silhouette_avg = 0.0
                print("Warning: Only one cluster found, silhouette score set to 0")
        except Exception as e:
            print(f"Warning: Could not calculate silhouette score: {e}")
            silhouette_avg = 0.0
        
        print(f"Silhouette Score: {silhouette_avg:.3f}")
        
        # Store clustering results
        self.clusters = {
            'model': model,
            'labels': cluster_labels,
            'silhouette_score': silhouette_avg,
            'n_clusters': actual_n_clusters
        }
        
        return cluster_labels

    def find_optimal_clusters(self, max_clusters=8, method='kmeans', remove_correlated=True, correlation_threshold=0.85, selected_features=None):
        """Find optimal number of clusters using elbow method and silhouette score."""
        if method == 'hdbscan':
            print("Warning: 'Find optimal clusters' is not applicable for HDBSCAN.")
            print("HDBSCAN determines the number of clusters automatically.")
            # Return a default value or simply don't run clustering here
            return 5 # A reasonable default, though it won't be used by HDBSCAN clustering.

        print(f"Finding optimal number of clusters for {method} clustering...")
        
        # Check if features exist
        if self.features is None or len(self.features) == 0:
            raise ValueError("No features available for clustering. Please extract features first.")
        
        # Remove highly correlated features if requested
        if remove_correlated:
            self.remove_correlated_features(correlation_threshold)
        
        # Select features for clustering
        feature_columns = self._map_selected_features(selected_features)
        
        if len(feature_columns) == 0:
            raise ValueError("No valid features available for clustering after preprocessing.")
        
        X = self.features[feature_columns].fillna(0)
        
        # Check for features with zero variance
        feature_variances = X.var()
        zero_var_features = feature_variances[feature_variances == 0].index.tolist()
        if zero_var_features:
            print(f"Warning: Features with zero variance detected: {zero_var_features}")
            print("These features will be removed from clustering.")
            X = X.drop(columns=zero_var_features)
            feature_columns = [col for col in feature_columns if col not in zero_var_features]
        
        if len(feature_columns) == 0:
            raise ValueError("All features have zero variance. Cannot perform clustering.")
        
        # Store the features used for clustering to ensure consistency
        self.clustering_features = feature_columns
        
        # Limit max_clusters based on available data
        max_possible_clusters = min(max_clusters, len(X) - 1)
        if max_possible_clusters < 2:
            raise ValueError(f"Not enough data points ({len(X)}) for meaningful clustering.")
        
        try:
            X_scaled = self.scaler.fit_transform(X)
        except Exception as e:
            raise ValueError(f"Error during feature standardization: {str(e)}")
        
        inertias = []
        silhouette_scores = []
        k_range = range(2, min(max_clusters + 1, len(X)))
        
        for k in k_range:
            if method == 'kmeans':
                model = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = model.fit_predict(X_scaled)
                inertias.append(model.inertia_)
                silhouette_scores.append(silhouette_score(X_scaled, labels))
            elif method == 'spectral':
                # Determine n_neighbors for spectral clustering
                n_neighbors = min(len(X_scaled) - 1, 10)
                if n_neighbors < 2:
                    # Not enough neighbors, skip this k
                    silhouette_scores.append(-1) # Append a poor score
                    continue
                model = SpectralClustering(n_clusters=k, random_state=42, assign_labels='kmeans', affinity='nearest_neighbors', n_neighbors=n_neighbors)
                labels = model.fit_predict(X_scaled)
                # SpectralClustering does not have an 'inertia_' attribute.
                # We can only use silhouette score.
                silhouette_scores.append(silhouette_score(X_scaled, labels))
            else:
                raise ValueError(f"Unsupported method for finding optimal clusters: {method}")

        # Plot results
        if method == 'kmeans':
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            
            # Elbow plot
            ax1.plot(k_range, inertias, 'bo-')
            ax1.set_xlabel('Number of Clusters')
            ax1.set_ylabel('Inertia')
            ax1.set_title('Elbow Method for Optimal k')
            ax1.grid(True)
            
            # Silhouette plot
            ax2.plot(k_range, silhouette_scores, 'ro-')
            ax2.set_xlabel('Number of Clusters')
            ax2.set_ylabel('Silhouette Score')
            ax2.set_title('Silhouette Score vs Number of Clusters')
            ax2.grid(True)
        else:  # for spectral and other methods
            fig = plt.figure(figsize=(8, 6))
            plt.plot(k_range, silhouette_scores, 'ro-')
            plt.xlabel('Number of Clusters')
            plt.ylabel('Silhouette Score')
            plt.title(f'Silhouette Score for {method.title()} Clustering')
            plt.grid(True)
        
        plt.tight_layout()
        plot_path = self.results_dir / 'optimal_clusters.png'
        plt.savefig(plot_path, dpi=300, bbox_inches='tight')
        plt.close(fig if 'fig' in locals() else plt.gcf()) # Close the plot to free memory
        print(f"Saved optimal cluster plot to '{plot_path}'")
        
        # Recommend optimal k based on the highest silhouette score
        if not silhouette_scores:
            print("Warning: Could not determine optimal k. Returning default of 3.")
            return 3
            
        optimal_k = k_range[np.argmax(silhouette_scores)]
        print(f"Recommended number of clusters based on silhouette score: {optimal_k}")
        
        return optimal_k
    
    def create_umap_visualization(self):
        """Create UMAP visualization of the clusters."""
        if self.clusters is None:
            print("No clustering results found. Run perform_clustering first.")
            return
        
        print("Creating UMAP visualization...")
        
        # Use the same features that were used for clustering to avoid scaler mismatch
        if self.clustering_features is not None:
            feature_columns = self.clustering_features
        else:
            # Fallback to all features if clustering_features not set
            feature_columns = [col for col in self.features.columns 
                              if col not in ['cell_id', 'cluster']]
        
        X = self.features[feature_columns].fillna(0)
        
        # Handle infinite values
        if np.isinf(X.values).any():
            X = X.replace([np.inf, -np.inf], 0)
        
        X_scaled = self.scaler.transform(X)
        
        # Apply UMAP
        reducer = umap.UMAP(n_neighbors=15, min_dist=0.1, n_components=2, random_state=42)
        embedding = reducer.fit_transform(X_scaled)
        
        # Create UMAP plot
        plt.figure(figsize=(12, 8))
        
        unique_labels = sorted(self.features['cluster'].unique())
        n_clusters = self.clusters.get('n_clusters', len(unique_labels))
        
        # Generate colors for actual clusters, handling case where n_clusters might be 0
        if n_clusters > 0:
            colors = plt.cm.Set1(np.linspace(0, 1, n_clusters))
        else:
            colors = []

        for cluster_label in unique_labels:
            mask = self.features['cluster'] == cluster_label
            cluster_embedding = embedding[mask]
            cluster_count = np.sum(mask)
            
            if cluster_label == -1:
                # Outliers
                plt.scatter(cluster_embedding[:, 0], cluster_embedding[:, 1], 
                           c='grey', label=f'Outliers (n={cluster_count})',
                           alpha=0.5, s=30)
            else:
                # Regular clusters
                if n_clusters > 0:
                    color_index = cluster_label % n_clusters
                    color = colors[color_index]
                else:
                    color = 'blue'
                plt.scatter(cluster_embedding[:, 0], cluster_embedding[:, 1], 
                           c=np.array([color]), label=f'Cluster {cluster_label} (n={cluster_count})',
                           alpha=0.7, s=60)
        
        plt.xlabel('UMAP Dimension 1')
        plt.ylabel('UMAP Dimension 2')
        plt.title('UMAP Visualization of Cell Clusters')
        plt.legend()
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.results_dir / 'umap_clusters.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        # Store UMAP results
        self.umap_embedding = embedding
        
        return embedding
    
    def get_cluster_outliers(self):
        """Get outlier cells identified by HDBSCAN."""
        if self.clusters is None or 'labels' not in self.clusters:
            print("No clustering results available.")
            return pd.DataFrame()
        
        outlier_mask = self.features['cluster'] == -1
        outliers = self.features[outlier_mask]
        
        if not outliers.empty:
            print(f"Found {len(outliers)} outlier cells (cluster -1).")
        else:
            print("No outlier cells found.")
            
        return outliers

    def create_correlation_matrix(self):
        """Create correlation matrix for features used in clustering."""
        print("Creating feature correlation matrix...")
        
        # Use the same features that were used for clustering
        if hasattr(self, 'clustering_features') and self.clustering_features is not None:
            feature_columns = self.clustering_features
            print(f"Creating correlation matrix for clustering features: {feature_columns}")
        else:
            # Fallback to all features if clustering_features not set
            feature_columns = [col for col in self.features.columns 
                              if col not in ['cell_id', 'cluster'] and 
                              self.features[col].dtype in ['int64', 'float64']]
            print(f"Creating correlation matrix for all features: {feature_columns}")
        
        # Calculate correlation matrix
        correlation_data = self.features[feature_columns].fillna(0)
        correlation_matrix = correlation_data.corr()

        # --- Enhanced Visualization Logic ---
        num_features = len(correlation_matrix.columns)

        # Dynamic figure size and font size for annotations
        if num_features > 0:
            figsize = (max(10, num_features * 0.8), max(8, num_features * 0.6))
            
            # Determine if annotations should be shown based on matrix size
            show_annot = True
            annot_kws = {'size': 8}
            if num_features > 40:
                show_annot = False  # Too cluttered to show annotations
            elif num_features > 20:
                annot_kws = {'size': 6} # Smaller font for medium-sized matrices
        else:
            figsize = (10, 8)
            show_annot = False

        # Create correlation heatmap
        plt.figure(figsize=figsize)
        
        # Create mask for upper triangle to show only lower triangle
        mask = np.triu(np.ones_like(correlation_matrix, dtype=bool))
        
        # Generate heatmap
        sns.heatmap(correlation_matrix, 
                   mask=mask,
                   annot=show_annot, 
                   cmap='RdBu_r', 
                   center=0,
                   square=True,
                   fmt='.2f',
                   cbar_kws={"shrink": .8},
                   annot_kws=annot_kws)
        
        plt.title('Feature Correlation Matrix', fontsize=16, pad=20)
        plt.xticks(rotation=45, ha='right')
        plt.yticks(rotation=0)
        plt.tight_layout()
        plt.savefig(self.results_dir / 'correlation_matrix.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        # Save correlation matrix to CSV
        correlation_matrix.to_csv(self.results_dir / 'correlation_matrix.csv')
        print(f"Saved correlation matrix to '{self.results_dir / 'correlation_matrix.csv'}'")
        
        # Print highly correlated features
        print("\nHighly Correlated Feature Pairs (|r| > 0.7):")
        print("=" * 50)
        
        high_corr_pairs = []
        for i in range(len(correlation_matrix.columns)):
            for j in range(i+1, len(correlation_matrix.columns)):
                if abs(correlation_matrix.iloc[i, j]) > 0.7:
                    feature1 = correlation_matrix.columns[i]
                    feature2 = correlation_matrix.columns[j]
                    high_corr_pairs.append((feature1, feature2, correlation_matrix.iloc[i, j]))
                    print(f"{feature1} <-> {feature2}: {correlation_matrix.iloc[i, j]:.3f}")
        
        if not high_corr_pairs:
            print("No highly correlated feature pairs found.")
        
        return correlation_matrix
    
    def visualize_clusters(self):
        """Create visualizations of the clustering results."""
        if self.clusters is None:
            print("No clustering results found. Run perform_clustering first.")
            return
        
        print("Creating cluster visualizations...")
        
        # Clean data before visualization
        self.features = self.features.replace([np.inf, -np.inf, np.nan], 0)
        
        # Use the same features that were used for clustering
        if hasattr(self, 'clustering_features') and self.clustering_features is not None:
            feature_columns = self.clustering_features
            print(f"Using clustering features for visualization: {feature_columns}")
        else:
            # Fallback to all features if clustering_features not set
            feature_columns = [col for col in self.features.columns 
                              if col not in ['cell_id', 'cluster']]
            print(f"Using all features for visualization: {feature_columns}")
        
        # Validate that we have numeric data
        numeric_features = []
        for col in feature_columns:
            if col in self.features.columns and pd.api.types.is_numeric_dtype(self.features[col]):
                # Check if column has any non-zero values
                if (self.features[col] != 0).any():
                    numeric_features.append(col)
        
        if not numeric_features:
            print("Warning: No valid numeric features found for visualization")
            return
        
        feature_columns = numeric_features
        
        # 1. Cluster distribution
        plt.figure(figsize=(8, 6))
        cluster_counts = self.features['cluster'].value_counts().sort_index()
        
        # Create labels for the bar chart
        bar_labels = []
        for label in cluster_counts.index:
            if label == -1:
                bar_labels.append("Outliers")
            else:
                bar_labels.append(f"Cluster {label}")
                
        plt.bar(bar_labels, cluster_counts.values)
        plt.xlabel('Cluster')
        plt.ylabel('Number of Cells')
        plt.title('Distribution of Cells Across Clusters')
        plt.xticks(rotation=45, ha='right')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(self.results_dir / 'cluster_distribution.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        # 2. UMAP visualization
        self.create_umap_visualization()
        
        # 3. Correlation matrix
        self.create_correlation_matrix()
        
        # 4. Feature differences between clusters (KDE plots)
        unique_labels = sorted(self.features['cluster'].unique())
        
        # Use the same features that were used for clustering
        available_features = feature_columns  # Use the feature_columns we determined above
        
        # Create subplots based on actual number of features
        n_features = len(available_features)
        if n_features > 0:
            # Calculate subplot layout
            cols = min(3, n_features)
            rows = (n_features + cols - 1) // cols
            
            fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows))
            if n_features == 1:
                axes = [axes]
            elif rows == 1:
                axes = axes if n_features > 1 else [axes]
            else:
                axes = axes.flatten()
            
            for i, feature in enumerate(available_features):
                if i < len(axes):
                    for cluster_label in unique_labels:
                        cluster_data = self.features[self.features['cluster'] == cluster_label][feature]
                        
                        label_text = f'Cluster {cluster_label}'
                        if cluster_label == -1:
                            label_text = 'Outliers'
                        
                        sns.kdeplot(cluster_data, ax=axes[i], label=label_text, fill=True, alpha=0.5)
                    
                    axes[i].set_xlabel(feature.replace('_', ' ').title())
                    axes[i].set_ylabel('Density')
                    axes[i].set_title(f'Distribution of {feature.replace("_", " ").title()}')
                    axes[i].legend()
                    axes[i].grid(True, alpha=0.3)
            
            # Hide empty subplots
            for i in range(n_features, len(axes)):
                axes[i].set_visible(False)
        
            plt.tight_layout()
            plt.savefig(self.results_dir / 'feature_distributions.png', dpi=300, bbox_inches='tight')
            plt.show()
        
        # 5. Box plots for each feature by cluster
        if n_features > 0:
            cols = min(3, n_features)
            rows = (n_features + cols - 1) // cols
            
            fig, axes = plt.subplots(rows, cols, figsize=(5*cols, 4*rows))
            if n_features == 1:
                axes = [axes]
            elif rows == 1:
                axes = axes if n_features > 1 else [axes]
            else:
                axes = axes.flatten()
            
            for i, feature in enumerate(available_features):
                if i < len(axes):
                    data_for_boxplot = [self.features[self.features['cluster'] == cluster_label][feature].values 
                                      for cluster_label in unique_labels]
                    
                    labels = []
                    for cluster_label in unique_labels:
                        if cluster_label == -1:
                            labels.append("Outliers")
                        else:
                            labels.append(f'Cluster {cluster_label}')
                    
                    axes[i].boxplot(data_for_boxplot, labels=labels)
                    axes[i].set_ylabel(feature.replace('_', ' ').title())
                    axes[i].set_title(f'Box Plot: {feature.replace("_", " ").title()}')
                    axes[i].grid(True, alpha=0.3)
            
            # Hide empty subplots
            for i in range(n_features, len(axes)):
                axes[i].set_visible(False)
        
            plt.tight_layout()
            plt.savefig(self.results_dir / 'feature_boxplots.png', dpi=300, bbox_inches='tight')
            plt.show()
        
        # 6. Cluster summary statistics
        print("\nCluster Summary Statistics:")
        print("=" * 50)
        
        for cluster_label in unique_labels:
            cluster_data = self.features[self.features['cluster'] == cluster_label]
            
            if cluster_label == -1:
                print(f"\nOutliers (n={len(cluster_data)}):")
            else:
                print(f"\nCluster {cluster_label} (n={len(cluster_data)}):")
            
            print("-" * 30)
            
            for feature in available_features:
                if feature in cluster_data.columns:
                    mean_val = cluster_data[feature].mean()
                    std_val = cluster_data[feature].std()
                    print(f"{feature.replace('_', ' ').title()}: {mean_val:.2f} ± {std_val:.2f}")

    def show_feature_removal_summary(self):
        """Display summary of removed features and their impact."""
        if hasattr(self, 'removed_features') and self.removed_features:
            print("\nFeature Removal Summary:")
            print("=" * 50)
            print(f"Original number of features: {len(self.original_features.columns) - 1}")  # -1 for cell_id
            print(f"Features removed: {len(self.removed_features)}")
            print(f"Remaining features: {len(self.features.columns) - 2}")  # -2 for cell_id and cluster
            print(f"Reduction: {len(self.removed_features) / (len(self.original_features.columns) - 1) * 100:.1f}%")
            
            print("\nRemoved features:")
            for feature in sorted(self.removed_features):
                print(f"  - {feature}")
            
            print("\nRemaining features:")
            remaining_features = [col for col in self.features.columns 
                                if col not in ['cell_id', 'cluster']]
            for feature in sorted(remaining_features):
                print(f"  - {feature}")
        else:
            print("No features were removed during correlation filtering.")
    
    def save_blender_format(self):
        """Save cell data in format suitable for Blender rendering software."""
        if self.data is None or self.features is None:
            print("No data available for Blender export. Run complete analysis first.")
            return
        
        print("Creating Blender-compatible output...")
        
        # Create a mapping from cell_id to cluster
        cell_cluster_map = dict(zip(self.features['cell_id'], self.features['cluster']))
        
        # Prepare Blender data with original outline data plus cluster information
        blender_data = []
        
        for idx, row in self.data.iterrows():
            cell_id = row['Cell ID']
            timepoint = row['Timepoint']
            outline_points = row['outline_points']
            
            # Get cluster assignment for this cell
            cluster = cell_cluster_map.get(cell_id, -1)  # -1 if not found
            
            # Create Blender-compatible entry
            blender_entry = {
                'Cell_ID': cell_id,
                'Timepoint': timepoint,
                'Cluster': cluster,
                'Outline_Points': outline_points,
                'Point_Count': len(outline_points)
            }
            
            # Add individual point coordinates for easier Blender access
            for i, point in enumerate(outline_points):
                blender_entry[f'Point_{i}_X'] = point[0]
                blender_entry[f'Point_{i}_Y'] = point[1]
            
            blender_data.append(blender_entry)
        
        # Convert to DataFrame and save
        blender_df = pd.DataFrame(blender_data)
        blender_df.to_csv(self.results_dir / 'blender_cell_data.csv', index=False)
        print(f"Saved Blender-compatible data to '{self.results_dir / 'blender_cell_data.csv'}'")
        
        # Also create a simplified cluster mapping file
        cluster_mapping = self.features[['cell_id', 'cluster']].copy()
        cluster_mapping.columns = ['Cell_ID', 'Cluster']
        cluster_mapping.to_csv(self.results_dir / 'cell_cluster_mapping.csv', index=False)
        print(f"Saved cluster mapping to '{self.results_dir / 'cell_cluster_mapping.csv'}'")
        
        # Create cluster color mapping for Blender
        n_clusters = len(self.features['cluster'].unique())
        colors = plt.cm.Set1(np.linspace(0, 1, n_clusters))
        
        cluster_colors = []
        for i in range(n_clusters):
            cluster = self.features['cluster'].unique()[i]
            color = colors[i]
            cluster_colors.append({
                'Cluster': cluster,
                'Red': color[0],
                'Green': color[1], 
                'Blue': color[2],
                'Alpha': 1.0,
                'Hex': f"#{int(color[0]*255):02x}{int(color[1]*255):02x}{int(color[2]*255):02x}"
            })
        
        color_df = pd.DataFrame(cluster_colors)
        color_df.to_csv(self.results_dir / 'cluster_colors.csv', index=False)
        print(f"Saved cluster colors to '{self.results_dir / 'cluster_colors.csv'}'")
        
        return blender_df, cluster_mapping, color_df
    
    def save_results(self):
        """Save clustering results to CSV files."""
        if self.features is None:
            print("No features to save. Run extract_features first.")
            return
        
        # Save features with cluster assignments
        features_path = self.results_dir / 'cell_features_with_clusters.csv'
        self.features.to_csv(features_path, index=False)
        print(f"Saved features with clusters to '{features_path}'")
        
        # Save Blender-compatible format
        self.save_blender_format()
        
        # Save removed features information
        if hasattr(self, 'removed_features') and self.removed_features:
            removed_features_info = {
                'removed_features': self.removed_features,
                'original_feature_count': len(self.original_features.columns) - 1 if hasattr(self, 'original_features') else 0,
                'remaining_feature_count': len(self.features.columns) - 2,  # -2 for cell_id and cluster
                'reduction_percentage': len(self.removed_features) / (len(self.original_features.columns) - 1) * 100 if hasattr(self, 'original_features') and (len(self.original_features.columns) - 1) > 0 else 0
            }
            
            # Save as a simple text file
            removed_features_path = self.results_dir / 'removed_features.txt'
            with open(removed_features_path, 'w') as f:
                f.write("Feature Removal Summary\n")
                f.write("=" * 30 + "\n")
                f.write(f"Original features: {removed_features_info['original_feature_count']}\n")
                f.write(f"Removed features: {len(self.removed_features)}\n")
                f.write(f"Remaining features: {removed_features_info['remaining_feature_count']}\n")
                f.write(f"Reduction: {removed_features_info['reduction_percentage']:.1f}%\n\n")
                f.write("Removed features:\n")
                for feature in sorted(self.removed_features):
                    f.write(f"  - {feature}\n")
            
            print(f"Saved removed features info to '{removed_features_path}'")
        
        # Save cluster summary
        if self.clusters is not None:
            n_clusters = self.clusters['n_clusters']
            summary_data = []
            
            # Use remaining features for summary
            remaining_features = [col for col in self.features.columns 
                                if col not in ['cell_id', 'cluster']]
            
            for cluster in range(n_clusters):
                cluster_data = self.features[self.features['cluster'] == cluster]
                summary = {'cluster': cluster, 'count': len(cluster_data)}
                
                for feature in remaining_features:
                    if feature in cluster_data.columns:
                        summary[f'{feature}_mean'] = cluster_data[feature].mean()
                        summary[f'{feature}_std'] = cluster_data[feature].std()
                
                summary_data.append(summary)
            
            summary_df = pd.DataFrame(summary_data)
            summary_path = self.results_dir / 'cluster_summary.csv'
            summary_df.to_csv(summary_path, index=False)
            print(f"Saved cluster summary to '{summary_path}'")
    
    def run_complete_analysis(self, n_clusters=None):
        """Run the complete clustering analysis pipeline."""
        print("Starting complete clustering analysis...")
        print("=" * 50)
        
        # Load data
        self.load_data()
        
        # Extract features
        self.extract_features()
        
        # Find optimal clusters if not specified
        if n_clusters is None:
            n_clusters = self.find_optimal_clusters()
        
        # Perform clustering
        self.perform_clustering(n_clusters)
        
        # Show feature removal summary
        self.show_feature_removal_summary()
        
        # Visualize results
        self.visualize_clusters()
        
        # Save results
        self.save_results()
        
        print("\nAnalysis complete!")
        print(f"Results saved in the 'Clustering' directory")


def main():
    """Main function to run the clustering analysis."""
    # Initialize analyzer
    analyzer = CellClusteringAnalyzer('processing/mesh_creation/outline_data.csv')
    
    # Run complete analysis
    analyzer.run_complete_analysis()


if __name__ == "__main__":
    main()